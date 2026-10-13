"""kernel/frameworks/react.py — React(TSX) 화면 프레임워크팩. 프로젝트는 `profiles/framework/react.py` 로 덮어쓸 수 있다.

이 하네스가 처음 쓰인 프로젝트의 화면 판정 환경을 그대로 옮긴 레퍼런스 팩이다. 화면 게이트 6종의
규칙 본문은 `kernel/eslint.harness.mjs` 한 벌이고, 이 팩은 그 규칙이 읽을 AST 를 만드는 파서와
대상 확장자만 선언한다. Vue·Svelte 팩은 파서와 확장자를 바꾸면 되고 규칙은 그대로 성립한다.

새 화면팩은 이 파일을 본떠 만들고 `python -X utf8 -m kernel.pack_check <이름>` 으로 확인한다.
선언 목록의 정본은 `kernel/framework.py` 헤더다.
"""

from __future__ import annotations

ROLE = "ui"

UI_EXT = ("*.tsx", "*.ts")
ESLINT_PARSER = "@typescript-eslint/parser"
PARSER_OPTIONS = {"ecmaFeatures": {"jsx": True}, "sourceType": "module"}
ESLINT_INSTALL = "npm i -D eslint @typescript-eslint/parser typescript"

# 적합성 검사 예제 — 화면 게이트 slug 마다 위반 하나와 통과 하나. ESLint 가 있는 환경에서만 실측한다.
FIXTURES = {
    "ts_any": {
        "violating": "export const count: any = 1;\n",
        "passing": "export const count: number = 1;\n",
    },
    "raw_fetch": {
        "violating": "export const load = () => fetch('/api/orders');\n",
        "passing": "import { useApi } from './useApi';\nexport const load = () => useApi('/api/orders');\n",
    },
    "hex_literal": {
        "violating": "export const accent = '#ff0000';\n",
        "passing": "export const accent = 'var(--accent)';\n",
    },
    "responsive": {
        "violating": "export const panel = { width: '480px' };\n",
        "passing": "export const panel = { maxWidth: '100%' };\n",
    },
    "browser_api": {
        "violating": "export const saved = localStorage.getItem('draft');\n",
        "passing": "import { storage } from './platform';\nexport const saved = storage.get('draft');\n",
    },
    "hash_nav": {
        "violating": "export const go = () => history.pushState(null, '', '#tab');\n",
        "passing": "export const go = () => { location.hash = '#tab'; };\n",
    },
}
