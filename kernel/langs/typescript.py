"""kernel/langs/typescript.py — TypeScript 언어팩 (서버가 Node 인 경우). 프로젝트는 `profiles/lang/` 에서 덮어쓸 수 있다.

프론트가 TS 인 경우는 이 팩이 아니라 프로파일의 `UI_EXT` 가 담당한다. 여기는 **서버까지
TS 인 프로젝트**용이다.

타입 검사는 `tsc --noEmit` 이 한다. 하네스가 다시 구현하지 않는다. 구문 사실은 정규식 분석기(`REGEX`, 설치 0개)가
내고, import 는 `./`·`../` 만 레포 내부로 본다(MODULE_RULE relative). 화살표 함수는 `const f = (…) =>` 꼴만 센다.
"""

from __future__ import annotations

EXT = ("*.ts", "*.tsx", "*.mts", "*.cts")
SYNTAX = "typescript"
ANALYZER = "regex"
MODULE_RULE = "relative"

# 함수 머리 — function 선언, `const f = (…) =>`, 클래스·객체 메서드. 메서드 대안은 호출문도 잡지만 본문 `{` 가 없으면 빠진다.
REGEX = {
    "functions": (r"^[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?function[ \t]*\*?[ \t]*(?P<name>[A-Za-z_$][\w$]*)"
                  r"|^[ \t]*(?:export[ \t]+)?(?:const|let|var)[ \t]+(?P<arrow>[A-Za-z_$][\w$]*)[ \t]*(?::[^=\n;]+)?=[ \t]*(?:async[ \t]*)?\("
                  r"|^[ \t]+(?:(?:public|private|protected|static|async|readonly|override|get|set)[ \t]+)*"
                  r"(?!(?:if|for|while|switch|catch|return|function|new|else|await|typeof|throw)\b)(?P<method>[A-Za-z_$][\w$]*)[ \t]*\("),
    "imports": (r"^[ \t]*(?:import|export)[ \t]+(?:type[ \t]+)?(?:[^'\";]*?[ \t]from[ \t]*)?['\"](?P<path>[^'\"\n]+)['\"]"
                r"|\brequire\([ \t]*['\"](?P<req>[^'\"\n]+)['\"][ \t]*\)"),
    "top_symbols": (r"^export[ \t]+(?:default[ \t]+)?(?:declare[ \t]+)?(?:abstract[ \t]+)?(?:async[ \t]+)?"
                    r"(?:function\*?|class|const|let|var|interface|type|enum)[ \t]+(?P<name>[A-Za-z_$][\w$]*)"),
}

# Node 내장 모듈 — 사람에게 물을 외부 의존이 아니다. `node:` 접두 표기와 맨이름 표기 둘 다 쓴다.
STDLIB = ("node:", "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "crypto", "dgram",
          "diagnostics_channel", "dns", "events", "fs", "http", "http2", "https", "inspector", "module", "net", "os",
          "path", "perf_hooks", "process", "querystring", "readline", "repl", "stream", "string_decoder", "timers",
          "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib")

# 적합성 검사 예제 — type_hints 는 tsc, closures 는 NOT_APPLICABLE 이라 예제가 없다.
FIXTURES = {
    "func_limit": {
        "violating": "export function long(): number {\n" + "  let x = 1;\n" * 80 + "  return x;\n}\n",
        "passing": "export const short = (a: number): number => {\n  return a;\n};\n",
    },
    "imports": {
        "path": "src/orders/api.ts",
        "source": ('import fs from "node:fs";\nimport { board } from "../db/reads";\n'
                   'import type { Row } from "./types.js";\nconst lib = require("./lib");\n'),
        "expect": ["src.db.reads", "src.orders.types", "src.orders.lib"],
    },
    "top_symbols": {
        "source": "export function place() {}\nexport class Order {}\nexport const LIMIT = 3;\nfunction hidden() {}\n",
        "expect": ["place", "Order", "LIMIT"],
    },
}

PATTERNS = {
    "env_read":    r"\bprocess\.env\b|\bDeno\.env\b",
    "any_type":    r":\s*any\b|\bas\s+any\b|<\s*any\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*import\b|\brequire\s*\(",
}

NOT_APPLICABLE = {
    "type_hints": "tsc already checks this, so it would duplicate",
    "closures":   "callbacks and handlers are idiomatic, so banning nested functions is wrong",
    "undefined_const":      "Python-only check — tsc rejects undefined names",
    "type_checking_future": "Python-only check — TypeScript has no typing.TYPE_CHECKING",
}

NAMING = {"function": "camel|pascal", "keys": "camel"}     # pascal 은 React 컴포넌트·생성 함수
OWNED = {
    "http_client": (r"""^\s*import\b[^'"]*['"](?:axios|node-fetch|got|undici)['"]"""
                    r"""|\brequire\(\s*['"](?:axios|node-fetch|got|undici)['"]"""),
}

LINTERS = [
    {"slug": "tsc", "cmd": ["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"],
     "parse": "gcc", "install": "npm i -D typescript"},
]
