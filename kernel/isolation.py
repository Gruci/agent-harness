"""kernel/isolation.py — worktree·workboard 강제: 편집 전 가드.

Claude 래퍼(`.claude/hooks/check_pretool.py`)와 Codex 진입점이 둘 다 `kernel/hook.py --event
PreToolUse` 로 이 판정을 부른다. 페이로드 해석과 exit 코드와 출력 JSON 은 어댑터가 맡고, 이 모듈은
판정과 메시지 문구만 맡는다. 결과는 모두 `kernel.workspace.Finding` 형태다. 본체로 합치기 전 검사는
`kernel/exit_gate.py` 다.

## 왜 강제하나 — 격리가 선택이면 아무도 안 한다

"단일 세션이면 메인 체크아웃에서 작업할 수 있다"가 정본이던 동안 실제로는 모든 세션이 메인에서
작업했고, 게이트는 작업 중인 트리에서 매 저장·매 턴 종료마다 차단을 반복했다. 백그라운드 워커가
코드를 쓰는 동안 메인 세션의 Stop 이 그 미완성 상태를 네 번 막았다(`dev/LESSONS.md` §25).
작업 공간(worktree)과 결과가 합쳐지는 본체를 나누면 그 마찰이 사라진다. 작업 중에는 막지 않고, 본체로 합칠 때 검사한다.

## 편집 전 가드 — 세 판정, 예외 셋

| 판정 | 어디 | 차단 조건 |
|---|---|---|
| worktree 주인 | `worktrees/<범위>--*` 안 | 그 범위 보드 파일의 `#sid` 가 내 sid 가 아니다 — 인계(`kernel.task resume`) 명령을 보인다 |
| 보드 등록 | 어디든 | 보드에 내 `#sid` 과업 파일이 없다 |
| 메인 체크아웃 | 공유 체크아웃 | 구현 파일을 메인에서 고친다 |

예외는 `workboard/**`·`docs/tasks/**`·`docs/mockup/**`(등록·research·plan·시안은 메인에서 쓴다)와 **바뀐 줄 1줄 이하**다.
설정 단계 — 그래프에 컴포넌트가 하나도 없는 동안 — 에는 설정 파일(`SETUP_PREFIXES`)도 예외다. 온보딩이 프로파일과
`PROJECT.md` 를 고쳐야 하는데, 그것까지 과업과 worktree 를 요구하면 원격이 없는 첫날에 설정이 worktree 에 갇혔다.
첫 컴포넌트가 승인되면 저절로 끝난다.
1줄 예외는 `CLAUDE.md` 4단계 워크플로우의 예외("오탈자·설정값 1줄")를 기계로 판정한 것이라 보드 등록과 메인 체크아웃
판정을 면제한다. 그런 편집에는 plan 이 없고, plan 이 없으면 보드 행도 없는 것이 정상이다. **worktree 주인 판정은
면제하지 않는다** — 남의 과업 worktree 는 1줄이어도 막는다. worktree 편집에는 본체 누적이 0이라, 예외를 먼저 돌리면
남의 worktree 를 1줄씩 고치는 편집이 매번 통과했다. 줄 수만 보고 파일 종류는
보지 않는다(사용자 지정 기준). **본체에서는 그 1줄이 본체 전체에 한 번이다** — 이번 편집의 줄 수에 본체에
이미 쌓인 커밋 안 된 구현 변경 줄 수를 더한다. 편집마다 1줄이면 쉰 번 나눠 격리를 통째로 우회할 수 있었다.

세션 식별자가 없거나 git 조회가 실패해 판정할 수 없으면 막지 않고 **경고만** 한다. 하네스가 오작동해
모든 편집이 막히면, 그 오작동을 고칠 편집까지 막혀 복구할 방법이 없어진다. 레포 밖(스크래치패드)과 다른 레포의 파일은 대상이 아니다.

worktree 접미(`--<sid8>`)는 만든 세션이고 보드의 `#sid` 는 지금 주인이다. 판정 키는 보드다 — 접미로 판정하면
인계받은 세션이 자기 worktree 를 못 고친다(결함 H).
"""

