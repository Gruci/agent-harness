"""Withdraw frozen candidates only after the provider confirms their PR is closed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from kernel import team_git, team_tasks
from kernel.task_lock import task_lock


def _provider_state(root: Path, branch: str, head: str) -> str:
    """A failed lookup or a different head is never evidence that a queue entry is gone."""
    result = subprocess.run(["gh", "pr", "view", branch, "--json", "state,headRefOid"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise ValueError("Could not confirm the candidate PR; reservations remain held")
    try:
        pull_request = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("The provider returned an invalid PR response; reservations remain held") from exc
    if not isinstance(pull_request, dict) or pull_request.get("headRefOid") != head:
        raise ValueError("The provider PR head differs from the frozen candidate; reservations remain held")
    state = pull_request.get("state")
    if state == "MERGED":
        raise ValueError("The candidate already merged; reconcile it instead of withdrawing it")
    if state not in ("OPEN", "CLOSED"):
        raise ValueError("The provider PR state is unknown; reservations remain held")
    return state


def withdraw(root: Path, scope: str) -> dict:
    """Use integration authority to close a PR before resetting its frozen generation.

    A lost close response is resolved by another provider lookup. A pending
    coordinator withdrawal has already passed that check and is replayed with
    its durable request ID before interpreting a possibly advanced epoch.
    """
    with task_lock(root, "team-receipt:" + scope):
        return _withdraw_locked(root, scope)


def _withdraw_locked(root: Path, scope: str) -> dict:
    """Keep provider evidence bound to the same receipt until its mutation is saved."""
    team_tasks.check_repository(root)
    receipt = team_tasks.load(root, scope)
    if not receipt.get("task_id"):
        raise ValueError("No team receipt exists for this scope")
    pending = receipt.get("pending_operation")
    if pending:
        if pending.get("operation") != "withdraw":
            raise ValueError("Retry the pending team operation before withdrawing the candidate")
        return team_tasks._operation(root, scope, "withdraw", None, True)
    connection = team_git._client(integration=True)
    current = connection.request("status", {"task_id": receipt["task_id"]})
    if current["epoch"] != receipt["epoch"]:
        raise ValueError("Team ownership changed; this receipt cannot withdraw the candidate")
    if current["state"] == "merged":
        raise ValueError("The candidate already merged; reconcile it instead of withdrawing it")
    if current["state"] not in ("submitted", "verified"):
        raise ValueError("Only a submitted or verified candidate can be withdrawn")
    state = _provider_state(root, current["branch"], current["head_sha"])
    if state == "OPEN":
        try:
            subprocess.run(["gh", "pr", "close", current["branch"]], cwd=root, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass  # Only the subsequent CLOSED confirmation authorizes a coordinator mutation.
        state = _provider_state(root, current["branch"], current["head_sha"])
    if state != "CLOSED":
        raise ValueError("The candidate PR is still open; remove it from the queue before withdrawing it")
    return team_tasks._operation(root, scope, "withdraw", None, True)
