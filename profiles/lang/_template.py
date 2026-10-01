"""profiles/lang/_template.py — 새 언어팩의 시작점. 복사해서 `profiles/lang/<이름>.py` 로 채운다.

커널에 없는 언어를 초기 설정의 스택 맞춤이 여기서 만든다. 선언 목록의 정본은 `kernel/lang.py` 헤더이고,
이 파일은 그 목록의 모든 키를 한 번씩 보여준다. 값은 모양이 맞는 예시일 뿐이라 언어에 맞게 전부 바꾼다.
`_` 로 시작하는 파일은 팩으로 세지 않으므로 이 파일 자체는 선택할 수 없다.

끝나는 조건은 사람이 아니라 `python -X utf8 -m kernel.pack_check <이름>` 이 정한다 — [미검증] 0 이어야 1급 팩이다.
"""

from __future__ import annotations

# 소스 확장자와 구문 이름. 확장자가 틀리면 대상이 0건이라 나머지를 아무리 채워도 검사가 안 돈다.
EXT = ("*.ext",)
SYNTAX = "ext"                  # 컴포넌트 그래프의 technology.syntax 와 같은 값

# 구문 사실을 만드는 분석기. 셋 중 하나다.
#   "python"      표준 ast — SYNTAX 가 python 일 때만
#   "treesitter"  QUERIES 실행 — tree_sitter 와 GRAMMAR 패키지가 설치돼 있어야 한다
#   "command"     ANALYZER_CMD 가 낸 JSON — tree-sitter 를 못 쓰는 환경의 탈출구. 계약은 kernel/analyzers/command.py 헤더
ANALYZER = "command"
ANALYZER_CMD = ("python", "tools/harness_facts.py")   # 인자로 파일 상대경로, stdout 에 FileFacts JSON 배열
GRAMMAR = None                  # treesitter 일 때 문법 패키지 모듈 이름. 비우면 tree_sitter_<SYNTAX>

# treesitter 일 때만 채운다. @def 가 함수 범위·@name 이 이름, @path 가 import 대상이다. command 면 비워 둔다.
QUERIES: dict[str, str] = {}
MODULE_RULE = None              # kernel/lang.py MODULE_RULES 중 하나. 비우면 경로가 곧 모듈 키다
PUBLIC_RULE = None              # kernel/lang.py PUBLIC_RULES 중 하나. 비우면 전부 공개다

# 이 팩이 1급으로 돌기 위해 필요한 도구. `harness_install.py --doctor` 가 check 를 돌려 없는 것만 보고한다.
REQUIRES = (
    {"name": "ext", "check": ["ext", "version"], "install": "https://example.com/ext/install"},
)

# 관용구 정규식. 적지 않은 키는 파이썬팩 값이 기본이라 이 언어에 맞지 않으면 반드시 덮어쓴다.
PATTERNS = {
    "env_read":    r"\bgetenv\(",
    "any_type":    r"\bany\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*import\b",
}

# 이 언어에서는 규칙 자체가 성립하지 않는 게이트와 그 사유. "못 함"이 아니라 "해당 없음"이다.
NOT_APPLICABLE = {
    "type_hints": "the language enforces types, so they cannot be missing",
}

# 위임할 표준 도구. 출력은 `경로:줄: 메시지` (gcc 형식) 이어야 한다.
LINTERS = [
    {"slug": "lint", "cmd": ["ext", "lint", "./..."], "parse": "gcc", "install": "https://example.com/ext/install"},
]

# 적합성 검사 예제 — 서식은 kernel/pack_check.py 헤더. NOT_APPLICABLE 로 둔 게이트는 예제가 필요 없다.
#   files        분석기가 읽을 보조 파일. command 분석기는 디스크에 없는 예제를 분석할 때 이 파일들을 함께 복사한다
#   게이트 slug  violating 은 잡히고 passing 은 안 잡혀야 1급 — closures · func_limit · type_hints
#   사실 종류    source 에서 expect 가 나와야 1급 — imports(모듈 키) · top_symbols(이름)
FIXTURES = {
    "files": {},
    "closures": {
        "violating": "func Outer {\n  func inner {\n  }\n}\n",
        "passing": "func Outer {\n}\n",
    },
    "func_limit": {
        "violating": "func Long {\n" + "  x = 1\n" * 81 + "}\n",
        "passing": "func Short {\n}\n",
    },
    "imports": {
        "source": 'import "db/reads"\n\nfunc F {\n}\n',
        "expect": ["db.reads"],
    },
    "top_symbols": {
        "source": "func Exported {\n}\n\ntype Thing\n",
        "expect": ["Exported", "Thing"],
    },
}
