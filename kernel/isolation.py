"""kernel/isolation.py — worktree·workboard 강제: 편집 전 가드와 본체로 합치기 전 검사.

Claude 래퍼(`.claude/hooks/check_pretool.py`)와 Codex 진입점이 둘 다 `kernel/hook.py --event
PreToolUse` 로 이 판정을 부른다. 페이로드 해석과 exit 코드와 출력 JSON 은 어댑터가 맡고, 이 모듈은
판정과 메시지 문구만 맡는다. 결과는 모두 `kernel.workspace.Finding` 형태다.

## 왜 강제하나 — 격리가 선택이면 아무도 안 한다

"단일 세션이면 메인 체크아웃에서 작업할 수 있다"가 정본이던 동안 실제로는 모든 세션이 메인에서
작업했고, 게이트는 작업 중인 트리에서 매 저장·매 턴 종료마다 차단을 반복했다. 백그라운드 워커가
코드를 쓰는 동안 메인 세션의 Stop 이 그 미완성 상태를 네 번 막았다(`dev/LESSONS.md` §25).
작업 공간(worktree)과 결과가 합쳐지는 본체를 나누면 그 마찰이 사라진다. 작업 중에는 막지 않고, 본체로 합칠 때 검사한다.

## 편집 전 가드 — 두 판정, 예외 셋

| 판정 | 어디 | 차단 조건 |
|---|---|---|
| 보드 등록 | 어디든 | 보드에 내 `#sid` 과업 파일이 없다 |
| 메인 체크아웃 | 공유 체크아웃 | 구현 파일을 메인에서 고친다 |

예외는 `workboard/**`·`docs/tasks/**`(등록·research·plan 은 메인에서 쓴다)와 **바뀐 줄 1줄 이하**다.
1줄 예외는 `CLAUDE.md` 4단계 워크플로우의 예외("오탈자·설정값 1줄")를 기계로 판정한 것이라 두 판정을 모두 면제한다.
그런 편집에는 plan 이 없고, plan 이 없으면 보드 행도 없는 것이 정상이다. 줄 수만 보고 파일 종류는
보지 않는다(사용자 지정 기준).

세션 식별자가 없거나 git 조회가 실패해 판정할 수 없으면 막지 않고 **경고만** 한다. 하네스가 오작동해
모든 편집이 막히면, 그 오작동을 고칠 편집까지 막혀 복구할 방법이 없어진다. 레포 밖(스크래치패드)과 다른 레포의 파일은 대상이 아니다.

## 나올 때 검사 — 본체로 합치는 명령 직전

`git push`·`gh pr create`·`gh pr merge`·`git merge` 를 실행하기 직전에 그 체크아웃에서
`kernel.runner --verify` 를 돌려 exit 0 이 아니면 막는다. `[TOOL]`·`[DECISION]` 도 통과가 아니다.
러너를 실행하지 못해도 **막는다**(fail-closed). 본체에 합친 것은 되돌리기 비싸기 때문이다. `git -C <경로>` 는 그 경로의
체크아웃을 검사한다. 명령은 명령줄을 나눈 각 조각의 맨 앞에서만 찾는다. `echo "git push"` 나 커밋 메시지 안의
문장은 명령이 아니다(`kernel/worktree.py` 도 같은 원칙을 따른다).
"""

from __future__ import annotations

import difflib
import shlex
import subprocess
from datetime import date
from pathlib import Path

from kernel.context import default_branch, runner_command
from kernel.workboard import board_dir
from kernel.workspace import Finding
from kernel.worktree import my_scope, segments

HOOK_NAME = "check_pretool"
EXEMPT_PREFIXES = ("workboard/", "docs/tasks/")
EXIT_COMMANDS = (("git", "push"), ("gh", "pr", "create"), ("gh", "pr", "merge"), ("git", "merge"))
MAX_FREE_LINES = 1                         # 오탈자·설정값 1줄 — 4단계 예외의 기계 판정
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch")
SHELL_TOOLS = ("Bash", "PowerShell")
VERIFY_TIMEOUT_SEC = 120
MAX_VERDICT_LINES = 30
PATCH_MARK = "*** Begin Patch"


