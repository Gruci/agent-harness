"""kernel/frameworks/fastapi.py — FastAPI 서버 프레임워크팩. 프로젝트는 `profiles/framework/fastapi.py` 로 덮어쓸 수 있다.

이 하네스가 처음 쓰인 프로젝트의 서버 판정을 그대로 옮긴 레퍼런스 팩이다. 데코레이터 라우트
(`@app.get("/x")`·`@router.post('/y')`), Python ast 로 보는 await 없는 async 핸들러,
`status_code=` 키워드로 에러를 실어 보내는 응답 래퍼 — 셋 다 FastAPI 관용구라 팩에 둔다.

새 서버팩은 이 파일을 본떠 만들고 `python -X utf8 -m kernel.pack_check <이름>` 으로 확인한다.
선언 목록의 정본은 `kernel/framework.py` 헤더다.
"""

from __future__ import annotations

ROLE = "server"

# 그룹 1 이 경로다. 데코레이터 이름은 무엇이든 받는다 — app 이든 router 든.
ROUTE_PATTERN = r"""@\w+\.(?:get|post|put|delete|patch)\(\s*["']([^"']+)"""

# await 없는 async 핸들러는 Python ast 로 판정한다. 스트림 응답은 await 없이도 정상이다.
ASYNC_HANDLER = "python_ast"
STREAM_RETURNS = ("StreamingResponse", "EventSourceResponse")

# 프로파일 SYMBOLS["error_response"] 래퍼가 이 키워드에 4xx·5xx 를 실으면 에러를 예외 대신 반환한 것이다.
ERROR_STATUS_KWARG = "status_code"

# 적합성 검사 예제 — route 에서 라우트 하나가 인식되고, consumer 는 소비로 통과하며, stranger 는 검출돼야 [1급] 이다.
FIXTURES = {
    "orphan_api": {
        "route": '@router.get("/api/orders")\ndef orders() -> list:\n    return []\n',
        "consumer": "fetch('/api/orders')",
        "stranger": "fetch('/api/other')",
    },
}
