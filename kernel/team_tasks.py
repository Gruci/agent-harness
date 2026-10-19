"""Team task receipts and lifecycle integration; local state never contains credentials."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

from kernel import profile
from kernel.context import git_common_dir
from kernel.isolation import GENERATED


def git_value(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    if done.returncode:
        raise ValueError(f"Git operation failed: {' '.join(args[:2])}")
    return done.stdout.strip()


def receipt_path(root: Path, scope: str) -> Path:
    common = git_common_dir(root)
    if common is None:
        raise ValueError("Team tasks require a Git checkout")
    name = hashlib.sha256(scope.encode()).hexdigest()
    return common / "harness-team" / f"{name}.json"


def load(root: Path, scope: str) -> dict:
    path = receipt_path(root, scope)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(root: Path, scope: str, receipt: dict) -> None:
    path = receipt_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def client():
    from kernel.team_client import Client

    if not profile.TEAM or profile.MERGE_FLOW != "pr":
        raise ValueError("Enable TEAM and MERGE_FLOW='pr' before using team commands")
    return Client(profile.TEAM)


def check_repository(root: Path) -> None:
    remote = git_value(root, "remote", "get-url", "origin")
    if profile.repo_key(remote) != profile.repo_key(str(profile.TEAM["repository"])):
        raise ValueError("TEAM repository does not match origin")


def claim(root: Path, scope: str, sid: str, branch: str, touch: list[str], base: str,
          goal: str = "", depends_on: list[str] | None = None) -> dict:
    if not profile.TEAM:
        return {}
    check_repository(root)
    receipt = load(root, scope)
    if not receipt or receipt.get("state") in ("cancelled", "merged"):
        receipt = {"scope": scope, "sid": sid, "request_id": uuid.uuid4().hex,
                   "branch": branch, "base_sha": git_value(root, "rev-parse", "--verify", f"{base}^{{commit}}"),
                   "resources": touch, "goal": goal, "depends_on": depends_on or []}
        save(root, scope, receipt)  # Persist the retry key before a possibly ambiguous network failure.
    payload = {key: receipt[key] for key in ("scope", "request_id", "branch", "base_sha", "resources", "goal", "depends_on")}
    from kernel.team_store import TeamError

    try:
        granted = client().request("claim", payload)
    except TeamError as error:
        if 400 <= error.status < 500 and not receipt.get("task_id"):
            receipt_path(root, scope).unlink(missing_ok=True)
        raise
    receipt.update(granted)
    receipt["sid"] = sid
    save(root, scope, receipt)
    return receipt


def operation(root: Path, scope: str, name: str, extra: dict | None = None, *, integration: bool = False) -> dict:
    from kernel.task_lock import task_lock

    with task_lock(root, "team-receipt:" + scope):
        return _operation(root, scope, name, extra, integration)


def _operation(root: Path, scope: str, name: str, extra: dict | None, integration: bool) -> dict:
    from kernel.team_store import TeamError

    receipt = load(root, scope)
    if not receipt.get("task_id"):
        raise ValueError("No team receipt; start the task through the coordinator first")
    payload = {"task_id": receipt["task_id"], "epoch": receipt["epoch"], **(extra or {})}
    if name not in ("status", "list"):
        pending = receipt.get("pending_operation")
        if pending and (pending["operation"] != name or
                        {key: value for key, value in pending["payload"].items() if key != "request_id"} != payload):
            raise ValueError("Retry the pending team operation before starting a different mutation")
        if pending:
            payload = pending["payload"]
        else:
            payload["request_id"] = uuid.uuid4().hex
            receipt["pending_operation"] = {"operation": name, "payload": payload}
            save(root, scope, receipt)
    try:
        if integration:
            from kernel.team_git import _client

            connection = _client(integration=True)
        else:
            connection = client()
        result = connection.request(name, payload)
    except TeamError as error:
        if 400 <= error.status < 500:
            receipt.pop("pending_operation", None)
            save(root, scope, receipt)
        raise
    if result.get("epoch", receipt["epoch"]) != receipt["epoch"] and name != "withdraw":
        raise ValueError("Team ownership changed; reclaim explicitly instead of adopting another attempt")
    receipt.update(result)
    receipt.pop("pending_operation", None)
    save(root, scope, receipt)
    return receipt


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    git_value(root, "merge-base", "--is-ancestor", base, head)
    done = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"], cwd=root,
                          capture_output=True, timeout=60)
    if done.returncode:
        raise ValueError("Could not inspect submitted Git changes")
    return [path for path in done.stdout.decode("utf-8").split("\0") if path and path not in GENERATED
            and not path.startswith("docs/tasks/archive/")]


def submit(root: Path, scope: str) -> dict:
    receipt = load(root, scope)
    head = git_value(root, "rev-parse", "HEAD")
    from kernel.team_resources import covers

    paths = changed_paths(root, receipt["base_sha"], head)
    outside = [path for path in paths if not covers(receipt["resources"], path)]
    if outside:
        raise ValueError("Changes outside reserved resources: " + ", ".join(outside))
    return operation(root, scope, "submit", {"base_sha": receipt["base_sha"], "head_sha": head})


def release(root: Path, scope: str) -> None:
    if profile.TEAM and load(root, scope).get("task_id"):
        operation(root, scope, "cancel")


def recover_pending(root: Path, scope: str) -> dict:
    from kernel.task_lock import task_lock

    with task_lock(root, "team-receipt:" + scope):
        return _recover_pending(root, scope)


def _recover_pending(root: Path, scope: str) -> dict:
    """Replay while the caller holds the receipt lock; never acquire it recursively."""
    receipt = load(root, scope)
    pending = receipt.get("pending_operation")
    if not pending:
        return receipt
    if pending["operation"] == "withdraw":
        raise ValueError("Retry scope withdraw to recover the pending integration operation")
    extra = {key: value for key, value in pending["payload"].items()
             if key not in ("task_id", "epoch", "request_id")}
    return _operation(root, scope, pending["operation"], extra, False)


def refresh(root: Path, scope: str) -> dict:
    """Refresh an existing attempt without adopting another owner's generation."""
    from kernel.task_lock import task_lock

    with task_lock(root, "team-receipt:" + scope):
        receipt = _recover_pending(root, scope)
        if not receipt.get("task_id"):
            raise ValueError("No team receipt; start the task through the coordinator first")
        current = client().request("status", {"task_id": receipt["task_id"]})
        if current["epoch"] != receipt["epoch"] or current["actor"] != receipt["actor"]:
            raise ValueError("Team ownership changed; this attempt cannot be resumed")
        receipt.update(current)
        save(root, scope, receipt)
        return receipt


