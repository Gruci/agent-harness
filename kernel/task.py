"""kernel/task.py — 과업 시작·인계와 명령줄. 끝내기는 `kernel/task_finish.py` 다.

판단 단계(범위 인터뷰·research·plan·승인)는 그대로 두고, 모델이 손으로 밟던 기계 단계만 명령으로 접는다.

| 명령 | 하는 일 | 닫는 결함 |
|---|---|---|
| `plan <범위> --sid <sid8> --branch <접두>/<이름>` | 리서치를 시작할 때 보드에 `상태: 계획` 으로 올린다. worktree 는 만들지 않는다 | 계획 중인 범위가 다른 세션에 안 보이던 것, 승인 대기 중 보드가 비어 남은 산출물 검사(⑰)가 막던 것 |
| `start <범위> --sid <sid8> --branch <접두>/<이름> --touch <글로브>… [--plan <plan> 또는 --small] [--on <브랜치>]` | 보드 파일을 쓰고 `--no-track` worktree 를 만든다. 내 `상태: 계획` 파일은 구현 단계 본문으로 올린다. 실패하면 보드 파일을 되돌린다. `--plan` 에 `## 사람용 요약`(또는 `## Human summary`)이 없으면 거절한다. `--small` 은 plan 없는 소규모 과업이고 finish 가 실제 diff 를 잰다 | 손으로 만든 이름을 훅이 사후에 막던 것, upstream 자동 등록으로 합친 뒤 `branch -d` 가 거부되던 것, 14칸 plan 을 사람에게 그대로 들이밀던 것, 작은 수정에도 research·plan 을 쓰던 것 |
| `finish --sid <sid8> [--scope <범위>]` | 보관 → 따라잡기 → 그 worktree 검사 → ff 합치기 → push → 정리. 몇 번을 다시 실행해도 된다 | 결함 E·F·G (`kernel/task_finish.py`) |
| `resume <범위> --sid <sid8>` | 보드의 `#sid` 를 새 값으로 바꾸고 `인계` 를 남긴다. worktree 가 없으면 브랜치에서 다시 만든다 | 결함 H — 새 session_id 로는 자기 과업도 못 고치던 것 |
| `abandon --sid <sid8> [--scope <범위>]` | 커밋 안 한 변경이 없을 때만 worktree·브랜치·보드 파일을 지운다(`kernel/task_abandon.py`) | 버린 과업을 손으로 치우다 남의 것까지 지우던 위험 |

세션 식별자는 `--sid` 로 받는다. session_id 는 훅 페이로드에만 오므로, 세션 시작 알림과 편집 가드 안내문이
그 값을 채운 명령을 그대로 보여 준다. 템플릿 체크아웃에서는 `python -X utf8 -m kernel.task <명령>` 으로 부른다 —
`python -m kernel` 진입점은 플러그인 전용이다.

같은 범위가 이미 열려 있으면 새로 만들지 않는다. 내 것이면 이어서 하고, `PR#n` 이면 그 브랜치 위에 쌓고, 남의 것이면
합류하거나 그 세션이 끝났을 때 인계받는다. 세션이 살아 있는지는 기계가 알 수 없다 — 판정은 사람과 모델이 한다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from kernel.context import default_branch
from kernel.isolation import SETUP_PREFIXES
from kernel.workboard import (BRANCH_PATTERN, add_list_item, board_dir, board_text, branch_of, field, list_field,
                              sid_of, task_files)
from kernel.worktree import worktree_of
from kernel.team_resources import TeamError

GIT_TIMEOUT_SEC = 60                       # fetch·push 가 느린 망에서도 끝나는 값
SCOPE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
TASK_DOCS = "docs/tasks/"
PLANNING = "계획"                          # ko-ok: task-board state value
# ko-ok: plan headings the approval shows the user (dev/workflows/feature-workflow.md) — English plans use the second
SUMMARY_HEADINGS = ("## 사람용 요약", "## Human summary")
SIZE_KEY, SMALL = "크기", "소규모"           # ko-ok: task-board key and value — finish measures a small task's real diff


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """git 한 번. 실패를 예외로 바꾸지 않는다 — 호출자가 returncode 로 가른다."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_SEC)


def fail(message: str, code: int) -> int:
    """`[TASK] <message>` 를 stderr 로 찍고 code 를 돌려준다. 명령 셋이 같이 쓴다."""
    print(f"[TASK] {message}", file=sys.stderr)
    return code


def plan(scope: str, sid8: str, branch: str) -> int:
    from kernel.task_lock import task_lock

    with task_lock(board_dir().parent, "scope:" + scope):
        return _plan(scope, sid8, branch)


