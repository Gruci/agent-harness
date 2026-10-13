"""kernel/gates/orphan_api.py — 소비 UI 가 없는 라우트.

라우트를 만들고 화면을 안 만들면 **사용자에게 그 기능은 존재하지 않는다.** 그런데 테스트는
통과하고 주소를 직접 치면 JSON 도 나오므로, 만든 쪽에서는 끝난 것처럼 보인다. 라우트를 추가하는
작업은 그 라우트를 쓰는 화면 컴포넌트까지 만들어야 끝난다.

이 규칙이 산문으로만 있는 동안 원류 프로젝트(이 하네스가 처음 쓰인 프로젝트)에 위반이 17건 쌓였다.
같은 전수감사에서 게이트로 강제하던 규칙은 위반이 0건이었다. 산문 규칙과 게이트의 차이가 그 숫자에
드러난다.

## 판정

라우트 레이어에서 서버 프레임워크팩의 `ROUTE_PATTERN` 으로 경로 리터럴을 모으고, 화면 소스 전체에서
그 문자열이 한 번도 안 나오면 위반이다. 라우트 선언의 생김새는 프레임워크마다 다르므로(FastAPI 는
데코레이터, Express 는 `app.get(...)`) 정규식은 커널이 아니라 팩이 준다.

경로 파라미터 앞까지만 비교한다 — 화면은 `/api/etf/${code}` 처럼 조립하므로 전체 문자열로
비교하면 전부 오탐이 된다. 접두가 너무 짧으면 비교를 건너뛴다(`/` 하나짜리는 어디에나 있다).

소비자가 애초에 화면이 아닌 라우트(헬스체크·웹훅·머신 API)는 이 게이트가 다루지 않는다.
그런 라우트는 동결본(baseline)에 올려 둔다. 커널은 어느 라우트가 그런지 알 수 없기 때문이다.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, _rel

MIN_PREFIX_LEN = 2


def literal_prefix(route: str) -> str:
    """경로 파라미터 앞의 고정 부분. 화면이 조립하는 뒤쪽은 비교 대상이 아니다. `{id}` 와 `:id` 둘 다 파라미터다."""
    return route.split("{")[0].split(":")[0].rstrip("/")


def routes_in(text: str, pattern: str) -> list[tuple[int, str]]:
    """소스 하나에서 (줄번호, 라우트). 팩의 패턴은 그룹 1 로 경로를 잡는다. `pack_check` 도 이 함수로 예제를 판정한다."""
    route_re = re.compile(pattern)
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = route_re.search(line)
        if match:
            found.append((number, match.group(1)))
    return found


def consumed(route: str, ui_source: str) -> bool:
    """화면 소스가 이 라우트를 쓰는가. 접두가 너무 짧으면 비교 불가라 소비로 본다."""
    prefix = literal_prefix(route)
    return len(prefix) < MIN_PREFIX_LEN or prefix in ui_source


def _declared_routes(py_files: list[Path], pattern: str) -> list[tuple[str, int, str]]:
    """(경로, 줄번호, 라우트) — 라우트 레이어 아래 선언만."""
    prefix = profile.layer("routes") or profile.layer("web")
    if not prefix:
        return []
    declared: list[tuple[str, int, str]] = []
    for path in py_files:
        rel = _rel(path)
        if not rel.startswith(prefix):
            continue
        for number, route in routes_in(path.read_text(encoding=READ_ENC, errors="replace"), pattern):
            declared.append((rel, number, route))
    return declared


def check_orphan_api(py_files: list[Path], ui_files: list[Path]) -> list[str]:
    """소비하는 화면 코드가 없는 라우트. 서버팩이 없으면 라우트를 알아볼 수 없어 빈 목록이다 — 러너가 [SKIP] 으로 찍는다."""
    if profile.SERVER is None:
        return []
    declared = _declared_routes(py_files, profile.SERVER["ROUTE_PATTERN"])
    if not declared or not ui_files:
        return []
    ui_source = "\n".join(
        path.read_text(encoding=READ_ENC, errors="replace") for path in ui_files)
    orphans: list[str] = []
    for rel, number, route in declared:
        if consumed(route, ui_source):
            continue
        orphans.append(f"{rel}:{number}: `{route}` — no UI code consumes it. "
                       f"A route is done only when its component exists")
    return orphans
