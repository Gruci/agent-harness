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
import subprocess
from pathlib import Path

from kernel.context import ROOT

BRANCH_PATTERN = re.compile(r"\b((?:feat|fix|perf|chore|docs|refactor)/[A-Za-z0-9._/-]+)")


def board_dir() -> Path:
    """공유 체크아웃의 `workboard/` 경로. git 조회가 실패하면 현재 체크아웃의 `workboard/` 로 대신한다.

    이 파일은 worktree 마다 복제되므로 `ROOT / "workboard"` 로 잡으면 보드가 세션 수만큼
    따로 생긴다. 그러면 보드를 git 밖으로 꺼낸 이유, 즉 같은 머신의 파일시스템을 공유 채널로 쓴다는
    전제가 무너진다. `git rev-parse --git-common-dir` 은 worktree 안에서도 **메인 `.git`** 을
    가리키고, 그 부모가 공유 체크아웃 루트다.

    이렇게 대신해도 안전한 이유: 보드를 못 찾으면 '열린 과업 없음'으로 읽혀 남은 과업 검사가 돌고
    범위 겹침 경고가 안 뜬다. 둘 다 경고나 통과로 끝나 세션을 막지 않는다.
    """
    try:
        done = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=5)
    except Exception:
        return ROOT / "workboard"
    if done.returncode != 0 or not done.stdout.strip():
        return ROOT / "workboard"
    # 메인 체크아웃에서는 `.git` 처럼 상대경로가 온다 — 실행 cwd(ROOT) 기준으로 푼다.
    found = Path(done.stdout.strip())
    if not found.is_absolute():
        found = ROOT / found
    return found.resolve().parent / "workboard"


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


def touch_globs(text: str) -> list[str]:
    """`손대는 곳:` 아래의 글로브 목록. 다음 필드(`- 이름:`)를 만나면 끝난다."""
    globs: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- 손대는 곳:"):  # ko-ok: task-board file key is Korean
            collecting = True
            continue
        if collecting:
            # 두 칸 들여쓴 `- <glob>` 만 항목이다. 들여쓰기 없는 `- x:` 는 다음 필드다.
            if line.startswith("  - "):
                globs.append(stripped[2:].strip())
                continue
            if stripped.startswith("- "):
                break
    return globs


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
