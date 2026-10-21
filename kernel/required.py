"""kernel/required.py — 완료 계약: 프로젝트가 필수로 정한 검사가 실제로 돌았는가.

`--verify` exit 0 은 지금 프로파일이 켠 검사에 위반이 없다는 뜻이다. 꺼진 검사(`[SKIP]`)는 개수만 끝줄에 남는다.
그래서 프로젝트가 "이 검사는 꼭 돌아야 한다"고 정할 자리가 필요하다. 프로파일 `REQUIRED_CHECKS` 의 slug 가
`[SKIP]`·`[N/A]` 이거나 이번 실행 결과에 아예 없으면 `[FAIL]` 섹션 하나로 실패한다.

| 조건 | 결과 |
|---|---|
| 졸업 전(초기 단계이고 컴포넌트 0개) | 판정하지 않는다 — 첫 코드 전에는 꺼진 게 정상이다 |
| 목록이 비어 있음 | 판정하지 않는다 — 기존 설치는 지금과 같다 |
| 필수 slug 가 SKIP·N/A | 실패. 사유를 그대로 보인다 |
| 필수 slug 가 결과에 없음 | 실패. 오타이거나 연결되지 않은 검사다 — slug 레지스트리가 없어 프로파일을 읽을 때는 알 수 없다 |
| 예약 slug `tests` | `TESTS` 선언이 비면 실패. 테스트 실행은 finish 와 CI 의 몫이다(`kernel/tests_run.py`) |

러너가 baseline 을 적용한 뒤에 붙이므로 동결할 수 없다. 필수 목록을 줄이는 것은 완화라 편집 표면 래칫이 반대 극성으로 센다
(`harness_gates/edit_surface.py`).
"""

from __future__ import annotations

from pathlib import Path

from kernel import component_graph, profile
from kernel.sections import Section

TESTS_SLUG = "tests"


def graduated(root: Path) -> bool:
    """초기 단계를 벗어났는가. 문서 게이트의 완화와 필수 검사가 같은 규칙을 쓴다."""
    return profile.STAGE != "greenfield" or component_graph.has_components(root)


def section(sections: list[Section], root: Path) -> Section | None:
    """`--verify` 에서만 부른다. 졸업 전이거나 목록이 비면 None 이라 기존 동작 그대로다."""
    if not profile.REQUIRED_CHECKS or not graduated(root):
        return None
    graded: dict[str, list[tuple[str, str] | None]] = {}
    for slug, _title, _found, skip in sections:
        graded.setdefault(slug, []).append(skip)
    bad: list[str] = []
    for slug in profile.REQUIRED_CHECKS:
        if slug == TESTS_SLUG:
            if not profile.TESTS:
                bad.append("tests: required but TESTS is empty — declare the product test command in the profile")
        elif slug not in graded:
            bad.append(f"{slug}: required but this run produced no such check — a typo, or the check is not wired")
        else:
            bad += [f"{slug}: required but [{skip[0]}] — {skip[1]}" for skip in graded[slug] if skip is not None]
    return ("required_checks", "Required checks", bad, None)
