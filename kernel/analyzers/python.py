"""kernel/analyzers/python.py — 표준 `ast` → FileFacts.

게이트 셋(closures·func_limit·type_hints)과 컴포넌트 의존 검사가 각자 `ast` 를 걷던 것을 여기
한 곳으로 모았다. 판정은 옮기지 않았다 — 그쪽은 여전히 게이트다. 여기 있는 것은 "무엇이 있나"뿐이다.

Python 의미론에만 있는 것(속성 경유 참조·동적 import·호출 이름·ast 자체)은 `extra` 로 나간다.
다른 언어의 분석기는 그 절을 내지 않고, 소비하는 게이트는 없으면 건너뛴다.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

from kernel import facts

KINDS = frozenset({"functions", "nesting", "types", "imports", "top_symbols", "python"})


def module_key(rel: str) -> str:
    """점 표기 모듈 키. `__init__` 은 패키지 자신이다."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef, parent: str | None) -> facts.Function:
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    missing = tuple(a.arg for a in args if a.arg not in ("self", "cls") and a.annotation is None)
    return facts.Function(
        name=node.name, line=node.lineno, end_line=node.end_lineno or node.lineno, parent=parent,
        public=not node.name.startswith("_"), missing_types=missing, missing_return=node.returns is None,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        awaits=any(isinstance(sub, ast.Await) for sub in ast.walk(node)),
    )


def _functions(tree: ast.AST) -> tuple[facts.Function, ...]:
    """`ast.walk` 와 같은 너비 우선 순서 — 게이트 출력 순서가 그 순서에 묶여 있다. 감싸는 함수를 함께 나른다."""
    found: list[facts.Function] = []
    queue: deque[tuple[ast.AST, str | None]] = deque([(tree, None)])
    while queue:
        node, parent = queue.popleft()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(_function(node, parent))
            parent = node.name
        queue.extend((child, parent) for child in ast.iter_child_nodes(node))
    return tuple(found)


def _imports(tree: ast.AST, module: str, is_package: bool) -> tuple[list[tuple[str, str | None, int]], dict[str, str]]:
    """(대상, 심볼, 줄) 과 별칭표. 상대 import 는 이 파일의 모듈 키로 푼다."""
    imports: list[tuple[str, str | None, int]] = []
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, None, node.lineno))
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            prefix = module.split(".") if is_package else module.split(".")[:-1]
            if node.level:
                prefix = prefix[:len(prefix) - node.level + 1]
                target = ".".join(prefix + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            for alias in node.names:
                imports.append((target, alias.name, node.lineno))
                aliases[alias.asname or alias.name] = target + "." + alias.name
    return imports, aliases


def _attribute(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _attribute(node.value, aliases) + "." + node.attr
    return ""


def _top_symbols(tree: ast.Module) -> frozenset[str]:
    """모듈 최상위에서 이름이 되는 것 — 정의·import 별칭·대입. 공개 계약의 심볼 실존 근거다."""
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            symbols.update(target.id for target in targets if isinstance(target, ast.Name))
    return frozenset(symbols)


def _references(tree: ast.AST, aliases: dict[str, str]) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
    """(속성 경유 참조, 호출 이름) — 별칭을 푼 점 표기와 줄. Python 전용이라 extra 로 나간다."""
    attributes: list[tuple[str, int]] = []
    calls: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attributes.append((_attribute(node, aliases), node.lineno))
        if isinstance(node, ast.Call):
            calls.append((_attribute(node.func, aliases), node.lineno))
    return tuple(attributes), tuple(calls)


class PythonAnalyzer:
    label = "Python"
    kinds = KINDS
    suffixes = (".py",)

    def module_key(self, rel: str) -> str:
        return module_key(rel)

    def analyze(self, text: str, rel: str) -> facts.FileFacts:
        module = module_key(rel)
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError) as exc:     # ValueError — 널 바이트가 든 소스
            return facts.FileFacts(rel, module, error=str(exc))
        imports, aliases = _imports(tree, module, rel.endswith("/__init__.py"))
        attributes, calls = _references(tree, aliases)
        return facts.FileFacts(
            rel=rel, module=module, functions=_functions(tree),
            imports=tuple(facts.Import(target, None, symbol, line) for target, symbol, line in imports),
            top_symbols=_top_symbols(tree),
            extra={"tree": tree, "attributes": attributes, "calls": calls},
        )
