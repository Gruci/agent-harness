"""kernel/context.py — 프로젝트 루트와 추적 파일 수집.

커널은 `<프로젝트>/kernel/` 에 설치되므로 루트는 이 패키지의 부모다.

대상 수집이 `git ls-files` 인 이유: 추적되지 않는 파일(빌드 산출물·벤더 사본·gitignore 대상)은
프로젝트의 소유가 아니라 게이트의 대상도 아니다. 작업트리에서 지워졌는데 인덱스에만 남은
파일은 읽기 크래시를 내므로 실존 확인으로 걸러낸다.

이 모듈은 프로파일을 모른다 — `kernel/profile.py` 가 여기의 ROOT 를 쓰기 때문이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# utf-8-sig — BOM 이 붙은 파일도 읽는다. Windows 에서 PowerShell 의 `Set-Content`·`Out-File`
# 이 기본으로 BOM 을 붙이고, 그 BOM 을 그냥 utf-8 로 읽으면 첫 글자가 ﻿ 가 되어
# `ast.parse` 가 SyntaxError 를 낸다. 그러면 게이트가 "파싱 실패"를 보고하거나 조용히 건너뛴다.
# 즉 검사기가 자기 검사 대상을 못 읽는 상태가 되는데, 화면상으론 그냥 통과처럼 보인다.
READ_ENC = "utf-8-sig"


def _rel(f: Path) -> str:
    """루트 기준 경로. worktree(`worktrees/<이름>/`) 안 파일은 그 접두를 떼어낸다.
    작성 시점 훅은 메인 체크아웃의 ROOT 기준으로 실행되지만 구현은 worktree 안에서 하기 때문이다.
    접두를 떼지 않으면 경로 기반 게이트(헤더 주석 등)가 모두 오탐한다."""
    rel = f.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] == "worktrees":
        return "/".join(parts[2:])
    return rel


def read_list(path: Path) -> set[str]:
    """한 줄 한 항목 목록 파일(baseline·허용 목록). `#` 뒤는 주석이다. 파일이 없으면 빈 집합."""
    if not path.exists():
        return set()
    return {token for line in path.read_text(encoding=READ_ENC).splitlines()
            if (token := line.split("#", 1)[0].strip())}


def read_pairs(path: Path) -> set[tuple[str, str]]:
    """`<키>\\t<값>` 목록 파일. `#` 로 시작하는 줄과 값 없는 줄은 건너뛴다. 파일이 없으면 빈 집합."""
    if not path.exists():
        return set()
    pairs: set[tuple[str, str]] = set()
    for line in path.read_text(encoding=READ_ENC).splitlines():
        if line.lstrip().startswith("#"):
            continue
        key, _tab, value = line.partition("\t")
        if value.strip():
            pairs.add((key.strip(), value.strip()))
    return pairs


def git_output(*args: str) -> str | None:
    """git 표준출력. 실패·예외면 None."""
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch() -> str | None:
    """원격 기본 브랜치 이름. `origin/HEAD` 를 먼저 보고, 없으면 원격에 실제로 있는 main, master 순으로 찾는다.

    훅 쪽 `_hookio.default_branch` 와 판정이 같다. 훅은 커널을 불러오지 못해도 동작해야 하므로 같은 구현을 훅 쪽에 따로 둔다.
    """
    head = git_output("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.strip():
        return head.strip().rsplit("/", 1)[-1]
    for name in ("main", "master"):
        if git_output("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{name}") is not None:
            return name
    return None


def _ls_files(*patterns: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", *patterns], cwd=ROOT, capture_output=True, text=True
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def tracked(*patterns: str, under: str | None = None) -> list[Path]:
    """추적 중인 실존 파일. under 를 주면 그 접두 아래만."""
    return [ROOT / rel for rel in _ls_files(*patterns)
            if (under is None or rel.startswith(under)) and (ROOT / rel).exists()]


# ── 하네스 자체 파일 ───────────────────────────────────────────────────────
#
# 커널·프리셋·훅 스크립트는 프로젝트의 앱 코드가 아니다. 코드 게이트의 대상으로 넣으면
# 하네스를 설치했다는 이유만으로 위반이 생기고, 사람은 게이트가 오탐한다고 여기게 된다.
# MD 는 제외 대상이 아니다 — 하네스 문서가 규칙을 어기면 그건 진짜 위반이다.

HARNESS_OWN_PREFIXES = ("kernel/", "profiles/", ".claude/")
HARNESS_OWN_FILES = ("harness_install.py", "setup_global_permissions.py", "harness_profile.py")


def is_harness_own(rel: str) -> bool:
    return rel.startswith(HARNESS_OWN_PREFIXES) or rel in HARNESS_OWN_FILES


def candidate_files(*patterns: str, root: Path | None = None) -> list[Path]:
    """Tracked and untracked non-ignored files, with NUL-safe path handling."""
    directory = ROOT if root is None else root
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *patterns],
        cwd=directory, capture_output=True, check=True, timeout=10,
    )
    names = set(result.stdout.decode("utf-8").split("\0"))
    return [directory / name for name in sorted(names) if name and (directory / name).is_file()]


def app_code(*patterns: str, under: str | None = None) -> list[Path]:
    """Product source candidates include new files before git add."""
    return [f for f in candidate_files(*patterns)
            if not is_harness_own(_rel(f)) and (under is None or _rel(f).startswith(under))]