def shared_root() -> Path:
    """공유 체크아웃 루트 = 보드의 부모. `kernel.workboard.board_dir` 가 git common dir 로 계산한다."""
    return board_dir().resolve().parent


def _git_roots(probe: Path) -> tuple[Path, Path] | None:
    """(체크아웃 루트, 공유 .git). git 실패면 None."""
    try:
        done = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel", "--git-common-dir"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except Exception:
        return None
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) < 2:
        return None
    top = Path(lines[0].strip()).resolve()
    common = Path(lines[1].strip())
    if not common.is_absolute():
        common = probe / common               # 메인 체크아웃에서는 `.git` 상대경로가 온다
    return top, common.resolve()


def checkout_of(path: Path) -> Path | None:
    """이 경로가 속한 체크아웃 루트. 아직 없는 파일은 가장 가까운 실존 상위 디렉토리로 묻는다."""
    found = _git_roots(_existing_dir(path))
    return found[0] if found else None


def _existing_dir(path: Path) -> Path:
    probe = path
    while not probe.is_dir() and probe.parent != probe:
        probe = probe.parent
    return probe


def _place(path: Path, shared: Path) -> tuple[str, Path | None]:
    """(자리, 체크아웃 루트). 자리는 `main`·`worktree`·`outside`·`unknown`(git 실패인데 공유 루트 아래)."""
    found = _git_roots(_existing_dir(path))
    if found is None:
        return ("unknown" if shared in path.resolve().parents else "outside"), None
    top, common = found
    if top == shared:
        return "main", top
    return ("worktree" if common.parent == shared else "outside"), top


def locate(path: Path, shared: Path | None = None) -> str:
    """경로의 자리 이름. 공유 루트를 안 주면 보드에서 계산한다."""
    return _place(path, shared_root() if shared is None else shared.resolve())[0]


def in_worktree(path: Path, shared: Path | None = None) -> bool:
    return locate(path, shared) == "worktree"


def is_edit(tool: str, tool_input: object) -> bool:
    """편집 툴인가 — 이름으로 가르고, 이름을 모르면 입력 모양(file_path·patch)으로 가른다."""
    if tool in EDIT_TOOLS:
        return True
    if tool in SHELL_TOOLS:
        return False
    if isinstance(tool_input, dict):
        return bool(tool_input.get("file_path")) or PATCH_MARK in str(tool_input.get("command", ""))
    return isinstance(tool_input, str) and PATCH_MARK in tool_input


def _diff_lines(old: str, new: str) -> int:
    """두 본문 사이에 바뀐 줄 수 — 한 줄 교체는 1, 3줄 문맥 속 1줄 교체도 1."""
    before, after = old.splitlines(), new.splitlines()
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


def _patch_lines(patch: str) -> int:
    """apply_patch 본문의 바뀐 줄 수 — 추가와 삭제 중 큰 쪽(한 줄 교체 = 1)."""
    body = [line for line in patch.splitlines() if not line.startswith("***")]
    added = sum(1 for line in body if line.startswith("+"))
    removed = sum(1 for line in body if line.startswith("-"))
    return max(added, removed)


def _occurrences(tool_input: dict, old: str) -> int:
    """`replace_all` 편집이 실제로 건드리는 자리 수. 파일을 못 읽으면 1."""
    if not tool_input.get("replace_all") or not old:
        return 1
    try:
        text = Path(str(tool_input.get("file_path"))).read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return 1
    return max(1, text.count(old))


