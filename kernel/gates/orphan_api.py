"""kernel/gates/orphan_api.py — 소비 UI 가 없는 라우트.

라우트를 만들고 화면을 안 만들면 **사용자에게 그 기능은 존재하지 않는다.** 그런데 테스트는
통과하고 주소를 직접 치면 JSON 도 나오므로, 만든 쪽에서는 끝난 것처럼 보인다. 라우트를 추가하는
작업은 그 라우트를 쓰는 화면 컴포넌트까지 만들어야 끝난다.

이 규칙이 산문으로만 있는 동안 원류 프로젝트(이 하네스가 처음 쓰인 프로젝트)에 위반이 17건 쌓였다.
같은 전수감사에서 게이트로 강제하던 규칙은 위반이 0건이었다. 산문 규칙과 게이트의 차이가 그 숫자에
드러난다.

## 판정

라우트 레이어의 데코레이터에서 경로 리터럴을 모으고, 화면 소스 전체에서 그 문자열이 한 번도
안 나오면 위반이다.

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

# `@app.get("/x")` · `@router.post('/y')` 형태. 데코레이터 이름은 무엇이든 받는다.
_ROUTE_DECORATOR = re.compile(r"""@\w+\.(?:get|post|put|delete|patch)\(\s*["']([^"']+)""")

MIN_PREFIX_LEN = 2


def _literal_prefix(route: str) -> str:
    """경로 파라미터 앞의 고정 부분. 화면이 조립하는 뒤쪽은 비교 대상이 아니다."""
    return route.split("{")[0].split(":")[0].rstrip("/")


def _declared_routes(py_files: list[Path]) -> list[tuple[str, int, str]]:
    """(경로, 줄번호, 라우트) — 라우트 레이어 아래 선언만."""
    prefix = profile.layer("routes") or profile.layer("web")
    if not prefix:
        return []
    declared: list[tuple[str, int, str]] = []
    for path in py_files:
        rel = _rel(path)
        if not rel.startswith(prefix):
            continue
        for number, line in enumerate(
                path.read_text(encoding=READ_ENC, errors="replace").splitlines(), 1):
            found = _ROUTE_DECORATOR.search(line)
            if found:
                declared.append((rel, number, found.group(1)))
    return declared


def check_orphan_api(py_files: list[Path], ui_files: list[Path]) -> list[str]:
    """소비하는 화면 코드가 없는 라우트."""
    declared = _declared_routes(py_files)
    if not declared or not ui_files:
        return []
    consumed = "\n".join(
        path.read_text(encoding=READ_ENC, errors="replace") for path in ui_files)
    orphans: list[str] = []
    for rel, number, route in declared:
        prefix = _literal_prefix(route)
        if len(prefix) < MIN_PREFIX_LEN or prefix in consumed:
            continue
        orphans.append(f"{rel}:{number}: `{route}` — 소비하는 화면 코드가 없다. "
                       f"컴포넌트까지가 한 단위다")
    return orphans
