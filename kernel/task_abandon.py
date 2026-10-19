"""kernel/task_abandon.py — 내 과업을 버린다. `python -X utf8 -m kernel.task abandon --sid <sid8> [--scope <범위>]`.

버린 과업을 손으로 치우면 `git worktree remove --force`·`git branch -D`·보드 파일 삭제를 순서대로 해야 하고, 그 사이에
남의 과업을 건드리기 쉽다. 이 명령은 내 `#sid` 과업 하나만, 커밋 안 한 변경이 없을 때만 지운다. 커밋한 작업은
브랜치와 함께 사라지므로 사용자에게서 버린다는 답을 받은 뒤에만 부른다. research·plan 은 `docs/tasks/` 에 남는다.
"""

from __future__ import annotations

from pathlib import Path

from kernel.task import fail, git
from kernel.task_finish import my_task, uncommitted
from kernel.workboard import board_dir, branch_of
from kernel.worktree import worktree_of


def abandon(sid8: str, scope: str | None, discard_commits: bool = False) -> int:
    from kernel.task_lock import task_lock

    found = my_task(board_dir(), sid8, scope)
    if found is None:
        return 1
    with task_lock(board_dir().parent, "scope:" + found[0].stem):
        return _abandon(sid8, scope, discard_commits)


def _abandon(sid8: str, scope: str | None, discard_commits: bool = False) -> int:
    board = board_dir()
    shared = board.parent
    found = my_task(board, sid8, scope)
    if found is None:
        return 1
    task_file, text = found
    branch = branch_of(" | ".join(text.split())) or ""
    ahead = git(shared, "rev-list", "--count", f"HEAD..{branch}").stdout.strip() if branch else ""
    if ahead.isdigit() and int(ahead) and not discard_commits:
        return fail(f"{branch} has {ahead} commit(s) not merged — finish the task to keep them, or, only after the user "
                    "agrees to lose them, run abandon again with --discard-commits", 1)
    tree = worktree_of(branch)
    if tree is not None:
        dirty = uncommitted(tree)
        if dirty:
            return fail("uncommitted work in the worktree — commit it or discard it first:\n"
                        + "\n".join(f"  {line}" for line in dirty), 1)
        if Path.cwd().resolve().is_relative_to(tree.resolve()):
            return fail('run abandon from the main checkout — Claude: ExitWorktree(action="keep") first', 1)
    from kernel.team_tasks import release

    release(shared, task_file.stem)
    if tree is not None:
        removed = git(shared, "worktree", "remove", str(tree))
        if removed.returncode:
            return fail(f"git worktree remove refused — {removed.stderr.strip()[:300]}", 1)
    if branch and git(shared, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        git(shared, "branch", "-D", branch)
    task_file.unlink()
    print(f"[TASK] Abandoned {task_file.stem}: worktree, branch {branch or '-'} and board file removed. "
          "Its research and plan stay in docs/tasks/.")
    return 0
