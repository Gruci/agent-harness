"""profiles/framework/_template.py — 새 프레임워크팩의 시작점. 복사해서 `profiles/framework/<이름>.py` 로 채운다.

커널에 없는 프레임워크(Express·Vue 등)를 초기 설정의 스택 맞춤이 여기서 만든다. 선언 목록의 정본은
`kernel/framework.py` 헤더이고, 역할은 server·ui 둘이다. 로더는 ROLE 에 맞는 절만 읽으므로 이 파일은 두 절을
다 보여주고, 복사한 뒤 ROLE 을 정하고 다른 절은 지운다. `_` 로 시작하는 파일은 팩으로 세지 않는다.

레퍼런스는 `kernel/frameworks/fastapi.py`(server)·`react.py`(ui) 이고, 1급 판정은
`python -X utf8 -m kernel.pack_check <이름>` 이 한다.
"""

from __future__ import annotations

ROLE = "server"                 # "server" | "ui"

# ── ROLE = "server" ──────────────────────────────────────────────────────────
# 라우트 선언을 찾는 정규식. 그룹 1 이 경로다 — 소비 UI 없는 라우트 검사가 쓴다.
ROUTE_PATTERN = r"""\bapp\.(?:get|post|put|delete|patch)\(\s*["']([^"']+)"""
# await 없는 async 핸들러의 판정 방식. kernel/framework.py ASYNC_HANDLERS 중 하나. None 이면 이 프레임워크에서 성립하지 않음
ASYNC_HANDLER = None
# await 없이도 정상인 스트림 반환 타입 이름 — 접미 일치
STREAM_RETURNS: tuple[str, ...] = ()
# 에러 상태를 실어 보내는 키워드 인자. None 이면 라우트 에러 응답 검사가 성립하지 않음
ERROR_STATUS_KWARG = None

# ── ROLE = "ui" ──────────────────────────────────────────────────────────────
UI_EXT = ("*.vue", "*.ts")                  # 화면 소스 패턴. 프로파일 UI_EXT 의 기본값이다
ESLINT_PARSER = "vue-eslint-parser"         # 화면 게이트 6종이 쓸 ESLint 파서 패키지
PARSER_OPTIONS = {"sourceType": "module"}   # 그 파서에 넘길 parserOptions
ESLINT_INSTALL = "npm i -D eslint vue-eslint-parser"   # 비우면 파서 이름으로 만든다

# ── 공통 ─────────────────────────────────────────────────────────────────────
# 적합성 검사 예제 — 서식은 kernel/pack_check.py 헤더.
#   server: orphan_api 는 route 하나가 인식되고, consumer 로는 통과하며, stranger 로는 검출돼야 1급이다.
#   ui:     화면 게이트 slug 마다 violating 하나와 passing 하나. ESLint 가 있는 환경에서만 실측한다.
FIXTURES = {
    "orphan_api": {
        "route": 'app.get("/api/orders", (req, res) => res.json([]));\n',
        "consumer": "fetch('/api/orders')",
        "stranger": "fetch('/api/other')",
    },
}