def changed_lines(tool: str, tool_input: object) -> int:
    """이 편집이 바꾸는 줄 수. 1줄 예외의 유일한 근거다."""
    if isinstance(tool_input, str):
        return _patch_lines(tool_input) if PATCH_MARK in tool_input else 0
    if not isinstance(tool_input, dict):
        return 0
    command = str(tool_input.get("command", ""))
    if tool == "apply_patch" or PATCH_MARK in command:
        return _patch_lines(command)
    if tool == "Write":
        return len(str(tool_input.get("content", "")).splitlines())
    if tool == "NotebookEdit":
        return len(str(tool_input.get("new_source", "")).splitlines())
    if tool == "MultiEdit":
        edits = tool_input.get("edits")
        return sum(_diff_lines(str(e.get("old_string", "")), str(e.get("new_string", "")))
                   for e in edits if isinstance(e, dict)) if isinstance(edits, list) else 0
    old = str(tool_input.get("old_string", ""))
    return _diff_lines(old, str(tool_input.get("new_string", ""))) * _occurrences(tool_input, old)


def _exempt(path: Path, top: Path) -> bool:
    try:
        rel = path.resolve().relative_to(top).as_posix()
    except ValueError:
        return False
    return rel.startswith(EXEMPT_PREFIXES)


def _guarded(paths: list[Path], shared: Path) -> list[tuple[Path, str]]:
    """가드 대상 (경로, 자리). 레포 밖·다른 레포·예외 경로는 뺀다."""
    found: list[tuple[Path, str]] = []
    for path in paths:
        kind, top = _place(path, shared)
        if kind == "outside" or (top is not None and _exempt(path, top)):
            continue
        found.append((path, kind))
    return found


def _register_message(sid8: str) -> str:
    today = date.today().isoformat()
    return "\n".join([
        f"[ISOLATION] No task file for this session in workboard — register first (#sid:{sid8}).",
        "Create workboard/<area>-<target>.md in the main checkout. If a task file with the same scope exists, add a line to its items instead (join):",
        "  - 범위: <area>-<target>",  # ko-ok: shows the task-board format
        f"  - 과업: <feat|fix|chore>/<branch> #sid:{sid8}",  # ko-ok: shows the task-board format
        "  - 항목:",  # ko-ok: shows the task-board format
        "    - [ ] <todo>",
        "  - 손대는 곳:",  # ko-ok: shows the task-board format
        "    - <glob>",
        f"  - 시작: {today}",  # ko-ok: shows the task-board format
        "  - 상태: 진행",  # ko-ok: shows the task-board format
        "(Source of truth: workboard/README.md format)"])


def _worktree_message(paths: list[Path], lines: int, scope: str, sid8: str, shared: Path) -> str:
    names = " · ".join(_rel_or_name(path, shared) for path in paths)
    name = f"{scope}--{sid8}"
    base = default_branch() or "<default-branch>"
    return "\n".join([
        f"[ISOLATION] Editing in the main checkout — {names} ({lines} lines).",
        "Implement only inside a worktree. Exceptions: workboard/, docs/tasks/, and edits of 1 changed line or less.",
        f"  git worktree add worktrees/{name} -b <branch> origin/{base}",
        f"  Claude: EnterWorktree(path=\"worktrees/{name}\") · Codex: work in that directory",
        "(Source of truth: workboard/README.md work isolation)"])


def _rel_or_name(path: Path, shared: Path) -> str:
    try:
        return path.resolve().relative_to(shared).as_posix()
    except ValueError:
        return path.name


