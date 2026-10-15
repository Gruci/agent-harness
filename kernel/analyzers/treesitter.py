"""kernel/analyzers/treesitter.py — 언어팩 QUERIES 를 실행해 FileFacts 를 만드는 엔진.

언어별 차이는 팩이 주는 쿼리 문자열과 규칙 이름뿐이다. 이 모듈은 어느 언어의 노드 이름도 모른다.

  QUERIES["functions"]     @def 와 그 안의 @name — 함수 범위·중첩(감싸는 @def)·공개 여부
  QUERIES["imports"]       @path — import 대상. MODULE_RULE 이 레포 안 모듈 키로 바꾼다
  QUERIES["top_symbols"]   @name — 모듈 최상위 이름
  MODULE_RULE·PUBLIC_RULE  kernel/analyzers/modules.py — 정규식 엔진과 같은 규칙을 쓴다

`tree_sitter` 와 문법 패키지(`tree_sitter_<SYNTAX>`)는 선택 의존이다. import 는 이 모듈에서만, 그것도
필요한 시점에만 한다. 그래서 커널이 설치를 요구하는 의존성은 여전히 0개다. 없으면 `build` 가 사유를 돌려주고 러너는
그 게이트를 [TOOL] 로 찍는다 — 팩이 REGEX 도 선언했으면 정규식 엔진으로 내려간다(kernel/facts.py).
py-tree-sitter 0.23 이상을 기준으로 하고, 0.25 의 QueryCursor 도 받는다.

타입 누락(`missing_types`)은 여기서 내지 않는다 — tree-sitter 를 쓰는 언어는 대개 타입을 강제하고,
그렇지 않은 언어는 팩이 NOT_APPLICABLE 로 선언한다.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from pathlib import Path

from kernel import facts, lang
from kernel.analyzers.modules import ModuleRules, is_public

MISSING = "tree-sitter not installed — install it in the initial stack setup"
_GRAMMAR_MISSING = "grammar not installed — install it in the initial stack setup"


def install_missing(reason: str) -> bool:
    """사유가 설치 누락인가. 쿼리 컴파일 실패는 팩 결함이라 다른 엔진으로 덮으면 안 된다."""
    return reason == MISSING or reason.endswith(_GRAMMAR_MISSING)


def _grammar(package: str, syntax: str) -> object | None:
    """문법 패키지의 언어 포인터. `tree_sitter_typescript` 처럼 언어별 함수 이름을 쓰는 패키지도 받는다."""
    try:
        module = importlib.import_module(package)
    except ImportError:
        return None
    for name in ("language", f"language_{syntax}"):
        maker = getattr(module, name, None)
        if callable(maker):
            return maker()
    return None


def _compile(ts, language, source: str):
    """0.23+ 는 Query(language, source), 그 전은 language.query(source)."""
    query_cls = getattr(ts, "Query", None)
    if query_cls is not None:
        try:
            return query_cls(language, source)
        except TypeError:
            pass
    return language.query(source)


def _matches(ts, query, node) -> list[dict[str, list]]:
    """매치마다 캡처 이름 → 노드 목록 딕셔너리를 만든다. 0.25 는 QueryCursor, 그 전은 query.matches 를 쓴다."""
    cursor_cls = getattr(ts, "QueryCursor", None)
    raw = cursor_cls(query).matches(node) if cursor_cls is not None else query.matches(node)
    groups: list[dict[str, list]] = []
    for _pattern, captured in raw:
        groups.append({name: list(nodes) if isinstance(nodes, list) else [nodes]
                       for name, nodes in captured.items()})
    return groups


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def build(pack: Mapping[str, object], root: Path) -> tuple["Engine | None", str]:
    """팩의 엔진을 돌려주고, 못 만들면 그 사유를 돌려준다. 설치 문제인지 팩 결함(쿼리 오류)인지를 사유 문구로 구분한다."""
    try:
        import tree_sitter as ts
    except ImportError:
        return None, MISSING
    syntax = str(pack["SYNTAX"])
    package = lang.grammar_module(dict(pack)) or f"tree_sitter_{syntax}"   # 팩의 GRAMMAR 가 정본이고, 비우면 구문 이름에서 만든다
    grammar = _grammar(package, syntax)
    if grammar is None:
        return None, f"tree-sitter-{syntax} {_GRAMMAR_MISSING}"
    queries = dict(pack.get("QUERIES") or {})   # type: ignore[call-overload]  # lang.load 가 매핑임을 검증했다
    try:
        language = ts.Language(grammar)
        compiled = {kind: _compile(ts, language, str(source)) for kind, source in queries.items()}
    except Exception as exc:     # 어떤 예외형이든 팩 결함이다 — 설치하라고 안내하면 안 된다
        return None, f"language pack {syntax} QUERIES failed to compile: {type(exc).__name__}: {exc}"
    return Engine(ts, pack, root, language, compiled), ""


class Engine:
    label = "tree-sitter"

    def __init__(self, ts, pack: Mapping[str, object], root: Path, language, queries: dict) -> None:
        self._ts = ts
        try:
            self._parser = ts.Parser(language)
        except TypeError:                       # 0.21 이하 — 인자 없이 만들고 언어를 붙인다
            self._parser = ts.Parser()
            self._parser.set_language(language)
        self._queries = queries
        self.syntax = str(pack["SYNTAX"])
        self.suffixes = tuple(str(pattern).lstrip("*") for pattern in pack["EXT"])   # type: ignore[union-attr]
        self.kinds = facts.query_kinds(queries)
        self._rules = ModuleRules(pack.get("MODULE_RULE"), root, self.suffixes)
        self._public_rule = pack.get("PUBLIC_RULE")

    def module_key(self, rel: str) -> str:
        return self._rules.module_key(rel)

    def _functions(self, root_node, source: bytes) -> tuple[facts.Function, ...]:
        defs: list[tuple[object, str]] = []
        for match in _matches(self._ts, self._queries["functions"], root_node):
            names = match.get("name", [])
            for node in match.get("def", []):
                inside = [n for n in names if n.start_byte >= node.start_byte and n.end_byte <= node.end_byte]
                defs.append((node, _text(inside[0], source) if inside else ""))
        # 시작 오름차순·같은 시작이면 바깥이 먼저 — 그러면 나를 감싸는 것 중 마지막이 가장 안쪽이다.
        defs.sort(key=lambda item: (item[0].start_byte, -item[0].end_byte))   # type: ignore[attr-defined]
        found: list[facts.Function] = []
        for node, name in defs:
            parent = None
            for other, other_name in defs:
                if other is not node and other.start_byte <= node.start_byte and node.end_byte <= other.end_byte:   # type: ignore[attr-defined]
                    parent = other_name
            found.append(facts.Function(name, node.start_point[0] + 1, node.end_point[0] + 1, parent,   # type: ignore[attr-defined]
                                        is_public(self._public_rule, name), None))
        return tuple(found)

    def _imports(self, root_node, source: bytes, rel: str) -> tuple[facts.Import, ...]:
        found: list[facts.Import] = []
        for match in _matches(self._ts, self._queries["imports"], root_node):
            for node in match.get("path", []):
                resolved = self._rules.resolve(_text(node, source).strip('"`\''), rel)
                if resolved is not None:
                    found.append(facts.Import(resolved[0], resolved[1], None, node.start_point[0] + 1))
        return tuple(found)

    def _top_symbols(self, root_node, source: bytes) -> frozenset[str]:
        return frozenset(_text(node, source)
                         for match in _matches(self._ts, self._queries["top_symbols"], root_node)
                         for node in match.get("name", []))

    def analyze(self, text: str, rel: str) -> facts.FileFacts:
        module = self.module_key(rel)
        source = text.encode("utf-8")
        root_node = self._parser.parse(source).root_node
        if root_node.has_error:
            # tree-sitter 는 오류를 품고 계속 파싱한다. 반쪽 사실로 판정하면 조용히 빠지는 위반이 생긴다.
            return facts.FileFacts(rel, module, error="syntax error — tree-sitter produced an ERROR node")
        return facts.FileFacts(
            rel=rel, module=module,
            functions=self._functions(root_node, source) if "functions" in self._queries else (),
            imports=self._imports(root_node, source, rel) if "imports" in self._queries else (),
            top_symbols=self._top_symbols(root_node, source) if "top_symbols" in self._queries else frozenset(),
        )
