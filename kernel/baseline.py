"""kernel/baseline.py — 설치 시점에 동결한 위반 목록(래칫: 줄기만 하고 늘지 않는 목록)을 읽어 적용한다.

하네스를 기존 레포에 설치한 첫 실행이 위반을 수백 건 쏟아내면 사람은 게이트를 통째로 끈다.
하네스가 실제로 버려지는 경로가 이것이다. 그래서 설치할 때 현재 위반을 (slug, 파일) 단위로 동결해
모든 검사가 통과한 상태에서 출발한다. 줄번호로 동결하지 않는 이유는 코드가 한 줄만 밀려도 동결이 풀리기 때문이다.

러너는 동결을 적용하고, 설치 스크립트는 동결 목록을 만들고, trace 는 위반에서 파일 경로를 뽑는다.
셋이 같은 판정을 쓰므로 러너 밖으로 뺐다. 러너 파일이 400줄 상한을 지키게 하려는 것도 이유다.
"""

from __future__ import annotations

from kernel.context import ROOT, read_pairs

BASELINE_FILE = ROOT / "harness_baseline.txt"


def violation_path(violation: str) -> str | None:
    """위반 문자열 앞머리의 파일 경로. 파일에 귀속되지 않는 전역 위반이면 None."""
    head = violation.split(":", 1)[0].strip()
    if not head or " " in head or ("/" not in head and "." not in head):
        return None
    return head


def load_baseline() -> set[tuple[str, str]]:
    return read_pairs(BASELINE_FILE)


def apply_baseline(sections: list) -> list:
    """동결된 (slug, 파일) 쌍의 위반을 걸러낸다. Section 형태의 정의는 runner 에 있다."""
    frozen = load_baseline()
    if not frozen:
        return sections
    kept = []
    for slug, title, violations, skipped in sections:
        live = [v for v in violations
                if (slug, violation_path(v) or "") not in frozen]
        kept.append((slug, title, live, skipped))
    return kept