from __future__ import annotations

import difflib
import subprocess
from datetime import date
from pathlib import Path

from kernel import component_graph
from kernel.context import git_dirs
from kernel.workboard import board_dir, board_text, sid_of
from kernel.workspace import Finding
from kernel.worktree import my_scope

HOOK_NAME = "check_pretool"
EXEMPT_PREFIXES = ("workboard/", "docs/tasks/", "docs/mockup/")
# 설정 단계(컴포넌트 0개) 동안만 예외 — 온보딩이 고치는 파일들
SETUP_PREFIXES = ("harness_profile.py", "PROJECT.md", "profiles/", "docs/architecture/", ".github/workflows/")
MAX_FREE_LINES = 1                         # 오탈자·설정값 1줄 — 4단계 예외의 기계 판정. 본체 전체에 한 번이다
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch")
SHELL_TOOLS = ("Bash", "PowerShell")
PATCH_MARK = "*** Begin Patch"
# 훅이 다시 쓰는 생성 파일 — 1줄 예외의 누적에도, finish 의 더러움 판정에도 세지 않는다. 지도 둘은 `GENERATED_MAPS` 다.
GENERATED = ("harness_trace.jsonl", "docs/architecture/feature-map.json", "docs/architecture/feature-map.md")
GENERATED_MAPS = GENERATED[1:]


def shared_root() -> Path:
    """공유 체크아웃 루트 = 보드의 부모. `kernel.workboard.board_dir` 가 git common dir 로 계산한다."""
    return board_dir().resolve().parent


def checkout_of(path: Path) -> Path | None:
    """이 경로가 속한 체크아웃 루트. 아직 없는 파일은 가장 가까운 실존 상위 디렉토리로 묻는다."""
    found = git_dirs(path)
    return found[0] if found else None


def _place(path: Path, shared: Path) -> tuple[str, Path | None]:
    """(자리, 체크아웃 루트). 자리는 `main`·`worktree`·`outside`·`unknown`(git 실패인데 공유 루트 아래)."""
    found = git_dirs(path)
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


def exempt_prefixes(shared: Path) -> tuple[str, ...]:
    """편집 가드 예외 경로. 설정 단계(그래프에 컴포넌트 0개)에는 설정 파일이 더해진다."""
    return EXEMPT_PREFIXES + (() if component_graph.has_components(shared) else SETUP_PREFIXES)


