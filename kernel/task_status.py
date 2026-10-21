"""Read-only session context from the shared board, live worktrees and local history.

Archive checkboxes are historical text, never evidence of unfinished work.
An archive commit on the local base is not evidence of a push or successful tests.
"""

from pathlib import Path
import subprocess

from kernel.context import git_dirs
from kernel.task import git
from kernel.workboard import branch_of, field, list_field, sid_of, task_files


def _worktrees(shared: Path) -> dict[str, str]:
    done = git(shared, "worktree", "list", "--porcelain", "-z")
    if done.returncode:
        raise ValueError("Git worktree inventory could not be read")
    trees: dict[str, str] = {}
    for block in done.stdout.split("\0\0"):
        fields = dict(part.split(" ", 1) for part in block.split("\0") if " " in part)
        if fields.get("branch") and Path(fields.get("worktree", "")).is_dir():
            trees[fields["branch"].removeprefix("refs/heads/")] = fields.get("worktree", "")
    return trees


def _open_task(path: Path, text: str, trees: dict[str, str], sid: str) -> list[str]:
    owner = sid_of(text) or "unknown"
    branch = branch_of(" | ".join(text.split())) or "unknown"
    # ko-ok: shared task-board keys and planning state
    planning = field(text, "상태") == "계획"
    state = "planning" if planning else "open"
    location = trees.get(branch, "no worktree yet" if planning else "worktree missing")
    yours = " yours" if sid and owner == sid[:8] else ""
    lines = [f"[TASK STATUS] {path.stem}: {state}{yours}; owner #{owner}; {branch}; {location}"]
    # ko-ok: shared task-board artifact key
    artifacts = list_field(text, "산출물")
    plans = [rel for rel in artifacts if Path(rel).name.removeprefix("wip_").startswith("plan_")]
    if plans:
        plan = path.parent.parent / plans[0]
        note = "current scope and recorded decisions" if plan.is_file() else "plan missing; inspect the shared board"
        lines.append(f"[TASK STATUS] Read first: {plan.as_posix()} ({note}).")
    if sid and owner == sid[:8]:
        action = "review the plan and its approval" if planning else "continue in the worktree; review the plan before editing"
        if not planning and branch not in trees:
            action = "recover the missing worktree from its branch before editing"
        lines.append(f"[TASK STATUS] Next: {action}.")
    return lines


def _last_archive(shared: Path) -> list[str]:
    remote = git(shared, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    suggested = remote.stdout.strip().removeprefix("refs/remotes/origin/") if remote.returncode == 0 else ""
    base = next((name for name in (suggested, "main", "master")
                 if name and git(shared, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0), "")
    done = git(shared, "log", "-1", "--format=%h%x09%s", "--grep=^chore(task): archive ", base or "HEAD", "--")
    if done.returncode:
        raise ValueError("local history could not be read")
    if not done.stdout.strip():
        return []
    sha, subject = done.stdout.strip().split("\t", 1)
    scope = subject.removeprefix("chore(task): archive ").removesuffix(" design docs and harness trace")
    label = "Last landed" if base else "Latest local archive (default branch unknown)"
    lines = [f"[TASK STATUS] {label}: {scope} ({sha}; local archive, not proof of push or tests)."]
    plans = sorted(path for path in (shared / "docs/tasks/archive").glob("*/plan_*.md")
                   if path.parent.name.endswith("-" + scope))
    if plans:
        lines.append(f"[TASK STATUS] Recorded context: {plans[-1].as_posix()} (historical decisions and results).")
    return lines


def status(root: Path, sid: str = "") -> tuple[int, str]:
    """Return a bounded status without writes, fetches, tests or ownership changes."""
    try:
        found = git_dirs(root)
        if found is None:
            raise ValueError("Git checkout could not be identified")
        shared = found[1].parent
        tasks = task_files(shared / "workboard")
        tasks.sort(key=lambda item: (sid_of(item[1]) != sid[:8], item[0].name))
        lines: list[str] = []
        if tasks:
            trees = _worktrees(shared)
            for path, text in tasks[:3]:
                lines.extend(_open_task(path, text, trees, sid))
            if len(tasks) > 3:
                lines.append(f"[TASK STATUS] {len(tasks) - 3} more open tasks: inspect the shared workboard.")
        else:
            lines.append("[TASK STATUS] No open tasks on the shared board.")
            lines.extend(_last_archive(shared))
            lines.append("[TASK STATUS] Next: name a new scope or inspect the last landed task; no open task is implied by archived checkboxes.")
        from kernel.graph_workflow import DIRECTORY, pending

        for proposal in pending(root)[:2]:
            lines.append(f"[TASK STATUS] Decision pending: {DIRECTORY}/{proposal['id']}.json — read before changing classification.")
        return 0, "\n".join(lines)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return 2, f"[TASK STATUS] Unavailable: {error}. Inspect Git and the shared workboard; completion is unknown."
