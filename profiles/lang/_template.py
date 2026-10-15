"""profiles/lang/_template.py — 새 언어팩의 시작점. 복사해서 `profiles/lang/<이름>.py` 로 채운다.

커널에 없는 언어로 하네스를 옮기는 일이 이 파일 하나를 채우는 것이다. 초기 설정의 스택 맞춤이 여기서 만든다.
선언 목록의 정본은 `kernel/lang.py` 헤더이고, 이 파일은 그 목록의 키를 한 번씩 보여준다. 값은 모양이 맞는 예시일 뿐이라
언어에 맞게 전부 바꾼다. 실물 본보기는 `kernel/langs/java.py`(정규식 분석기)·`go.py`(tree-sitter + 정규식 대체)다.
`_` 로 시작하는 파일은 팩으로 세지 않으므로 이 파일 자체는 선택할 수 없다.

끝나는 조건은 사람이 아니라 `python -X utf8 -m kernel.pack_check <이름>` 이 정한다 — [미검증] 0 이어야 1급 팩이다.
"""

from __future__ import annotations

# 소스 확장자와 구문 이름. 확장자가 틀리면 대상이 0건이라 나머지를 아무리 채워도 검사가 안 돈다.
EXT = ("*.ext",)
SYNTAX = "ext"                  # 컴포넌트 그래프의 technology.syntax 와 같은 값

# 구문 사실을 만드는 분석기. 중괄호 언어는 "regex" 부터 쓴다 — 설치가 0개다.
#   "regex"       REGEX 정규식 셋 — 함수 머리 뒤 첫 `{` 의 짝이 함수 범위다. kernel/analyzers/regex.py
#   "treesitter"  QUERIES 실행 — tree_sitter 와 GRAMMAR 패키지가 설치돼 있어야 한다. REGEX 도 적으면 없을 때 그것으로 내려간다
#   "command"     ANALYZER_CMD 가 낸 JSON — 정규식으로 안 되는 언어의 탈출구. 계약은 kernel/analyzers/command.py 헤더
#   "python"      표준 ast — SYNTAX 가 python 일 때만
ANALYZER = "regex"
ANALYZER_CMD: tuple[str, ...] = ()   # command 일 때 — 예: ("python", "tools/harness_facts.py"). 상대경로는 프로젝트 루트 기준
GRAMMAR = None                  # treesitter 일 때 문법 패키지 모듈 이름. 비우면 tree_sitter_<SYNTAX>

# regex 일 때 채운다. 이름은 이름 있는 그룹이 잡고(대안마다 다른 그룹 이름 가능), imports 의 `block` 그룹은 그 안의 따옴표 문자열 전부가 경로다.
REGEX = {
    "functions": (r"^[ \t]*(?:pub(?:\([^)\n]*\))?[ \t]+)?(?:(?:const|async|unsafe|extern(?:[ \t]+\"[^\"\n]*\")?)[ \t]+)*"
                  r"fn[ \t]+(?P<name>[A-Za-z_]\w*)"),
    "imports": r"^[ \t]*(?:pub(?:\([^)\n]*\))?[ \t]+)?use[ \t]+(?P<path>[\w:]+)",
    "top_symbols": (r"^(?:pub(?:\([^)\n]*\))?[ \t]+)?(?:(?:const|async|unsafe)[ \t]+)*"
                    r"(?:fn|struct|enum|trait|type|const|static|mod)[ \t]+(?P<name>[A-Za-z_]\w*)"),
}
# treesitter 일 때 채운다. @def 가 함수 범위·@name 이 이름, @path 가 import 대상이다.
QUERIES: dict[str, str] = {}
# import 를 레포 모듈로 푸는 규칙 — go_package(디렉터리=패키지, 가장 가까운 go.mod) · relative(`./x`·`../y`)
# · dotted(`a.b.C`·`crate::a::b` 를 레포 모듈 키 접미로). 비우면 경로가 곧 모듈 키다
MODULE_RULE = "dotted"
PUBLIC_RULE = None              # kernel/lang.py PUBLIC_RULES 중 하나. 비우면 전부 공개다
# 표준 라이브러리 이름 접두 — 사람에게 물을 외부 의존이 아니다. `.`·`:`·`/` 로 끝나면 접두, 아니면 이름 하나
STDLIB = ("std", "core", "alloc")    # dotted 규칙은 `std::x::Y` 를 첫 마디(`std`)로 부른다

# 이 팩이 1급으로 돌기 위해 필요한 도구. `harness_install.py --doctor` 가 check 를 돌려 없는 것만 보고한다.
REQUIRES = (
    {"name": "ext", "check": ["ext", "version"], "install": "https://example.com/ext/install"},
)

# 관용구 정규식. 적지 않은 키는 파이썬팩 값이 기본이라 이 언어에 맞지 않으면 반드시 덮어쓴다.
PATTERNS = {
    "env_read":    r"\benv::var\(",
    "any_type":    r"\bdyn\s+Any\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*use\b",
}

# 이 언어에서는 규칙 자체가 성립하지 않는 게이트와 그 사유. "못 함"이 아니라 "해당 없음"이다.
# Python 의미론 게이트(kernel/lang.py PYTHON_ONLY)는 이 언어에서 왜 성립하지 않는지를 적는다. 빼면 영구 [TOOL] 이다.
NOT_APPLICABLE = {
    "type_hints": "the language enforces types, so they cannot be missing",
    "undefined_const":      "Python-only check — the ext compiler rejects undefined names",
    "type_checking_future": "Python-only check — ext has no typing.TYPE_CHECKING",
}

# 이름 표기 — function(snake·camel·pascal, `|` 로 여럿)·keys(응답 키). 한 모듈만 맡을 기능 — {가족: 정규식}
NAMING = {"function": "snake", "keys": "snake"}
OWNED = {"http_client": r"^\s*use\s+(?:reqwest|hyper|ureq)\b"}

# 위임할 표준 도구. 출력은 `경로:줄: 메시지` (gcc 형식) 이어야 한다.
LINTERS = [
    {"slug": "lint", "cmd": ["ext", "lint", "./..."], "parse": "gcc", "install": "https://example.com/ext/install"},
]

# 적합성 검사 예제 — 서식은 kernel/pack_check.py 헤더. NOT_APPLICABLE 로 둔 게이트는 예제가 필요 없다.
#   files        분석기가 읽을 보조 파일. command 분석기는 디스크에 없는 예제를 분석할 때 이 파일들을 함께 복사한다
#   게이트 slug  violating 은 잡히고 passing 은 안 잡혀야 1급 — closures · func_limit · type_hints
#   사실 종류    source 에서 expect 가 나와야 1급 — imports(모듈 키) · top_symbols(이름). path 로 예제 파일 위치를 정한다
FIXTURES = {
    "files": {"src/db/reads.ext": "pub fn board() {\n}\n"},
    "closures": {
        "violating": "fn outer() {\n    fn inner() {\n    }\n}\n",
        "passing": "fn outer() {\n}\n",
    },
    "func_limit": {
        "violating": "fn long() {\n" + "    let x = 1;\n" * 81 + "}\n",
        "passing": "fn short() {\n}\n",
    },
    "imports": {
        "path": "src/orders/service.ext",
        "source": "use crate::db::reads;\n\nfn f() {\n}\n",
        "expect": ["src.db.reads"],
    },
    "top_symbols": {
        "source": "pub fn exported() {\n}\n\npub struct Thing {}\n",
        "expect": ["exported", "Thing"],
    },
}