def edit_guard(root: Path, paths: list[Path]):
    """Local hints fail early; the trusted server revalidates the real Git diff at admission."""
    if not profile.TEAM:
        return None
    from kernel.team_resources import covers
    from kernel.workboard import branch_of, task_files, board_dir
    from kernel.worktree import worktree_of
    from kernel.workspace import Finding

    for task_file, text in task_files(board_dir()):
        branch = branch_of(" | ".join(text.split()))
        tree = worktree_of(branch) if branch else None
        selected = [p for p in paths if tree and p.resolve().is_relative_to(tree.resolve())]
        if not selected:
            continue
        receipt = load(root, task_file.stem)
        reason = ""
        if not receipt.get("task_id") or receipt.get("state") != "active":
            reason = "this task has no active team claim"
        elif float(receipt.get("lease_until", 0)) <= time.time():
            reason = "the team lease expired; renew or reclaim it before editing"
        else:
            if float(receipt["lease_until"]) - time.time() < 60:
                receipt = operation(root, task_file.stem, "renew")
            outside = [p.relative_to(tree).as_posix() for p in selected
                       if p.relative_to(tree).as_posix() not in GENERATED
                       and not covers(receipt["resources"], p.relative_to(tree).as_posix())]
            if outside:
                reason = "reserve additional paths before editing: " + ", ".join(outside)
        if reason:
            return Finding("team", "team_claim", True, f"[TEAM] {reason}", (reason,))
    return None


def reclaim(root: Path, scope: str) -> dict:
    """Explicit recovery after expiry; another active owner is never overwritten."""
    from kernel.task_lock import task_lock

    with task_lock(root, "team-receipt:" + scope):
        return _reclaim(root, scope)


def _reclaim(root: Path, scope: str) -> dict:
    receipt = load(root, scope)
    if not receipt.get("task_id"):
        raise ValueError("No saved task metadata to reclaim")
    payload = {key: receipt[key] for key in ("scope", "branch", "base_sha", "resources", "goal", "depends_on")}
    pending = receipt.get("pending_reclaim")
    payload["request_id"] = pending or uuid.uuid4().hex
    receipt["pending_reclaim"] = payload["request_id"]
    save(root, scope, receipt)
    granted = client().request("claim", payload)
    receipt.update(granted, request_id=payload["request_id"])
    receipt.pop("pending_reclaim", None)
    save(root, scope, receipt)
    return receipt


def heartbeat(root: Path, scope: str, interval: float = 30, once: bool = False) -> dict:
    """Run while a worker is active; stop renewing when it submits or is cancelled."""
    if not 0 < interval <= 60:
        raise ValueError("Heartbeat interval must be greater than zero and at most 60 seconds")
    while True:
        receipt = load(root, scope)
        if receipt.get("state") != "active":
            return receipt
        receipt = operation(root, scope, "renew")
        if once:
            return receipt
        time.sleep(min(interval, max(0.1, (float(receipt["lease_until"]) - time.time()) / 3)))
