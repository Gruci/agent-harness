"""kernel/langs/go.py — Go 언어팩. 프로젝트는 `profiles/lang/go.py` 로 덮어쓸 수 있다.

관용구 린트는 `go vet` 과 `staticcheck` 에 위임한다. 우리가 Go 의미론을 다시 만들 이유가
없다 — 그쪽이 정확하고, 이미 그 생태계의 표준이다. 구문 사실(함수 범위·import·최상위 이름)만
`QUERIES` 로 뽑아 언어 무관 게이트와 컴포넌트 의존 검사를 켠다. tree-sitter 는 초기 설정의
스택 맞춤에서 설치한다(선택 의존).

`NOT_APPLICABLE` 이 셋인 것이 이 팩의 요점이다. Go 에서 타입힌트 게이트가 안 도는 건
손실이 아니라 **언어가 이미 보장**하기 때문이다. 손실과 비손실을 구분해야 무엇을 잃었는지
알 수 있다.

레퍼런스 팩이다 — 새 언어팩은 이 파일의 선언을 본떠 만들고 `kernel.pack_check` 로 1급을 확인한다.
"""

from __future__ import annotations

EXT = ("*.go",)
SYNTAX = "go"

# tree-sitter-go 쿼리. @def 는 범위, 그 안의 @name 이 이름이다. 클로저(func_literal)는 관용구라 안 본다.
QUERIES = {
    "functions": (
        "(function_declaration name: (identifier) @name) @def\n"
        "(method_declaration name: (field_identifier) @name) @def"
    ),
    "imports": "(import_spec path: (interpreted_string_literal) @path)",
    "top_symbols": (
        "(source_file (function_declaration name: (identifier) @name))\n"
        "(source_file (type_declaration (type_spec name: (type_identifier) @name)))"
    ),
}
MODULE_RULE = "go_package"      # 디렉토리 = 패키지. go.mod 의 module 접두가 붙은 import 만 레포 내부다
PUBLIC_RULE = "capitalized"     # 대문자 시작이 공개 — 언어 규칙 그대로

# 적합성 검사 예제 — closures·type_hints 는 NOT_APPLICABLE 이라 예제가 없다.
FIXTURES = {
    "files": {"go.mod": "module example.com/app\n"},
    "func_limit": {
        "violating": "package a\n\nfunc F() {\n" + "\t_ = 1\n" * 81 + "}\n",
        "passing": "package a\n\nfunc F() {}\n",
    },
    "imports": {
        "source": 'package a\n\nimport (\n\t"fmt"\n\t"example.com/app/db/reads"\n)\n',
        "expect": ["db.reads"],
    },
    "top_symbols": {
        "source": "package a\n\nfunc Exported() {}\n\ntype Thing struct{}\n",
        "expect": ["Exported", "Thing"],
    },
}

PATTERNS = {
    "env_read":    r"\bos\.(Getenv|LookupEnv|Environ)\b",
    "any_type":    r"\binterface\s*\{\s*\}|(?<![\w.])\bany\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*import\b|^\s*\"[\w./-]+\"",
}

# 규칙 자체가 이 언어에서 성립하지 않는 것들. "못 함"이 아니라 "해당 없음"이다.
NOT_APPLICABLE = {
    "type_hints": "언어가 타입을 강제하므로 누락이 불가능",
    "web_async":  "async/await 개념이 없음 (goroutine 은 다른 모델)",
    "closures":   "클로저가 관용구라 금지가 부적절",
}

LINTERS = [
    {"slug": "vet", "cmd": ["go", "vet", "./..."],
     "parse": "gcc", "install": "Go 툴체인에 포함"},
    {"slug": "staticcheck", "cmd": ["staticcheck", "./..."],
     "parse": "gcc", "install": "go install honnef.co/go/tools/cmd/staticcheck@latest"},
]