def main_pending_lines(shared: Path) -> int:
    """본체에 이미 쌓인, 커밋 안 된 구현 변경 줄 수. 1줄 예외는 본체 전체에 한 번이다."""
    try:
        diff = subprocess.run(["git", "-C", str(shared), "diff", "--numstat", "-z", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    exempt = exempt_prefixes(shared)
    total = 0
    for record in diff.stdout.split("\0"):
        added, _tab, rest = record.partition("\t")
        deleted, _tab, rel = rest.partition("\t")
        if added.isdigit() and deleted.isdigit() and not rel.startswith(exempt) and rel not in GENERATED:
            total += max(int(added), int(deleted))
    return total


def _exempt(path: Path, top: Path, prefixes: tuple[str, ...]) -> bool:
    try:
        rel = path.resolve().relative_to(top).as_posix()
    except ValueError:
        return False
    return rel.startswith(prefixes)


def _guarded(paths: list[Path], shared: Path) -> list[tuple[Path, str]]:
    """가드 대상 (경로, 자리). 레포 밖·다른 레포·예외 경로는 뺀다."""
    prefixes = exempt_prefixes(shared)
    found: list[tuple[Path, str]] = []
    for path in paths:
        kind, top = _place(path, shared)
        if kind == "outside" or (top is not None and _exempt(path, top, prefixes)):
            continue
        found.append((path, kind))
    return found


def _worktree_owner(path: Path, shared: Path, board: Path) -> tuple[str, str] | None:
    """편집 대상이 든 worktree 의 과업 (범위, 주인 sid). 규약 밖 worktree 이거나 보드 파일이 없으면 None."""
    try:
        name = path.resolve().relative_to(shared / "worktrees").parts[0]
    except (ValueError, IndexError):
        return None
    task_file = board / f"{name.rsplit('--', 1)[0]}.md"
    owner = sid_of(task_file.read_text(encoding="utf-8")) if task_file.is_file() else None
    return (task_file.stem, owner) if owner else None


def _register_message(sid8: str) -> str:
    sample = board_text("<area>-<target>", "<feat|fix|chore>/<branch>", sid8, ("<glob>",), (), date.today().isoformat())
    return "\n".join([
        f"[ISOLATION] No task file for this session in workboard — register first (#sid:{sid8}).",
        "From the main checkout, one command writes the task file and the worktree:",
        f"  python -X utf8 -m kernel.task start <area>-<target> --sid {sid8} --branch <feat|fix|chore>/<name> "
        "--touch <glob> [--plan docs/tasks/plan_<task>.md]",
        "If a task file with the same scope exists, add a line to its items instead (join). The file it writes:",
        *(f"  {line}" for line in sample.splitlines()),
        "(Source of truth: workboard/README.md format)"])


def _resume_message(scope: str, owner: str, sid8: str) -> str:
    return "\n".join([
        f"[ISOLATION] This worktree belongs to task {scope} (#sid:{owner}), not this session (#sid:{sid8}).",
        "If that session has ended, take the task over — it rewrites the board #sid and keeps the worktree:",
        f"  python -X utf8 -m kernel.task resume {scope} --sid {sid8}",
        "If it is still running, leave this worktree alone and add your item to that task file (join).",
        "(Source of truth: workboard/README.md handoff)"])


def _worktree_message(paths: list[Path], lines: int, pending: int, scope: str, sid8: str, shared: Path) -> str:
    names = " · ".join(_rel_or_name(path, shared) for path in paths)
    name = f"{scope}--{sid8}"
    counted = f"{lines} lines" if not pending else f"{lines} lines, {pending} uncommitted lines already in the main checkout"
    return "\n".join([
        f"[ISOLATION] Editing in the main checkout — {names} ({counted}).",
        "Implement only inside a worktree. Exceptions: workboard/, docs/tasks/, docs/mockup/, one changed line in the whole "
        "main checkout, and setup files (profile, PROJECT.md) until the first component is approved.",
        f"  python -X utf8 -m kernel.task start {scope} --sid {sid8} --branch <branch> --touch <glob>   (if worktrees/{name} is missing)",
        f"  Claude: EnterWorktree(path=\"worktrees/{name}\") · Codex: work in that directory",
        "(Source of truth: workboard/README.md work isolation)"])


def _rel_or_name(path: Path, shared: Path) -> str:
    try:
        return path.resolve().relative_to(shared).as_posix()
    except ValueError:
        return path.name


def edit_guard(paths: list[Path], sid8: str | None, lines: int,
               board: Path | None = None) -> Finding | None:
    """편집 전 판정. worktree 주인 → 보드 등록 → 메인 체크아웃 편집 순이다. 프로토콜상 등록이 먼저이기 때문이다."""
    board = board_dir() if board is None else board
    shared = board.resolve().parent
    targets = _guarded(paths, shared)
    if not targets:
        return None
    if sid8 is not None:                  # 주인 판정은 1줄 예외보다 먼저다 — 남의 worktree 는 1줄이어도 막는다
        for path, kind in targets:
            owner = _worktree_owner(path, shared, board) if kind == "worktree" else None
            if owner is not None and owner[1] != sid8:
                return Finding(HOOK_NAME, "edit_guard", True, _resume_message(owner[0], owner[1], sid8),
                               (f"edit in task {owner[0]} owned by {owner[1]}",))
    on_main = [path for path, kind in targets if kind == "main"]
    pending = main_pending_lines(shared) if on_main else 0
    if lines + pending <= MAX_FREE_LINES:
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
    if not on_main:
        return None
    return Finding(HOOK_NAME, "edit_guard", True,
                   _worktree_message(on_main, lines, pending, scope, sid8, shared),
                   tuple(f"main checkout edit {_rel_or_name(path, shared)}" for path in on_main))
