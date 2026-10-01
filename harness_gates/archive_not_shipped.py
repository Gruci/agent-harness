"""harness_gates/archive_not_shipped.py — 배포본에 작업 archive 를 싣지 않는다.

이 레포의 master 는 새 프로젝트가 clone 해 가는 배포본이다. `docs/tasks/archive/` 는
하네스 자신을 개발하며 나온 research·plan·mockup 산출물이라, 실어 보내면 새 프로젝트가
남의 작업 기록을 안고 출발한다. 로컬에는 남기되 git 추적만 막는다.

clone 해 간 프로젝트에는 이 규칙이 없다. 그쪽은 자기 archive 를 자기 레포에 커밋하는 게 맞다.
그래서 이 게이트는 커널이 아니라 여기에 둔다. 커널에는 특정 프로젝트에만 맞는 규칙을 넣지 않는다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kernel.context import ROOT

TITLE = "No task archive in the shipped repo"
ARCHIVE_PREFIX = "docs/tasks/archive/"


def tracked_archive_files() -> list[str]:
    """git 이 추적 중인 archive 아래 파일 목록. git 명령이 실패하면 빈 목록을 돌려준다 — 판정할 수 없으면 통과로 본다."""
    done = subprocess.run(
        ["git", "ls-files", "--cached", ARCHIVE_PREFIX],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if done.returncode != 0:
        return []
    return [line for line in done.stdout.splitlines() if line.strip()]


def run(py_files: list[Path], ui_files: list[Path]) -> list[tuple[str, list[str]]]:
    """레포 전체를 한 번에 판정하므로 인자로 받은 파일 목록은 쓰지 않는다. git 이 추적하는 파일 전체를 본다."""
    del py_files, ui_files
    return [(TITLE, [f"{rel}: task archive is shipped in the repo — "
                     f"untrack it with `git rm --cached {rel}`. The local file stays"
                     for rel in tracked_archive_files()])]
