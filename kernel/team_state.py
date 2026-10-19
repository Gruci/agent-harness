"""SQLite schema and durable receipts/events for the transactional team registry.

The coordinator owns this local database. Remote workers use its authenticated
transport; SQLite is never a database shared over a network filesystem.
All writes, expiration, resource checks and receipts share BEGIN IMMEDIATE.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from kernel.team_resources import TeamError

RESERVING = ("active", "submitted", "verified")
SCHEMA = """
CREATE TABLE IF NOT EXISTS team_tasks (
    task_id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    scope TEXT NOT NULL,
    actor TEXT NOT NULL,
    branch TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    head_sha TEXT NOT NULL DEFAULT '',
    epoch INTEGER NOT NULL CHECK(epoch > 0),
    state TEXT NOT NULL CHECK(state IN ('active','expired','submitted','verified','merged','cancelled')),
    lease_until REAL NOT NULL,
    goal TEXT NOT NULL,
    resources TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    worker_proof TEXT NOT NULL DEFAULT '{}',
    proof TEXT NOT NULL DEFAULT '{}',
    changed_paths TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS team_scope_reserved ON team_tasks(repository,scope)
    WHERE state IN ('active','submitted','verified');
CREATE INDEX IF NOT EXISTS team_repository_state ON team_tasks(repository,state);
CREATE TABLE IF NOT EXISTS team_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES team_tasks(task_id),
    epoch INTEGER NOT NULL,
    actor TEXT NOT NULL,
    operation TEXT NOT NULL,
    occurred_at REAL NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_requests (
    repository TEXT NOT NULL,
    actor TEXT NOT NULL,
    request_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    response TEXT NOT NULL,
    PRIMARY KEY(repository,actor,request_id)
);
"""
JSON_FIELDS = ("resources", "depends_on", "worker_proof", "proof", "changed_paths")


def encode(value: object) -> str:
    """Deterministic JSON for durable metadata and idempotency comparisons."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TeamError("payload must contain finite JSON values", 400) from exc


def connect(database: Path) -> sqlite3.Connection:
    """A connection per request lets threads/processes share one serialized writer."""
    connection = sqlite3.connect(database, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialize(database: Path) -> None:
    """Idempotent schema creation, before a Store begins accepting requests."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)


def response(row: sqlite3.Row) -> dict:
    """Return JSON metadata, never SQLite implementation objects."""
    value = dict(row)
    for field in JSON_FIELDS:
        value[field] = json.loads(value[field])
    return value


def event(connection: sqlite3.Connection, task: dict, actor: str, operation: str, now: float, detail: dict) -> None:
    """Events commit atomically with the state transition they describe."""
    connection.execute(
        "INSERT INTO team_events(repository,task_id,epoch,actor,operation,occurred_at,detail) VALUES (?,?,?,?,?,?,?)",
        (task["repository"], task["task_id"], task["epoch"], actor, operation, now, encode(detail)),
    )


def expire(connection: sqlite3.Connection, repository: str, now: float) -> None:
    """Only working leases expire; a submitted candidate keeps all reservations."""
    rows = connection.execute(
        "SELECT * FROM team_tasks WHERE repository=? AND state='active' AND lease_until<=?", (repository, now),
    ).fetchall()
    for row in rows:
        connection.execute("UPDATE team_tasks SET state='expired',updated_at=? WHERE task_id=?", (now, row["task_id"]))
        event(connection, response(row), "coordinator", "expired", now, {})


def task_by_id(connection: sqlite3.Connection, repository: str, task_id: str) -> dict:
    """Cross-repository task ids never expose or mutate another repository's task."""
    row = connection.execute("SELECT * FROM team_tasks WHERE repository=? AND task_id=?", (repository, task_id)).fetchone()
    if row is None:
        raise TeamError("task does not exist in this repository", 404)
    return response(row)