def _plan(scope: str, sid8: str, branch: str) -> int:
    """리서치를 시작할 때 보드에 올린다. 승인 대기 중에도 보드에 과업이 있어 다른 세션이 같은 범위를 잡지 않고 ⑰ 이 막지 않는다."""
    board = board_dir()
    if not SCOPE_NAME.fullmatch(scope) or not BRANCH_PATTERN.fullmatch(branch):
        return fail(f"need a scope like <area>-<target> and a branch like feat/<name> — got {scope} {branch}", 2)
    task_file = board / f"{scope}.md"
    if task_file.exists():
        return _already_open(task_file, sid8)
    artifacts = (f"{TASK_DOCS}research_{scope}.md", f"{TASK_DOCS}plan_{scope}.md")
    board.mkdir(exist_ok=True)
    task_file.write_text(board_text(scope, branch, sid8, (), artifacts, date.today().isoformat(), state=PLANNING),
                         encoding="utf-8")
    print(f"[TASK] Planning {scope} (#sid:{sid8}). Board: workboard/{scope}.md — write {' and '.join(artifacts)}.")
    print("Registration is not permission to implement: edits outside workboard/ and docs/tasks/ still need a worktree.")
    print(f"After approval: python -X utf8 -m kernel.task start {scope} --sid {sid8} --branch {branch} "
          f"--touch <glob> --plan {artifacts[1]}")
    return 0


def start(scope: str, sid8: str, branch: str, touch: list[str], plan: str | None, on: str | None,
          small: bool = False, goal: str = "", depends_on: list[str] | None = None) -> int:
    from kernel.task_lock import task_lock

    with task_lock(board_dir().parent, "scope:" + scope):
        return _start(scope, sid8, branch, touch, plan, on, small, goal, depends_on)


def _start(scope: str, sid8: str, branch: str, touch: list[str], plan: str | None, on: str | None,
           small: bool, goal: str, depends_on: list[str] | None) -> int:
    board = board_dir()
    shared = board.parent
    if not SCOPE_NAME.fullmatch(scope) or not BRANCH_PATTERN.fullmatch(branch) or not touch:
        return fail(f"need --touch, a scope like <area>-<target> and a branch like feat/<name> — got {scope} {branch}", 2)
    task_file = board / f"{scope}.md"
    previous = task_file.read_text(encoding="utf-8") if task_file.exists() else None
    if previous is not None and not (sid_of(previous) == sid8 and field(previous, "상태") == PLANNING):  # ko-ok: task-board key
        return _already_open(task_file, sid8)
    setup = _uncommitted_setup(shared)
    if setup:
        return fail("setup changes are not committed, so the new work copy would miss them — commit them first:\n"
                    f"  git add {' '.join(setup)} && git commit -m \"chore: harness setup\"", 2)
    artifacts = _artifacts(shared, plan)
    base = on or _start_point(shared)
    if base is None or artifacts is None:
        return fail("no start point (connect origin or check out the default branch) or the plan file is missing", 2)
    if small and plan is not None:
        return fail("--small is for a task without a plan — pass --plan or --small, not both", 2)
    text = (shared / plan).read_text(encoding="utf-8") if plan is not None else ""
    if plan is not None and not any(heading in text for heading in SUMMARY_HEADINGS):
        return fail(f"{plan} has no `{SUMMARY_HEADINGS[0]}` or `{SUMMARY_HEADINGS[1]}` heading — add four plain-language lines before starting: "
                    "what the user gets, what changes, the risk and how to undo it, what is deferred on purpose "
                    "(dev/workflows/feature-workflow.md). The approval request shows that summary, not the whole plan.", 2)
    from kernel import team_tasks

    team_tasks.claim(shared, scope, sid8, branch, touch, base, goal, depends_on)
    board.mkdir(exist_ok=True)
    body = board_text(scope, branch, sid8, tuple(touch), artifacts, date.today().isoformat())
    if small:
        body = body.replace("- 시작:", f"- {SIZE_KEY}: {SMALL}\n- 시작:", 1)  # ko-ok: task-board key
    task_file.write_text(body, encoding="utf-8")
    name = f"worktrees/{scope}--{sid8}"
    added = git(shared, "worktree", "add", "--no-track", "-b", branch, name, base)
    if added.returncode:
        _restore(task_file, previous)         # 보드만 남으면 worktree 없는 과업이 된다 — 등록이나 계획 단계 본문을 되돌린다
        team_tasks.release(shared, scope)
        return fail(f"git worktree add failed — {added.stderr.strip()[:300]}", 2)
    print(f"[TASK] Started {scope} on {branch} from {base}. Board: workboard/{scope}.md")
    print(f'Next — Claude: EnterWorktree(path="{name}") · Codex: work in {name}')
    print(f"Finish with: python -X utf8 -m kernel.task finish --sid {sid8}")
    return 0


