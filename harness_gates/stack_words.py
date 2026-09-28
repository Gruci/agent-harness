"""harness_gates/stack_words.py — 문서·에이전트에 스택 이름이 되돌아오지 못하게 잠근다.

이 레포가 싣고 나가는 문서와 에이전트는 어느 스택의 프로젝트에도 그대로 깔린다. 거기에 특정
프레임워크 이름이 박히면 다른 스택을 고른 사람이 엉뚱한 지시를 받는다. 원칙은 프로파일 키로
가리키고, 스택별 관례는 프레임워크팩 옆 조각(`kernel/frameworks/<이름>.md`)에만 둔다. 이 게이트는
그 정리가 되돌아가지 않게 잠그는 래칫이다.

대상은 MD 문서와 에이전트·스킬 정의뿐이다. 코드 쪽 스택 이름은 팩과 픽스처가 담는 것이 정상이다.
허용 위치: 사고 경위는 그 스택에서 났으므로 `dev/LESSONS.md` 는 그대로 두고, 조각·픽스처·작업
산출물(`docs/tasks/`)은 스택을 담는 것이 역할이다. 벤더 사본(`.claude/skills/impeccable/`)은 우리 문서가
아니다. 허용 위치의 경로를 백틱으로 가리키는 것과 조각에서 생성한 「스택 관례」 절은 이름이 아니라
참조라 걸지 않는다.

제품 프로젝트는 자기 문서에 자기 스택을 쓰는 게 정상이므로 커널이 아니라 여기에 둔다.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import conventions
from kernel.context import READ_ENC, _rel, candidate_files

TITLE = "스택 단어 래칫(문서·에이전트)"
WORDS = re.compile(r"\b(react|fastapi|useapi|tanstack|colors\.ts)\b", re.IGNORECASE)
ALLOWED = ("dev/LESSONS.md", "kernel/frameworks/", "tests/fixtures/", "docs/tasks/",
           ".claude/skills/impeccable/")
_ALLOWED_REF = re.compile("`(?:" + "|".join(re.escape(prefix) for prefix in ALLOWED) + ")[^`]*`")


def allowed(rel: str) -> bool:
    return rel.startswith(ALLOWED)


def scan(rel: str, text: str) -> list[str]:
    """문서 하나의 위반 줄. 허용 위치면 빈 목록이고, 생성 절 안과 허용 위치 경로 참조는 건너뛴다."""
    if allowed(rel):
        return []
    bad: list[str] = []
    generated = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped == conventions.BEGIN:
            generated = True
            continue
        if stripped == conventions.END:
            generated = False
            continue
        if generated:
            continue
        for word in WORDS.findall(_ALLOWED_REF.sub("", line)):
            bad.append(f"{rel}:{number}: 스택 이름 '{word}' — 원칙은 프로파일 키로 가리키고, "
                       f"스택 관례는 kernel/frameworks/<이름>.md 조각에 둔다")
    return bad


def targets() -> list[Path]:
    """추적 중이거나 아직 add 전인 MD 전부. 허용 위치는 읽지 않는다."""
    return [path for path in candidate_files("*.md") if not allowed(_rel(path))]


def run(py_files: list[Path], ui_files: list[Path]) -> list[tuple[str, list[str]]]:
    """레포 전체 문서를 판정하므로 인자로 받은 파일 목록은 쓰지 않는다. MD 하나를 고칠 때마다 전체를 다시 본다."""
    del py_files, ui_files
    bad: list[str] = []
    for path in targets():
        bad += scan(_rel(path), path.read_text(encoding=READ_ENC, errors="replace"))
    return [(TITLE, bad)]
