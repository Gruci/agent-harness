"""Transactional task/lease/resource registry behind the team coordinator.

BEGIN IMMEDIATE serializes claim, expansion, fencing and receipts across threads
and processes. The privileged flag is an authenticated transport capability,
never a field accepted from worker JSON. Lease timestamps are UTC epoch seconds.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Callable

from kernel import team_state, team_submission
from kernel.team_resources import TeamError, commit_sha, overlaps, resources_from, text_field

OPERATIONS = frozenset(("claim", "renew", "expand", "submit", "withdraw", "cancel", "status", "list", "verify", "merged"))
PRIVILEGED = frozenset(("verify", "merged"))


class Store:
    """One coordinator database; repository identity partitions all reservations."""

    def __init__(self, database: Path, lease_seconds: int = 300, max_active: int = 16,
                 clock: Callable[[], float] = time.time):
        if (isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float))
                or not math.isfinite(lease_seconds) or lease_seconds <= 0):
            raise ValueError("lease_seconds must be positive and finite")
        if isinstance(max_active, bool) or not isinstance(max_active, int) or max_active <= 0:
            raise ValueError("max_active must be a positive integer")
        self.database = Path(database)
        self.lease_seconds, self.max_active, self.clock = lease_seconds, max_active, clock
        team_state.initialize(self.database)

    def request(self, actor: str, operation: str, payload: dict, *, privileged: bool = False) -> dict:
        """Apply one authenticated operation and its idempotency receipt atomically."""
        if operation not in OPERATIONS:
            raise TeamError("unknown team operation", 400)
        if not isinstance(payload, dict):
            raise TeamError("payload must be an object", 400)
        actor = text_field({"actor": actor}, "actor", 128)
        repository = text_field(payload, "repository", 1024)
        if operation in PRIVILEGED and not privileged:
            raise TeamError("integration role required", 403)
        connection = team_state.connect(self.database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = float(self.clock())
            if not math.isfinite(now):
                raise TeamError("coordinator clock is unavailable", 503)
            team_state.expire(connection, repository, now)
            cached = self._receipt(connection, actor, operation, payload, repository)
            if cached is not None:
                connection.commit()
                return cached
            result = self._dispatch(connection, actor, operation, payload, repository, now, privileged)
            if operation not in ("status", "list"):
                team_state.event(connection, result, actor, operation, now, payload)
                self._save_receipt(connection, actor, operation, payload, repository, result)
            connection.commit()
            return result
        except sqlite3.Error as exc:
            connection.rollback()
            raise TeamError("coordinator database is unavailable; retry the same request id", 503) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _receipt(self, connection: sqlite3.Connection, actor: str, operation: str, payload: dict,
                 repository: str) -> dict | None:
        request_id = payload.get("request_id")
        if request_id is None or operation in ("status", "list"):
            return None
        text_field(payload, "request_id", 128)
        row = connection.execute(
            "SELECT * FROM team_requests WHERE repository=? AND actor=? AND request_id=?",
            (repository, actor, request_id),
        ).fetchone()
        if row is None:
            return None
        fingerprint = team_state.encode({"operation": operation, "payload": payload})
        if row["fingerprint"] != fingerprint:
            raise TeamError("request_id was already used with a different operation or payload")
        receipt = json.loads(row["response"])
        current = team_state.task_by_id(connection, repository, receipt["task_id"])
        if current["epoch"] != receipt["epoch"] or current["actor"] != receipt["actor"]:
            raise TeamError("idempotency receipt belongs to a stale task epoch")
        if current["state"] == "expired" and operation in ("claim", "renew", "expand", "submit", "withdraw"):
            raise TeamError("idempotency receipt belongs to an expired lease")
        if operation == "claim" and current["state"] != "active":
            raise TeamError("claim receipt no longer represents an active lease")
        return current

    def _save_receipt(self, connection: sqlite3.Connection, actor: str, operation: str, payload: dict,
                      repository: str, result: dict) -> None:
        request_id = payload.get("request_id")
        if request_id is None:
            return
        connection.execute("INSERT INTO team_requests VALUES (?,?,?,?,?)", (
            repository, actor, request_id, team_state.encode({"operation": operation, "payload": payload}),
            team_state.encode(result),
        ))

    def _dispatch(self, connection: sqlite3.Connection, actor: str, operation: str, payload: dict,
                  repository: str, now: float, privileged: bool) -> dict:
        if operation == "list":
            return self._list(connection, payload, repository)
        if operation == "claim":
            return self._claim(connection, actor, payload, repository, now)
        task_id = text_field(payload, "task_id", 64)
        task = team_state.task_by_id(connection, repository, task_id)
        if operation == "status":
            if payload.get("events"):
                events = connection.execute("SELECT * FROM team_events WHERE repository=? AND task_id=? ORDER BY event_id",
                                            (repository, task_id)).fetchall()
                task["events"] = [{**dict(row), "detail": json.loads(row["detail"])} for row in events]
            return task
        integration = operation in PRIVILEGED or (operation in ("cancel", "withdraw") and privileged)
        team_submission.fenced(task, payload, actor, owner=not integration)
        if operation == "renew":
            team_submission.require_state(task, "active")
            connection.execute("UPDATE team_tasks SET lease_until=?,updated_at=? WHERE task_id=?",
                               (now + self.lease_seconds, now, task_id))
        elif operation == "expand":
            self._expand(connection, task, payload, now)
        elif operation == "withdraw":
            if task["state"] == "verified" and not privileged:
                raise TeamError("integration must dequeue a verified candidate before withdrawal", 403)
            team_submission.withdraw(connection, task, now, self.lease_seconds)
        elif operation == "cancel":
            team_submission.require_state(task, "active", "expired", "submitted", "verified", "cancelled")
            if task["state"] in ("submitted", "verified") and not privileged:
                raise TeamError("only integration may cancel a submitted candidate", 403)
            connection.execute("UPDATE team_tasks SET state='cancelled',updated_at=? WHERE task_id=?", (now, task_id))
        else:
            getattr(team_submission, operation)(connection, task, payload, now)
        return team_state.task_by_id(connection, repository, task_id)

    def _list(self, connection: sqlite3.Connection, payload: dict, repository: str) -> dict:
        limit = payload.get("limit", 50)
        cursor = payload.get("cursor", "")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise TeamError("list limit must be between 1 and 100", 400)
        if not isinstance(cursor, str) or len(cursor) > 64:
            raise TeamError("invalid list cursor", 400)
        rows = connection.execute(
            "SELECT * FROM team_tasks WHERE repository=? AND task_id>? "
            "AND state IN ('active','submitted','verified') ORDER BY task_id LIMIT ?",
            (repository, cursor, limit + 1),
        ).fetchall()
        omitted = {"proof", "worker_proof", "changed_paths", "resources"}
        tasks = [{key: value for key, value in team_state.response(row).items() if key not in omitted}
                 for row in rows[:limit]]
        return {"repository": repository, "tasks": tasks,
                "next_cursor": tasks[-1]["task_id"] if len(rows) > limit else ""}

    def _reservations(self, connection: sqlite3.Connection, repository: str) -> list[dict]:
        rows = connection.execute(
            "SELECT * FROM team_tasks WHERE repository=? AND state IN ('active','submitted','verified')", (repository,),
        ).fetchall()
        return [team_state.response(row) for row in rows]

    def _check_resources(self, reservations: list[dict], resources: list[str], excluding: str = "") -> None:
        for task in reservations:
            if task["task_id"] == excluding:
                continue
            for resource in resources:
                if any(overlaps(resource, held) for held in task["resources"]):
                    raise TeamError(f"resource {resource} is reserved by task {task['task_id']}")

    def _dependencies(self, connection: sqlite3.Connection, repository: str, payload: dict) -> list[str]:
        values = payload.get("depends_on", [])
        if not isinstance(values, list) or len(values) > 256 or any(not isinstance(value, str) for value in values):
            raise TeamError("depends_on must be a list of task ids", 400)
        dependencies = sorted(set(values))
        for task_id in dependencies:
            dependency = team_state.task_by_id(connection, repository, task_id)
            if dependency["state"] != "merged":
                raise TeamError(f"dependency {task_id} has not merged")
        return dependencies

    def _claim(self, connection: sqlite3.Connection, actor: str, payload: dict, repository: str, now: float) -> dict:
        scope, branch = text_field(payload, "scope", 128), text_field(payload, "branch", 256)
        base_sha, resources = commit_sha(payload, "base_sha"), resources_from(payload)
        goal = payload.get("goal", "")
        if not isinstance(goal, str) or len(goal) > 8192:
            raise TeamError("goal must be a string of at most 8192 characters", 400)
        dependencies = self._dependencies(connection, repository, payload)
        reservations = self._reservations(connection, repository)
        if any(task["scope"] == scope for task in reservations):
            raise TeamError("scope is already reserved")
        if any(task["branch"].casefold() == branch.casefold() for task in reservations):
            raise TeamError("branch is already reserved by another task")
        if len(reservations) >= self.max_active:
            raise TeamError("repository concurrency capacity is full", 429)
        self._check_resources(reservations, resources)
        old = connection.execute(
            "SELECT * FROM team_tasks WHERE repository=? AND scope=? AND state='expired' ORDER BY updated_at DESC LIMIT 1",
            (repository, scope),
        ).fetchone()
        task_id, epoch = (old["task_id"], old["epoch"] + 1) if old else (uuid.uuid4().hex, 1)
        values = (repository, scope, actor, branch, base_sha, epoch, now + self.lease_seconds,
                  goal, team_state.encode(resources), team_state.encode(dependencies), now, now)
        if old:
            connection.execute(
                "UPDATE team_tasks SET repository=?,scope=?,actor=?,branch=?,base_sha=?,epoch=?,lease_until=?,goal=?,"
                "resources=?,depends_on=?,created_at=?,updated_at=?,state='active',head_sha='',worker_proof='{}',"
                "proof='{}',changed_paths='[]' WHERE task_id=?", (*values, task_id),
            )
        else:
            connection.execute(
                "INSERT INTO team_tasks(repository,scope,actor,branch,base_sha,epoch,lease_until,goal,resources,"
                "depends_on,created_at,updated_at,task_id,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'active')",
                (*values, task_id),
            )
        return team_state.task_by_id(connection, repository, task_id)

    def _expand(self, connection: sqlite3.Connection, task: dict, payload: dict, now: float) -> None:
        team_submission.require_state(task, "active")
        resources = sorted(set(task["resources"]) | set(resources_from(payload)))
        if len(resources) > 256:
            raise TeamError("a task may reserve at most 256 resources", 400)
        self._check_resources(self._reservations(connection, task["repository"]), resources, task["task_id"])
        connection.execute("UPDATE team_tasks SET resources=?,updated_at=? WHERE task_id=?",
                           (team_state.encode(resources), now, task["task_id"]))
