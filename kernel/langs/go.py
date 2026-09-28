"""kernel/langs/go.py — Go 언어팩. 프로젝트는 `profiles/lang/go.py` 로 덮어쓸 수 있다.

관용구 린트는 `go vet` 과 `staticcheck` 에 맡긴다. Go 의미론을 다시 구현할 이유가
없다. 그 도구들이 정확하고 이미 Go 생태계의 표준이다. 구문 사실(함수 범위·import·최상위 이름)만
`QUERIES` 로 뽑아 언어 무관 게이트와 컴포넌트 의존 검사를 켠다. tree-sitter 는 선택 의존성이며
초기 설정에서 스택을 맞출 때 설치한다.

`NOT_APPLICABLE` 항목이 셋이라는 점이 이 팩의 요점이다. Go 에서 타입힌트 게이트가 돌지 않는
것은 검사를 잃은 게 아니라 **언어가 이미 보장**하기 때문이다. 잃은 검사와 필요 없는 검사를
구분해야 실제로 무엇을 잃었는지 알 수 있다.

이 파일은 레퍼런스 팩이다. 새 언어팩은 이 파일의 선언을 본떠 만들고, `kernel.pack_check` 출력에
[미검증] 이 없는 1급 팩인지 확인한다.
"""

from __future__ import annotations

EXT = ("*.go",)
SYNTAX = "go"

# tree-sitter-go 쿼리. @def 가 대상의 범위이고 그 안의 @name 이 그 이름이다. 클로저(func_literal)는 Go 관용구라 보지 않는다.
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
MODULE_RULE = "go_package"      # 디렉토리 하나가 패키지 하나다. go.mod 의 module 경로로 시작하는 import 만 레포 내부로 본다
PUBLIC_RULE = "capitalized"     # 대문자로 시작하는 이름이 공개다. Go 언어 규칙 그대로다

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
