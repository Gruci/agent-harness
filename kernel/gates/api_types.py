# kernel/gates/api_types.py
# API 응답 타입의 배열 필드가 옵셔널인지 검사한다. `kernel/runner.py` 가 호출한다.
#
# 왜 이 게이트가 있나 (2026-07-31 같은 사고 2회):
#   프론트 번들과 파이썬 코드는 **같은 배포에서 함께 갱신되지 않는다.** 번들만 먼저 올라간 사이에는
#   새 응답 필드가 undefined 로 도착하는데, 소비처가 `entry.asset_groups.find(...)` 처럼 확인 없이
#   접근하면 **런타임 크래시로 보드 화면 전체가 하얗게 빈다**. 순서 폴백과 달리 조용히 넘어가지도
#   않는다. 로컬에서는 백엔드가 항상 새 코드라 재현되지 않으므로 검증도 통과한다.
#
# 선언부만 검사하는 이유: 소비처를 정적으로 훑으면 로컬 변수까지 걸려 오탐이 쏟아진다(실측 43건).
#   타입을 옵셔널로 강제하면 **tsc 가 소비처 전부를 대신 잡아준다** — 선언만 검사하고 소비처 확인은
#   타입체커에 맡기는 셈이다.
#
# 래칫 방식: 기존 필드는 baseline 에 동결하고 **새로 추가되는 것만** 막는다. baseline 은 줄어들기만 할 수 있다.

from __future__ import annotations

import re
from pathlib import Path

from kernel.context import READ_ENC, ROOT, _rel, read_list

BASELINE = ROOT / "api_array_baseline.txt"
# `field: T[];` — 옵셔널(`field?:`)은 `\w+\s*:` 에 걸리지 않아 자연히 빠진다.
_ARRAY_FIELD = re.compile(r"^\s*(\w+)\s*:\s*[^;{}()]*\[\]\s*;", re.M)


def _api_type_files(ui_files: list[Path]) -> list[Path]:
    """API 응답 계약을 담는 타입 파일 — 파일명이 types.ts 이거나 types/ 아래.
    컴포넌트 안의 로컬 인터페이스는 대상이 아니다. 배포 시차 때문에 undefined 로 도착할 수 있는 것은
    **서버 응답을 받는 계약**뿐이고, 그 계약은 이 파일들에 모여 있다."""
    return [f for f in ui_files
            if f.suffix == ".ts" and (f.name == "types.ts" or "types" in f.parts)]


def collect_required_array_fields(ui_files: list[Path]) -> set[str]:
    """현재 소스의 필수(non-optional) 배열 필드 — `경로:필드명` 집합. baseline 갱신에도 쓴다."""
    found: set[str] = set()
    for f in _api_type_files(ui_files):
        rel = _rel(f)
        for m in _ARRAY_FIELD.finditer(f.read_text(encoding=READ_ENC)):
            found.add(f"{rel}:{m.group(1)}")
    return found


def baseline_ready() -> bool:
    """동결 파일 존재 여부. 없으면 이 게이트는 판정할 수 없다 — 러너가 [SKIP] 으로 찍는다.

    예전엔 여기서 조용히 빈 목록을 돌려줬다. 그러면 검사 대상이 있는데도 [OK] 로 찍혀,
    커널이 없애려던 '검사하지 않고 통과로 보고하는 문제'가 커널 안에 그대로 있었다. `harness_install.py` 가 만든다.
    """
    return BASELINE.exists()


def check_api_array_optional(ui_files: list[Path]) -> list[str]:
    """API 응답 타입에 **필수 배열 필드**가 새로 늘면 위반.
    옵셔널(`field?: T[]`)로 선언하면 tsc 가 소비처에서 폴백을 강제한다."""
    if not baseline_ready():
        return []
    frozen = read_list(BASELINE)
    return [
        f"{item}: API 응답 타입의 배열 필드는 옵셔널(`?`)로 — 백엔드 배포가 늦으면 undefined 로"
        " 도착해 소비처가 크래시한다. 필수로 둬야 하면 baseline 에 등재"
        for item in sorted(collect_required_array_fields(ui_files) - frozen)
    ]
