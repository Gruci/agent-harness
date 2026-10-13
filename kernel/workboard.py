"""과업 보드(`workboard/`)의 데이터 계층. Claude 와 Codex 가 같은 판정을 쓰도록 판정 코드를 여기 한 곳에 둔다.

보드는 레포 루트의 `workboard/` 다. git 은 README.md 만 추적하고 과업 파일은 gitignore 한다.
`.claude/` 밑에 두지 않은 이유는 어느 한 에이전트 전용이 아니어야 해서다. Claude 훅과 Codex 진입점(`kernel/hook.py`)이
같은 보드를 읽어야 하는데, 한쪽 전용 폴더 밑에 두면 다른 쪽이 남의 전용 폴더를 드나들게 된다.

판정을 훅마다 다시 구현하지 않는다. 범위 겹침 검사가 Claude 쪽에만 있으면 Codex 세션이 남의 과업을
모르고 덮어쓴다(중복 구현 자체는 선언 본문 중복 검사 34 도 막는다). 머지 여부 추론(`is_merged`·`is_dead`)은 Claude
Stop 훅 전용이라 여기 두지 않는다. Codex 쪽 연결에는 그 판정 결과를 전달할 경고 채널이 정해져 있지 않다.

함수가 보드 경로를 인자로 받는 이유는 테스트 계약이다 — 훅이 자기 `BOARD_DIR` 전역을 쥐고
몽키패치로 갈아끼운다.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from kernel.context import ROOT, git_common_dir

BRANCH_PATTERN = re.compile(r"\b((?:feat|fix|perf|chore|docs|refactor)/[A-Za-z0-9._/-]+)")
SID_TAG = re.compile(r"#sid:([0-9A-Za-z]{8})")


def board_dir() -> Path:
    """공유 체크아웃의 `workboard/` 경로. git 조회가 실패하면 현재 체크아웃의 `workboard/` 로 대신한다.

    이 파일은 worktree 마다 복제되므로 `ROOT / "workboard"` 로 잡으면 보드가 세션 수만큼
    따로 생긴다. 그러면 보드를 git 밖으로 꺼낸 이유, 즉 같은 머신의 파일시스템을 공유 채널로 쓴다는
    전제가 무너진다. 공유 `.git`(`kernel.context.git_common_dir`)은 worktree 안에서도 **메인 `.git`** 이고,
    그 부모가 공유 체크아웃 루트다.

    이렇게 대신해도 안전한 이유: 보드를 못 찾으면 '열린 과업 없음'으로 읽혀 남은 과업 검사가 돌고
    범위 겹침 경고가 안 뜬다. 둘 다 경고나 통과로 끝나 세션을 막지 않는다.
    """
    common = git_common_dir(ROOT)
    return ROOT / "workboard" if common is None else common.parent / "workboard"


def task_files(board: Path) -> list[tuple[Path, str]]:
    """(과업 파일, 본문) 목록을 이름순으로 돌려준다. 보드 파일을 순회하는 곳은 전부 이 함수를 쓴다."""
    if not board.is_dir():
        return []
    found: list[tuple[Path, str]] = []
    for path in sorted(board.glob("*.md")):
        if path.name == "README.md":
            continue                      # 서식 설명이지 과업이 아니다
        try:
            found.append((path, path.read_text(encoding="utf-8")))
        except OSError:
            continue                      # 읽기 실패한 한 파일이 판정 전체를 죽이지 않는다
    return found


def active_rows(board: Path) -> list[str]:
    """진행 중인 과업 행 목록. **파일 하나가 한 행**이다(`workboard/<수정범위>.md`).

    파일 하나를 한 줄로 이어 붙이는 이유는 호출하는 쪽이 `#sid:` 포함 여부와 `branch_of()`
    만 쓰기 때문이다. 줄바꿈을 살릴 이유가 없고, 살리면 행 개수가 파일 수와 어긋난다.
    """
    return [" | ".join(text.split()) for _, text in task_files(board)]


def branch_of(row: str) -> str | None:
    """행에서 브랜치명을 찾는다. `과업:` 뒤를 먼저 보고, 없으면 행 전체에서 찾는다.

    ⚠️ 행 전체만 검색하면 `손대는 곳` 의 경로를 브랜치로 잘못 읽는다. `docs/tasks/*` 는 브랜치
    접두(`docs/`)와 모양이 같다. 예전 표 서식에서 '첫 칸만' 보던 것과 같은 방어이고, 기준만
    칸 위치에서 필드 이름으로 바꿨다(파일 서식에는 칸이 없다).
    """
    after = row.split("과업:", 1)  # ko-ok: task-board file key is Korean
    found = BRANCH_PATTERN.search(after[1] if len(after) > 1 else row)
    return found.group(1) if found else None


def field(text: str, name: str) -> str:
    """과업 파일의 `- <이름>: <값>` 한 줄. 없으면 빈 문자열."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {name}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def list_field(text: str, name: str) -> list[str]:
    """`- <이름>:` 아래 두 칸 들여쓴 `- <값>` 들. 들여쓰기 없는 다음 필드를 만나면 끝난다."""
    found: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {name}:"):
            collecting = True
        elif collecting and line.startswith("  - "):
            found.append(stripped[2:].strip())
        elif collecting and stripped.startswith("- "):
            break
    return found