def _restore(task_file: Path, previous: str | None) -> None:
    """start 가 쓰기 전 상태로. 새 파일이었으면 지우고, 계획 단계 파일이었으면 그 본문을 되돌린다."""
    if previous is None:
        task_file.unlink()
    else:
        task_file.write_text(previous, encoding="utf-8")


def _start_point(shared: Path) -> str | None:
    """새 브랜치를 딸 곳. origin 이 있으면 받아 온 `origin/<기본>`, 없으면 본체의 현재 브랜치다.
    본체가 origin 을 품고 앞서 있으면(설정 커밋처럼 아직 push 안 한 것) 본체에서 딴다 — origin 에서 따면 그 커밋이 빠진다."""
    current = git(shared, "rev-parse", "--abbrev-ref", "HEAD")
    local = (current.stdout.strip() or None) if current.returncode == 0 else None
    base = default_branch()
    if base:
        git(shared, "fetch", "--quiet", "origin", base)   # 오프라인이면 마지막으로 받은 ref 에서 딴다
        remote = f"origin/{base}"
        if local and git(shared, "merge-base", "--is-ancestor", remote, "HEAD").returncode == 0:
            return local
        return remote
    return local


def _uncommitted_setup(shared: Path) -> list[str]:
    """본체에서 고치고 커밋하지 않은 설정 파일. 그대로 worktree 를 따면 새 작업 사본에 설정이 빠진다."""
    status = git(shared, "status", "--porcelain", "--", *SETUP_PREFIXES).stdout
    return [line[3:].strip() for line in status.splitlines() if line.strip()]


def _artifacts(shared: Path, plan: str | None) -> tuple[str, ...] | None:
    """`--plan` 과 그 짝 research (`research_<과업>`·`wip_research_<과업>` 중 있는 것). plan 이 없으면 None."""
    if plan is None:
        return ()
    rel = Path(plan).as_posix()
    if not rel.startswith(TASK_DOCS) or not (shared / rel).is_file():
        return None
    stem = Path(rel).name.removeprefix("wip_").removeprefix("plan_")
    pair = [f"{TASK_DOCS}research_{stem}", f"{TASK_DOCS}wip_research_{stem}"]
    return (rel, *(candidate for candidate in pair if (shared / candidate).is_file()))


def _already_open(task_file: Path, sid8: str) -> int:
    """같은 범위가 이미 있을 때 — 내 것이면 이어서, `PR#n` 이면 쌓기, 남의 것이면 합류나 인계를 안내한다."""
    text = task_file.read_text(encoding="utf-8")
    scope, owner, state = task_file.stem, sid_of(text), field(text, "상태")  # ko-ok: task-board key
    if owner == sid8:
        print(f"[TASK] {scope} is already yours (#sid:{sid8}) — continue in its worktree.")
        return 0
    branch = branch_of(" | ".join(text.split())) or "<branch>"
    if state.startswith("PR#"):
        return fail(f"{scope} is out as {state} — stack a new scope on its branch:\n"
                    f"  python -X utf8 -m kernel.task start <new-scope> --sid {sid8} --branch <type>/<name> "
                    f"--touch <glob> --on {branch}", 1)
    stage = "being planned" if state == PLANNING else "open"
    return fail(f"{scope} is {stage} under #sid:{owner}. Join it (add your item to workboard/{scope}.md and leave "
                f"the work to that session) or, only if that session has ended, take it over:\n"
                f"  python -X utf8 -m kernel.task resume {scope} --sid {sid8}", 1)


def resume(scope: str, sid8: str) -> int:
    from kernel.task_lock import task_lock

    with task_lock(board_dir().parent, "scope:" + scope):
        return _resume(scope, sid8)


