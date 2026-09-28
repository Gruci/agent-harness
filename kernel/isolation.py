"""kernel/isolation.py — worktree·workboard 강제: 편집 전 가드와 본체로 합치기 전 검사.

Claude 래퍼(`.claude/hooks/check_pretool.py`)와 Codex 진입점이 둘 다 `kernel/hook.py --event
PreToolUse` 로 이 판정을 부른다. 페이로드·exit·출력 JSON 은 어댑터 몫이고 여기는 판정과 문구다.
결과는 `kernel.workspace.Finding` 한 모양이다.

## 왜 강제하나 — 격리가 선택이면 아무도 안 한다

"단일 세션이면 메인 체크아웃에서 작업할 수 있다"가 정본이던 동안 실제로는 모든 세션이 메인에서
작업했고, 게이트는 작업 중인 트리에서 매 저장·매 턴 종료마다 차단을 반복했다. 백그라운드 워커가
코드를 쓰는 동안 메인 세션의 Stop 이 그 미완성 상태를 네 번 막았다(`dev/LESSONS.md` §25).
작업 공간과 합쳐지는 본체를 가르면 그 마찰이 사라진다 — 작업 중은 노터치, 나올 때 검사.

## 편집 전 가드 — 두 판정, 예외 셋

| 판정 | 어디 | 차단 조건 |
|---|---|---|
| 보드 등록 | 어디든 | 보드에 내 `#sid` 과업 파일이 없다 |
| 메인 체크아웃 | 공유 체크아웃 | 구현 파일을 메인에서 고친다 |

예외는 `workboard/**`·`docs/tasks/**`(등록·research·plan 은 메인에서 쓴다)와 **바뀐 줄 1줄 이하**다.
1줄 예외는 `CLAUDE.md` 4단계 예외("오탈자·설정값 1줄")의 기계 판정이라 두 판정을 다 면제한다 —
그 편집은 plan 이 없고 plan 이 없으면 보드 행도 없는 것이 정상이다. 줄 수만 보고 파일 종류는
보지 않는다(사용자 지정 기준).

판정 불능(세션 식별자 없음·git 조회 실패)은 **비차단 경고**다. 하네스 오작동으로 모든 편집이
막히면 복구 수단이 그 편집이라 잠긴다. 레포 밖(스크래치패드)과 다른 레포의 파일은 대상이 아니다.

## 나올 때 검사 — 본체로 합치는 명령 직전

`git push`·`gh pr create`·`gh pr merge`·`git merge` 를 실행하기 직전에 그 체크아웃에서
`kernel.runner --verify` 를 돌려 exit 0 이 아니면 막는다. `[TOOL]`·`[DECISION]` 도 통과가 아니다.
러너 실행 불능은 **차단**(fail-closed) — 합치는 것은 되돌리기 비싸다. `git -C <경로>` 는 그 경로의
체크아웃을 검사한다. 명령은 조각의 머리에서만 찾는다 — `echo "git push"` 와 커밋 메시지 안의
산문은 명령이 아니다(`kernel/worktree.py` 의 같은 원칙).
"""

from __future__ import annotations

import difflib
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path

from kernel.context import default_branch
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
        f"[ISOLATION] workboard 에 이 세션의 과업 파일이 없다 — 등록부터 한다 (#sid:{sid8}).",
        "workboard/<영역>-<대상>.md 를 공유 체크아웃에 만든다. 같은 범위가 있으면 합류한다:",
        "  - 범위: <영역>-<대상>",
        f"  - 과업: <feat|fix|chore>/<브랜치> #sid:{sid8}",
        "  - 항목:",
        "    - [ ] <할 일>",
        "  - 손대는 곳:",
        "    - <글로브>",
        f"  - 시작: {today}",
        "  - 상태: 진행",
        "(정본: workboard/README.md 서식)"])


