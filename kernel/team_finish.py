"""Submit a team worktree without repeatedly merging moving main into each worker."""

from __future__ import annotations

from pathlib import Path

from kernel import team_tasks
from kernel.exit_gate import verify_checkout
from kernel.task import fail


def finish(shared: Path, task_file: Path, text: str, branch: str, tree: Path | None) -> int:
    from kernel.task_finish import (_after_pr, _archive, _local_base, _open_pr, _small_overrun, uncommitted)
    from kernel.workboard import field, list_field
    from kernel.context import default_branch

    receipt = team_tasks.load(shared, task_file.stem)
    if not receipt.get("task_id"):
        return fail("team task has no coordinator receipt; recover its claim before submitting", 2)
    state = field(text, "상태")  # ko-ok: local task-board key
    current = team_tasks.refresh(shared, task_file.stem)
    if state.startswith("PR#") and current["state"] != "active":
        if current["state"] != "merged":
            print(f"[TEAM] {task_file.stem} is {current['state']}; waiting for CI, merge and coordinator reconciliation.")
            return 0
        return _after_pr(shared, task_file, text, branch, tree, state.removeprefix("PR#"))
    if tree is None:
        return fail("team task worktree is missing; resume it before submitting", 2)
    dirty = uncommitted(tree)
    if dirty:
        return fail("commit worktree changes before submitting:\n" + "\n".join(dirty), 1)
    if current["state"] == "active":
        team_tasks.operation(shared, task_file.stem, "renew")
        overrun = _small_overrun(tree, text, _local_base(shared), task_file.stem)
        if overrun:
            return fail(overrun, 1)
        _archive(shared, tree, task_file.stem, list_field(text, "산출물"))  # ko-ok: local board key
        code, lines = verify_checkout(tree) or (2, ["team submission requires an installed runner"])
        if code:
            return fail("team worktree verification failed:\n" + "\n".join(lines), code)
        team_tasks.submit(tree, task_file.stem)
    elif current["state"] not in ("submitted", "verified"):
        return fail(f"team task is {current['state']}; renew/reclaim it before submitting", 1)
    receipt = team_tasks.load(shared, task_file.stem)
    if team_tasks.git_value(tree, "rev-parse", "HEAD") != receipt["head_sha"]:
        return fail("submitted head changed; withdraw the old candidate before editing and resubmitting", 1)
    base = default_branch()
    if not base:
        return fail("team submission requires a known origin default branch", 2)
    return _open_pr(task_file, branch, tree, f"origin/{base}")