def _resume(scope: str, sid8: str) -> int:
    """다른 세션이 남긴 과업을 이 세션이 넘겨받는다. 그 세션이 끝났을 때만 쓴다 — 판정은 사람과 모델이 한다."""
    board = board_dir()
    shared = board.parent
    task_file = board / f"{scope}.md"
    if not task_file.is_file():
        opened = ", ".join(path.stem for path, _text in task_files(board)) or "none"
        return fail(f"no task file workboard/{scope}.md — open tasks: {opened}", 1)
    text = task_file.read_text(encoding="utf-8")
    from kernel import profile, team_tasks

    if profile.TEAM:
        current = team_tasks.refresh(shared, scope)
        if current["state"] == "active":
            team_tasks.operation(shared, scope, "renew")
    old = sid_of(text)
    if old != sid8:
        text = text.replace(f"#sid:{old}", f"#sid:{sid8}", 1) if old else text
        text = add_list_item(text, "인계", f"{old or '?'} → {sid8} {date.today().isoformat()}")  # ko-ok: task-board key
        task_file.write_text(text, encoding="utf-8")
    branch = branch_of(" | ".join(text.split())) or ""
    tree = worktree_of(branch) or _recreate(shared, scope, sid8, branch)
    print(f"[TASK] {scope} is now #sid:{sid8} (was {old}). Only take over a task whose session has ended.")
    if tree is not None:
        print(f'Next — Claude: EnterWorktree(path="{tree.resolve().relative_to(shared.resolve()).as_posix()}") · Codex: work there')
    for rel in list_field(text, "산출물"):  # ko-ok: task-board key
        print(f"  read first: {rel}")
    return 0


def _recreate(shared: Path, scope: str, sid8: str, branch: str) -> Path | None:
    """브랜치가 로컬에 있고 worktree 가 없을 때만 `worktrees/<범위>--<sid8>` 를 그 브랜치로 다시 만든다."""
    if not branch or git(shared, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode:
        print(f"[TASK] branch {branch or '?'} does not exist locally — nothing to recreate. "
              "If the task is abandoned, delete its board file.")
        return None
    name = f"worktrees/{scope}--{sid8}"
    added = git(shared, "worktree", "add", name, branch)
    if added.returncode:
        print(f"[TASK] git worktree add failed — {added.stderr.strip()[:300]}")
        return None
    print(f"[TASK] Recreated {name} on {branch}.")
    return shared / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -X utf8 -m kernel.task", description="Task lifecycle: plan, start, finish, resume, abandon.")
    commands = parser.add_subparsers(dest="command", required=True)
    reader = commands.add_parser("status", help="read shared tasks and the last landed task; never takes ownership")
    reader.add_argument("--sid", default="", help="show this session's tasks first")
    planner = commands.add_parser("plan", help="put a planning-stage task on the board (no worktree) when research starts")
    planner.add_argument("scope")
    planner.add_argument("--sid", required=True, help="session id (first 8 characters are used)")
    planner.add_argument("--branch", required=True)
    starter = commands.add_parser("start", help="write the board file and create a --no-track worktree")
    starter.add_argument("scope")
    starter.add_argument("--sid", required=True, help="session id (first 8 characters are used)")
    starter.add_argument("--branch", required=True)
    starter.add_argument("--touch", nargs="+", required=True, metavar="GLOB")
    starter.add_argument("--plan", help="docs/tasks/plan_<task>.md — archived by finish with its research")
    starter.add_argument("--on", help="branch to stack on instead of the default branch")
    starter.add_argument("--small", action="store_true",
                         help="no plan: existing files only, small diff — finish measures it and refuses if it grew")
    starter.add_argument("--goal", default="", help="shared goal identifier for related independent tasks")
    starter.add_argument("--depends-on", nargs="*", default=[], metavar="TASK_ID")
    finisher = commands.add_parser("finish", help="archive, verify the worktree, merge, push, clean up")
    finisher.add_argument("--sid", required=True)
    finisher.add_argument("--scope")
    resumer = commands.add_parser("resume", help="take over an open task whose session has ended")
    resumer.add_argument("scope")
    resumer.add_argument("--sid", required=True)
    dropper = commands.add_parser("abandon", help="drop your task: worktree, branch and board file (refuses unsaved work)")
    dropper.add_argument("--sid", required=True)
    dropper.add_argument("--scope")
    dropper.add_argument("--discard-commits", action="store_true", help="also drop commits that were never merged")
    args = parser.parse_args(argv)
    if args.command == "status":
        from kernel.context import ROOT
        from kernel.task_status import status

        code, text = status(ROOT, args.sid)
        print(text)
        return code
    sid8 = args.sid[:8]
    if args.command == "plan":
        return plan(args.scope, sid8, args.branch)
    if args.command == "start":
        return start(args.scope, sid8, args.branch, args.touch, args.plan, args.on, args.small, args.goal, args.depends_on)
    if args.command == "resume":
        return resume(args.scope, sid8)
    if args.command == "abandon":
        from kernel.task_abandon import abandon
        return abandon(sid8, args.scope, args.discard_commits)
    from kernel.task_finish import finish
    return finish(sid8, args.scope)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (TeamError, ValueError, OSError, TimeoutError) as exc:
        sys.exit(fail(str(exc), 2))
