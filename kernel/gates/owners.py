"""kernel/gates/owners.py — 한 모듈만 맡을 기능(HTTP 클라이언트·DB 연결·날짜 포맷)이 두 파일 이상에 있는 것.

가족과 정규식은 언어팩·화면팩의 `OWNED` 가 주고 프로파일 `OWNED` 가 덮는다(`profile.OWNED`·`profile.UI_OWNED`).
표준 라이브러리는 외부 의존 검사(`context_api`)가 묻지 않으므로, 두 번째 HTTP 클라이언트나 두 번째 날짜 포맷터는
의존 그래프로는 안 보인다. 여기서는 "그 기능을 직접 하는 파일이 둘 이상인가"만 본다. 테스트와 일회성 스크립트는 기능을
소유하지 않으므로 뺀다.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, _rel
from kernel.gates.tests_pairing import is_test_path

_UI_COMMENT = ("//", "*", "/*", "{/*")


def _first_uses(files: list[Path], families: dict[str, str], marks: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """가족 → {경로: 처음 쓴 줄}. 주석 줄의 일치는 세지 않는다."""
    compiled = {name: re.compile(rule, re.M) for name, rule in families.items()}
    scratch = profile.scratch()
    uses: dict[str, dict[str, int]] = {name: {} for name in families}
    for path in files:
        rel = _rel(path)
        if is_test_path(rel) or (scratch and rel.startswith(scratch)):
            continue
        try:
            text = path.read_text(encoding=READ_ENC)
        except OSError:
            continue
        for name, rule in compiled.items():
            for match in rule.finditer(text):
                start = text.rfind("\n", 0, match.start()) + 1
                if not text[start:match.end()].lstrip().startswith(marks):
                    uses[name][rel] = text.count("\n", 0, match.start()) + 1
                    break
    return uses


def _report(uses: dict[str, dict[str, int]]) -> list[str]:
    bad: list[str] = []
    for family, where in uses.items():
        if len(where) < 2:
            continue
        for rel, line in sorted(where.items()):
            others = ", ".join(sorted(set(where) - {rel}))
            bad.append(f"{rel}:{line}: {family} also lives in {others} — one module owns it; call that module instead "
                       f"of adding a second (if both must stay, list the file in harness_baseline.txt)")
    return bad


def check_single_owner(files: list[Path], ui_files: list[Path]) -> list[str]:
    """가족마다 그 기능을 쓰는 파일이 둘 이상이면 파일마다 위반 한 줄."""
    server_marks = (profile.pattern("comment") or "#",)
    return (_report(_first_uses(files, profile.OWNED, server_marks))
            + _report(_first_uses(ui_files, profile.UI_OWNED, _UI_COMMENT)))