def edit_guard(paths: list[Path], sid8: str | None, lines: int,
               board: Path | None = None) -> Finding | None:
    """편집 전 판정. 보드 등록 여부를 먼저 보고 메인 체크아웃 편집 여부를 다음에 본다. 프로토콜상 등록이 먼저이기 때문이다."""
    board = board_dir() if board is None else board
    shared = board.resolve().parent
    if lines <= MAX_FREE_LINES:
        return None
    targets = _guarded(paths, shared)
    if not targets:
        return None
    if sid8 is None:
        return Finding(HOOK_NAME, "edit_guard", False,
                       "[ISOLATION] No session id — skipping the isolation guard. Check the hook.",
                       ("no sid",))
    if any(kind == "unknown" for _path, kind in targets):
        return Finding(HOOK_NAME, "edit_guard", False,
                       "[ISOLATION] git query failed, so the checkout is unknown — skipping the isolation guard.",
                       ("git query failed",))
    scope = my_scope(sid8, board)
    if scope is None:
        return Finding(HOOK_NAME, "edit_guard", True, _register_message(sid8), (f"not on task board {sid8}",))
    on_main = [path for path, kind in targets if kind == "main"]
    if not on_main:
        return None
    return Finding(HOOK_NAME, "edit_guard", True,
                   _worktree_message(on_main, lines, scope, sid8, shared),
                   tuple(f"main checkout edit {_rel_or_name(path, shared)}" for path in on_main))


def exit_command(command: str) -> tuple[str, Path | None] | None:
    """본체로 합치는 명령이면 (명령 이름, `git -C` 경로)를 돌려준다. 명령줄 각 조각의 맨 앞만 본다."""
    try:
        tokens = shlex.split(command.replace("\\", "/"), posix=True)
    except ValueError:
        return None
    for segment in segments(tokens):
        name = Path(segment[0]).name.lower().removesuffix(".exe")
        rest = segment[1:]
        target: Path | None = None
        if name == "git" and len(rest) >= 2 and rest[0] == "-C":
            target, rest = Path(rest[1]), rest[2:]
        words = (name, *rest[:2])
        for pattern in EXIT_COMMANDS:
            if words[:len(pattern)] == pattern:
                return " ".join(pattern), target
    return None


def _verdict_lines(stdout: str) -> list[str]:
    """러너 출력 중 사람이 봐야 할 줄. [FAIL]·[TOOL]·[DECISION] 머리줄과 그 아래 위반 항목만 남긴다."""
    kept: list[str] = []
    inside = False
    for line in stdout.splitlines():
        if line.startswith(("[FAIL]", "[TOOL]", "[DECISION]")):
            inside = True
        elif not line.startswith("   -"):
            inside = False
        if inside:
            kept.append(line)
    if len(kept) > MAX_VERDICT_LINES:
        kept = kept[:MAX_VERDICT_LINES] + [f"   … and {len(kept) - MAX_VERDICT_LINES} more lines"]
    return kept


def _blocked(name: str, reason: str, detail: list[str]) -> Finding:
    head = f"[EXIT GATE] check before `{name}` — {reason}"
    tail = "Do not merge until it passes. [TOOL] and [DECISION] are not a pass."
    return Finding(HOOK_NAME, "exit_gate", True, "\n".join([head, *detail, tail]), (f"{name} blocked: {reason}",))


def exit_gate(command: str, cwd: Path) -> Finding | None:
    """본체로 합치는 명령이면 그 체크아웃에서 `--verify` 를 돌린다. exit 0 이 아니거나 러너를 실행하지 못하면 막는다."""
    found = exit_command(command)
    if found is None:
        return None
    name, target = found
    root = checkout_of(cwd / target if target else cwd)
    if root is None:
        return _blocked(name, "git checkout not found (fail-closed).", [])
    command_line = runner_command(root, "--verify")
    if command_line is None:
        return None                           # 하네스가 연결되지 않은 체크아웃이다 — 검사할 러너도 프로파일도 없다
    argv, env = command_line
    try:
        done = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=VERIFY_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _blocked(name, f"runner could not start: {type(exc).__name__} (fail-closed).", [])
    if done.returncode == 0:
        return None
    reason = f"`python -X utf8 -m kernel.runner --verify` exited {done.returncode} in {root}."
    return _blocked(name, reason, _verdict_lines(done.stdout) or done.stderr.splitlines()[-5:])
