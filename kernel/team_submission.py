"""Fenced ownership and immutable candidate transitions for a team task.

Worker proofs are untrusted metadata. Only the integration transport may attest
the actual Git diff, verification evidence and externally confirmed merge.
"""

from __future__ import annotations

import sqlite3

from kernel.team_resources import TeamError, authorized_paths, commit_sha
from kernel.team_state import encode


def fenced(task: dict, payload: dict, actor: str, *, owner: bool = True) -> None:
    """Every mutation carries the current epoch; the actor comes from authentication."""
    epoch = payload.get("epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch != task["epoch"]:
        raise TeamError("stale task epoch; read the current task before retrying")
    if owner and task["actor"] != actor:
        raise TeamError("task belongs to another actor", 403)


def require_state(task: dict, *states: str) -> None:
    """Transition policies are explicit; lease expiry never resumes a queued task."""
    if task["state"] not in states:
        raise TeamError(f"task is {task['state']}; expected {' or '.join(states)}")


def proof_from(payload: dict) -> dict:
    """Keep proofs JSON serializable and bounded before persistence."""
    proof = payload.get("proof", {})
    if not isinstance(proof, dict) or len(encode(proof)) > 65536:
        raise TeamError("proof must be a JSON object of at most 65536 characters", 400)
    return proof


def submit(connection: sqlite3.Connection, task: dict, payload: dict, now: float) -> None:
    """Freeze the candidate pair; a retry may repeat it but cannot replace its head."""
    require_state(task, "active", "submitted")
    base_sha, head_sha = commit_sha(payload, "base_sha"), commit_sha(payload, "head_sha")
    if base_sha != task["base_sha"]:
        raise TeamError("submitted base_sha differs from the claimed base")
    worker_proof = proof_from(payload)
    if task["state"] == "submitted":
        if head_sha != task["head_sha"] or worker_proof != task["worker_proof"]:
            raise TeamError("submitted candidates are immutable; cancel and claim a new task")
        return
    connection.execute(
        "UPDATE team_tasks SET head_sha=?,worker_proof=?,state='submitted',updated_at=? WHERE task_id=?",
        (head_sha, encode(worker_proof), now, task["task_id"]),
    )


def verify(connection: sqlite3.Connection, task: dict, payload: dict, now: float) -> None:
    """Bind trusted diff and test evidence to exactly this epoch and SHA pair."""
    require_state(task, "submitted", "verified")
    for name in ("base_sha", "head_sha"):
        if commit_sha(payload, name) != task[name]:
            raise TeamError(f"verification {name} differs from the submitted candidate")
    paths = authorized_paths(payload.get("changed_paths"), task["resources"])
    proof = proof_from(payload)
    for name in ("tested_sha", "tree_sha"):
        commit_sha(proof, name)
    if not isinstance(proof.get("policy_digest"), str) or not proof["policy_digest"].strip():
        raise TeamError("verification proof requires policy_digest", 400)
    bound = {**proof, "task_id": task["task_id"], "epoch": task["epoch"],
             "base_sha": task["base_sha"], "head_sha": task["head_sha"]}
    if task["state"] == "verified" and task["changed_paths"] != paths:
        raise TeamError("the trusted diff of an immutable submitted candidate cannot change")
    connection.execute(
        "UPDATE team_tasks SET state='verified',proof=?,changed_paths=?,updated_at=? WHERE task_id=?",
        (encode(bound), encode(paths), now, task["task_id"]),
    )


def merged(connection: sqlite3.Connection, task: dict, payload: dict, now: float) -> None:
    """Only trusted integration can release a verified task after merge confirmation."""
    require_state(task, "verified", "merged")
    if commit_sha(payload, "head_sha") != task["head_sha"]:
        raise TeamError("merge head_sha differs from the verified candidate")
    connection.execute("UPDATE team_tasks SET state='merged',updated_at=? WHERE task_id=?", (now, task["task_id"]))


def withdraw(connection: sqlite3.Connection, task: dict, now: float, lease_seconds: int) -> None:
    """The owner edits a new generation while keeping every existing reservation."""
    require_state(task, "submitted", "verified")
    connection.execute(
        "UPDATE team_tasks SET state='active',epoch=epoch+1,lease_until=?,head_sha='',worker_proof='{}',"
        "proof='{}',changed_paths='[]',updated_at=? WHERE task_id=?",
        (now + lease_seconds, now, task["task_id"]),
    )
