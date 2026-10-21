"""kernel/profile_checks.py — 완료 계약 설정(`REQUIRED_CHECKS`·`TESTS`·`TOUCH_ENFORCE`)의 형식 검사.

`kernel/profile.py` 의 `_shape_errors` 가 부른다. 값의 의미 판정은 쓰는 쪽이 한다 — 필수 검사는 `kernel/required.py`,
제품 테스트 선언은 그 실행기 `kernel/tests_run.py` 의 `declaration_errors` 가 정본이다. 형식 규칙을 두 곳에 두지 않으려고
여기서는 그 함수를 부르기만 한다.
"""

from __future__ import annotations

from typing import Any

from kernel.tests_run import declaration_errors   # tests_run 은 kernel.profile 을 import 하지 않아 순환이 없다

PROFILE_FILE = "harness_profile.py"


def contract_errors(mod: Any) -> list[str]:
    """세 설정의 형식 위반 문장 목록. 선언하지 않은 설정은 검사하지 않는다."""
    found: list[str] = []
    required = getattr(mod, "REQUIRED_CHECKS", ())
    if isinstance(required, (tuple, list)) and not all(isinstance(slug, str) and slug.strip() for slug in required):
        found.append(f"{PROFILE_FILE}: REQUIRED_CHECKS must list non-empty check slugs")
    enforce = getattr(mod, "TOUCH_ENFORCE", False)
    if not isinstance(enforce, bool):
        found.append(f"{PROFILE_FILE}: TOUCH_ENFORCE must be True or False — current value is {enforce!r}")
    # 빈 값·None 까지 실행기의 검증기에 넘긴다 — 형식 규칙의 주인은 그쪽 하나다
    found += [f"{PROFILE_FILE}: {error}" for error in declaration_errors(getattr(mod, "TESTS", ()))]
    return found