def touch_globs(text: str) -> list[str]:
    """`손대는 곳:` 아래의 글로브 목록. 다음 필드(`- 이름:`)를 만나면 끝난다."""
    return list_field(text, "손대는 곳")  # ko-ok: task-board file key is Korean


def sid_of(text: str) -> str | None:
    """과업 파일의 지금 주인 — `#sid:` 태그 값. 없으면 None."""
    found = SID_TAG.search(text)
    return found.group(1) if found else None


def board_text(scope: str, branch: str, sid8: str, touch: tuple[str, ...],
               artifacts: tuple[str, ...], start: str, state: str = "진행") -> str:  # ko-ok: task-board state value
    """과업 파일 본문. 서식 정본은 `workboard/README.md` 「서식」이고, 등록 안내문과 `kernel.task plan`·`start` 가 같이 쓴다."""
    lines = [f"- 범위: {scope}", f"- 과업: {branch} #sid:{sid8}", "- 항목:",  # ko-ok: task-board format
             f"  - [ ] {artifacts[0] if artifacts else branch}", "- 손대는 곳:",  # ko-ok: task-board format
             *(f"  - {glob}" for glob in touch)]
    if artifacts:
        lines += ["- 산출물:", *(f"  - {path}" for path in artifacts)]  # ko-ok: task-board format
    return "\n".join([*lines, f"- 시작: {start}", f"- 상태: {state}"]) + "\n"  # ko-ok: task-board format


def add_list_item(text: str, name: str, value: str) -> str:
    """`- <이름>:` 목록 끝에 `  - <값>` 을 더한다. 필드가 없으면 `- 시작:` 앞에 필드째 넣는다. `resume` 의 `인계` 기록이 쓴다."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"- {name}:"):
            end = index + 1
            while end < len(lines) and lines[end].startswith("  - "):
                end += 1
            lines.insert(end, f"  - {value}")
            return "\n".join(lines) + "\n"
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("- 시작:")), len(lines))  # ko-ok: task-board key
    lines[start:start] = [f"- {name}:", f"  - {value}"]
    return "\n".join(lines) + "\n"


def overlaps(target: Path, sid8: str, board: Path, root: Path) -> list[str]:
    """편집 대상이 남의 과업 글로브에 걸리는지 본다. 걸리면 `범위 (글로브)` 목록을 돌려준다.

    ⚠️ `root` 는 **호출자의 worktree 루트**다(보드 위치와 다르다). 편집 대상을 상대경로로 바꿔
    글로브와 비교하는 데 쓰므로, 공유 체크아웃 루트를 넘기면 worktree 안 파일이 전부 `relative_to`
    에서 벗어나 경고가 하나도 뜨지 않는다.
    """
    try:
        rel = target.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return []                         # 레포 밖 파일(스크래치패드 등)은 대상이 아니다
    hits: list[str] = []
    for path, text in task_files(board):
        if sid8 and f"#sid:{sid8}" in text:
            continue                      # 내 과업
        for pattern in touch_globs(text):
            if fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern.rstrip("*")):
                hits.append(f"{path.stem} ({pattern})")
                break
    return hits