def _worktree_message(paths: list[Path], lines: int, scope: str, sid8: str, shared: Path) -> str:
    names = " · ".join(_rel_or_name(path, shared) for path in paths)
    name = f"{scope}--{sid8}"
    base = default_branch() or "<기본브랜치>"
    return "\n".join([
        f"[ISOLATION] 메인 체크아웃에서 편집하려 한다 — {names} ({lines}줄).",
        "구현은 worktree 안에서만 한다. 예외는 workboard/·docs/tasks/ 와 바뀐 줄 1줄 이하다.",
        f"  git worktree add worktrees/{name} -b <브랜치> origin/{base}",
        f"  Claude: EnterWorktree(path=\"worktrees/{name}\") · Codex: 그 디렉토리에서 작업",
        "(정본: workboard/README.md 작업 격리)"])


def _rel_or_name(path: Path, shared: Path) -> str:
    try:
        return path.resolve().relative_to(shared).as_posix()
    except ValueError:
        return path.name


def edit_guard(paths: list[Path], sid8: str | None, lines: int,
               board: Path | None = None) -> Finding | None:
    """편집 전 판정. 보드 미등록 → 메인 체크아웃 순이다 — 등록이 프로토콜상 먼저다."""
    board = board_dir() if board is None else board
    shared = board.resolve().parent
    if lines <= MAX_FREE_LINES:
        return None
    targets = _guarded(paths, shared)
    if not targets:
        return None
    if sid8 is None:
        return Finding(HOOK_NAME, "edit_guard", False,
                       "[ISOLATION] 세션 식별자를 못 구했다 — 격리 가드를 건너뛴다. 훅을 점검하라.",
                       ("sid 없음",))
    if any(kind == "unknown" for _path, kind in targets):
        return Finding(HOOK_NAME, "edit_guard", False,
                       "[ISOLATION] git 조회 실패 — 체크아웃을 못 가려 격리 가드를 건너뛴다.",
                       ("git 조회 실패",))
    scope = my_scope(sid8, board)
    if scope is None:
        return Finding(HOOK_NAME, "edit_guard", True, _register_message(sid8), (f"보드 미등록 {sid8}",))
    on_main = [path for path, kind in targets if kind == "main"]
    if not on_main:
        return None
    return Finding(HOOK_NAME, "edit_guard", True,
                   _worktree_message(on_main, lines, scope, sid8, shared),
                   tuple(f"메인 편집 {_rel_or_name(path, shared)}" for path in on_main))


def exit_command(command: str) -> tuple[str, Path | None] | None:
    """합치는 명령이면 (명령 이름, `git -C` 경로). 조각의 머리에서만 본다."""
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
    """러너 출력 중 사람이 봐야 할 줄 — 등급 머리와 그 위반 항목만."""
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
        kept = kept[:MAX_VERDICT_LINES] + [f"   … 외 {len(kept) - MAX_VERDICT_LINES}줄"]
    return kept


def _blocked(name: str, reason: str, detail: list[str]) -> Finding:
    head = f"[EXIT GATE] `{name}` 전 검사 — {reason}"
    tail = "통과 전에는 본체로 합치지 않는다. [TOOL]·[DECISION] 도 통과가 아니다."
    return Finding(HOOK_NAME, "exit_gate", True, "\n".join([head, *detail, tail]), (f"{name} 차단: {reason}",))


def exit_gate(command: str, cwd: Path) -> Finding | None:
    """합치는 명령이면 그 체크아웃에서 `--verify`. exit 0 이 아니면 차단, 실행 불능도 차단."""
    found = exit_command(command)
    if found is None:
        return None
    name, target = found
    root = checkout_of(cwd / target if target else cwd)
    if root is None:
        return _blocked(name, "git 체크아웃을 못 찾았다(fail-closed).", [])
    if not (root / "kernel" / "runner.py").is_file():
        return None                           # 하네스가 깔린 체크아웃이 아니다 — 검사할 러너가 없다
    try:
        done = subprocess.run([sys.executable, "-X", "utf8", "-m", "kernel.runner", "--verify"], cwd=root,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=VERIFY_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _blocked(name, f"러너 실행 불능 {type(exc).__name__}(fail-closed).", [])
    if done.returncode == 0:
        return None
    reason = f"{root} 에서 `python -X utf8 -m kernel.runner --verify` 가 exit {done.returncode}."
    return _blocked(name, reason, _verdict_lines(done.stdout) or done.stderr.splitlines()[-5:])
