"""Persist and deduplicate classification notices for any AI hook client."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kernel.graph_workflow import _write, current_hash

QUEUE = "docs/architecture/decision-requests.json"


def report(root: Path, messages: list[str], session: str) -> list[dict]:
    """Queue once per issue and surface once per session; never approve a change."""
    path = root / QUEUE
    queue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    base = current_hash(root)
    emitted = []
    active = set()
    for message in sorted(set(messages)):
        key = hashlib.sha256((base + "\n" + message).encode()).hexdigest()
        active.add(key)
        item = queue.setdefault(key, {"id": key, "message": message, "state": "awaiting_user", "sessions": []})
        if item["state"] == "resolved":
            item.update(state="awaiting_user", sessions=[])
        if session not in item["sessions"]:
            emitted.append({"type": "needs_decision", "id": key, "message": message,
                            "action": "Propose component name, responsibility, location and dependency delta to the user. Record their answer before applying."})
            item["sessions"].append(session)
    for key, item in queue.items():
        if key not in active:
            item["state"] = "resolved"
    if queue:
        _write(path, queue)
    return emitted
