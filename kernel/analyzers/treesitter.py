"""kernel/analyzers/treesitter.py — 언어팩 QUERIES 를 실행해 FileFacts 를 만드는 엔진.

언어별 차이는 팩이 주는 쿼리 문자열과 규칙 이름뿐이다. 이 모듈은 어느 언어의 노드 이름도 모른다.

  QUERIES["functions"]     @def 와 그 안의 @name — 함수 범위·중첩(감싸는 @def)·공개 여부
  QUERIES["imports"]       @path — import 대상. MODULE_RULE 이 레포 안 모듈 키로 바꾼다
  QUERIES["top_symbols"]   @name — 모듈 최상위 이름
  MODULE_RULE go_package   디렉토리가 패키지, go.mod 의 module 접두가 붙은 import 가 레포 내부
  PUBLIC_RULE capitalized  대문자 시작이 공개 · underscore  `_` 접두가 비공개

`tree_sitter` 와 문법 패키지(`tree_sitter_<SYNTAX>`)는 선택 의존이다. import 는 이 모듈에서만, 그것도
필요한 시점에만 한다. 그래서 커널이 설치를 요구하는 의존성은 여전히 0개다. 없으면 `build` 가 사유를 돌려주고 러너는
그 게이트를 [TOOL] 로 찍는다. py-tree-sitter 0.23 이상을 기준으로 하고, 0.25 의 QueryCursor 도 받는다.

타입 누락(`missing_types`)은 여기서 내지 않는다 — tree-sitter 를 쓰는 언어는 대개 타입을 강제하고,
그렇지 않은 언어는 팩이 NOT_APPLICABLE 로 선언한다.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from pathlib import Path

from kernel import facts, lang

MISSING = "tree-sitter 미설치 — 초기 설정의 스택 맞춤에서 설치"
_GO_MODULE = re.compile(r"^\s*module\s+(\S+)", re.M)


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


def _go_module_path(root: Path) -> str | None:
    """go.mod 의 module 선언. 없으면 레포 내부 import 를 가를 수 없어 전부 외부로 본다."""
    path = root / "go.mod"
    if not path.is_file():
        return None
    match = _GO_MODULE.search(path.read_text(encoding="utf-8-sig"))
    return match.group(1).strip('"') if match else None


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
        return None, f"tree-sitter-{syntax} 문법 미설치 — 초기 설정의 스택 맞춤에서 설치"
    queries = dict(pack.get("QUERIES") or {})   # type: ignore[call-overload]  # lang.load 가 매핑임을 검증했다
    try:
        language = ts.Language(grammar)
        compiled = {kind: _compile(ts, language, str(source)) for kind, source in queries.items()}
    except Exception as exc:     # 어떤 예외형이든 팩 결함이다 — 설치하라고 안내하면 안 된다
        return None, f"언어팩 {syntax} QUERIES 컴파일 실패: {type(exc).__name__}: {exc}"
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
        self._module_rule = pack.get("MODULE_RULE")
        self._public_rule = pack.get("PUBLIC_RULE")
        self._go_module = _go_module_path(root) if self._module_rule == "go_package" else None

    def _root_key(self) -> str:
        return self._go_module.rsplit("/", 1)[-1] if self._go_module else "main"

    def module_key(self, rel: str) -> str:
        if self._module_rule == "go_package":
            directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
            return directory.replace("/", ".") if directory else self._root_key()
        return rel.rsplit(".", 1)[0].replace("/", ".")      # 규칙을 선언하지 않았으면 경로가 곧 키다

    def _resolve_import(self, raw: str) -> tuple[str | None, str | None]:
        """(레포 안 모듈 키, 외부 이름). go.mod 접두가 붙은 것만 내부다."""
        if self._module_rule == "go_package" and self._go_module:
            if raw == self._go_module:
                return self._root_key(), None
            if raw.startswith(self._go_module + "/"):
                return raw[len(self._go_module) + 1:].replace("/", "."), None
        return None, raw

    def _public(self, name: str) -> bool:
        if self._public_rule == "capitalized":
            return name[:1].isupper()
        if self._public_rule == "underscore":
            return not name.startswith("_")
        return True

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
                                        self._public(name), None))
        return tuple(found)

    def _imports(self, root_node, source: bytes) -> tuple[facts.Import, ...]:
        found: list[facts.Import] = []
        for match in _matches(self._ts, self._queries["imports"], root_node):
            for node in match.get("path", []):
                module, external = self._resolve_import(_text(node, source).strip('"`'))
                found.append(facts.Import(module, external, None, node.start_point[0] + 1))
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
            return facts.FileFacts(rel, module, error="구문 오류 — tree-sitter 가 ERROR 노드를 냈다")
        return facts.FileFacts(
            rel=rel, module=module,
            functions=self._functions(root_node, source) if "functions" in self._queries else (),
            imports=self._imports(root_node, source) if "imports" in self._queries else (),
            top_symbols=self._top_symbols(root_node, source) if "top_symbols" in self._queries else frozenset(),
        )
