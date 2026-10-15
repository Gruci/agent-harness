"""kernel/analyzers/regex.py — 설치 0개로 중괄호 언어의 구문 사실을 내는 엔진.

언어별 차이는 팩의 REGEX 와 규칙 이름뿐이다. 이 모듈은 어느 언어의 문법도 모른다. tree-sitter 를 깔 수 없는
환경의 기본 엔진이고, QUERIES 와 REGEX 를 함께 선언한 팩은 tree-sitter 가 없을 때 이 엔진으로 내려간다(kernel/facts.py).

  REGEX["functions"]    함수 머리. 이름 있는 그룹 중 처음 잡힌 것이 이름이다(대안마다 다른 그룹 이름)
  REGEX["imports"]      import 대상. `block` 그룹이 잡히면 그 안의 따옴표 문자열 전부가 경로다(Go `import ( … )`)
  REGEX["top_symbols"]  최상위 이름 — 중괄호 깊이 0 에서 잡힌 것만
  MODULE_RULE·PUBLIC_RULE 은 kernel/analyzers/modules.py

함수 머리와 중괄호는 주석·문자열을 공백으로 지운 본문에서 찾고, import 경로는 주석만 지운 원문에서 읽는다. 머리의 이름 뒤 첫 `(` 의
짝을 건너뛰고 `{` 를 찾는다. 그 전에 `;`·`}`·다음 머리가 오면 본문 없는 선언(인터페이스 메서드)이나 호출문이고,
`)` 와 `{` 사이에서 줄이 바뀐 뒤 다른 내용이 있으면 호출문 뒤의 다른 블록(`f(x)` 다음 줄의 `if (y) {`)이다.
범위 끝은 `{` 의 짝이다. 중괄호 짝이 안 맞는 파일은 error 사실이다 — 반쪽 범위로 판정하면 조용히 빠지는 위반이 생긴다.
"""

from __future__ import annotations

import bisect
import itertools
import re
from collections.abc import Mapping
from pathlib import Path

from kernel import facts
from kernel.analyzers.modules import ModuleRules, is_public

_MASK = re.compile(r'//[^\n]*|/\*.*?\*/|""".*?"""|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`', re.S)
_QUOTED = re.compile(r'"([^"\n]+)"|`([^`\n]+)`')
_STOP = re.compile(r"[{};]")


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def masked(text: str) -> str:
    """주석·문자열을 같은 길이의 공백으로 — 줄 번호와 위치가 그대로다. 함수 머리와 중괄호는 이 본문에서 찾는다."""
    return _MASK.sub(_blank, text)


def uncommented(text: str) -> str:
    """주석만 지운 원문 — import 경로(문자열)는 남기고 주석 속 `from "x"` 는 지운다."""
    return _MASK.sub(lambda match: _blank(match) if match.group().startswith(("//", "/*")) else match.group(), text)


def _capture(match: re.Match[str]) -> tuple[str, int, int]:
    """처음 잡힌 이름 그룹의 (값, 시작, 끝). 팩 정규식의 이름 그룹은 대안마다 다를 수 있다."""
    for group, value in match.groupdict().items():
        if value:
            return value, match.start(group), match.end(group)
    return "", match.start(), match.end()


def _pairs(body: str, opener: str, closer: str) -> tuple[dict[int, int], bool]:
    """여는 괄호 위치 → 짝인 닫는 괄호 위치, 그리고 짝이 전부 맞았는지."""
    pairs: dict[int, int] = {}
    stack: list[int] = []
    balanced = True
    for match in re.finditer(re.escape(opener) + "|" + re.escape(closer), body):
        if match.group() == opener:
            stack.append(match.start())
        elif stack:
            pairs[stack.pop()] = match.start()
        else:
            balanced = False
    return pairs, balanced and not stack


def build(pack: Mapping[str, object], root: Path, label: str = "regex") -> tuple["Engine | None", str]:
    """팩의 엔진. REGEX 가 없거나 컴파일되지 않으면 사유 — 설치 문제가 아니라 팩 결함이다."""
    patterns = pack.get("REGEX")
    if not isinstance(patterns, Mapping) or not patterns:
        return None, f"language pack {pack.get('SYNTAX')} declares no REGEX"
    try:
        compiled = {str(kind): re.compile(str(source), re.M) for kind, source in patterns.items()}
    except re.error as exc:
        return None, f"language pack {pack.get('SYNTAX')} REGEX failed to compile: {exc}"
    return Engine(pack, root, compiled, label), ""


class Lines:
    """위치 → 1부터 세는 줄 번호. 줄 시작 위치를 한 번 모아 두고 이분 탐색한다."""

    def __init__(self, text: str) -> None:
        self._starts = [0] + [match.end() for match in re.finditer("\n", text)]

    def __call__(self, position: int) -> int:
        return bisect.bisect_right(self._starts, position)


class Engine:
    def __init__(self, pack: Mapping[str, object], root: Path, patterns: dict[str, re.Pattern[str]], label: str) -> None:
        self.label = label
        self._patterns = patterns
        self.kinds = facts.query_kinds(patterns)
        self.syntax = str(pack["SYNTAX"])
        self.suffixes = tuple(str(pattern).lstrip("*") for pattern in pack["EXT"])   # type: ignore[union-attr]
        self._rules = ModuleRules(pack.get("MODULE_RULE"), root, self.suffixes)
        self._public_rule = pack.get("PUBLIC_RULE")

    def module_key(self, rel: str) -> str:
        return self._rules.module_key(rel)

    def _spans(self, body: str, braces: dict[int, int], parens: dict[int, int]) -> list[tuple[int, int, str]]:
        """(시작, 끝 중괄호 위치, 이름). 본문이 없는 머리는 뺀다 — 머리 정규식은 호출문도 잡기 때문이다."""
        heads = list(self._patterns["functions"].finditer(body))
        spans: list[tuple[int, int, str]] = []
        for index, head in enumerate(heads):
            name, _start, name_end = _capture(head)
            limit = heads[index + 1].start() if index + 1 < len(heads) else len(body)
            opening = body.find("(", name_end, limit)
            if not name or opening not in parens:
                continue
            close = parens[opening]
            stop = _STOP.search(body, close + 1, limit)
            if stop is None or stop.group() != "{" or "\n" in body[close + 1:stop.start()].rstrip():
                continue
            spans.append((head.start(), braces[stop.start()], name))
        return spans

    def _functions(self, body: str, line: Lines, braces: dict[int, int]) -> tuple[facts.Function, ...]:
        parens, _balanced = _pairs(body, "(", ")")
        # 시작 오름차순·같은 시작이면 바깥이 먼저 — 스택 맨 위가 나를 감싸는 가장 안쪽 함수다.
        spans = sorted(self._spans(body, braces, parens), key=lambda item: (item[0], -item[1]))
        stack: list[tuple[int, str]] = []
        found: list[facts.Function] = []
        for start, end, name in spans:
            while stack and stack[-1][0] < start:
                stack.pop()
            found.append(facts.Function(name, line(start), line(end), stack[-1][1] if stack else None,
                                        is_public(self._public_rule, name), None))
            stack.append((end, name))
        return tuple(found)

    def _imports(self, text: str, body: str, line: Lines, rel: str) -> tuple[facts.Import, ...]:
        found: list[facts.Import] = []
        code = uncommented(text)
        for match in self._patterns["imports"].finditer(code):
            keyword = match.start() + len(match.group()) - len(match.group().lstrip())
            if keyword >= len(body) or body[keyword] != code[keyword]:
                continue                                  # 문자열 안의 import 글자
            block = match.groupdict().get("block")
            if block is not None:
                paths = [(match.start("block") + quoted.start(), quoted.group(1) or quoted.group(2))
                         for quoted in _QUOTED.finditer(block)]
            else:
                raw, start, _end = _capture(match)
                paths = [(start, raw)] if raw else []
            for position, raw in paths:
                resolved = self._rules.resolve(raw, rel)
                if resolved is not None:
                    found.append(facts.Import(resolved[0], resolved[1], None, line(position)))
        return tuple(found)

    def _top_symbols(self, body: str, braces: dict[int, int]) -> frozenset[str]:
        marks = sorted([(start, 1) for start in braces] + [(end, -1) for end in braces.values()])
        positions = [position for position, _delta in marks]
        depths = list(itertools.accumulate(delta for _position, delta in marks))
        names: set[str] = set()
        for match in self._patterns["top_symbols"].finditer(body):
            name, start, _end = _capture(match)
            before = bisect.bisect_left(positions, start)
            if name and not (depths[before - 1] if before else 0):
                names.add(name)
        return frozenset(names)

    def analyze(self, text: str, rel: str) -> facts.FileFacts:
        module = self.module_key(rel)
        body = masked(text)
        braces, balanced = _pairs(body, "{", "}")
        if not balanced:
            return facts.FileFacts(rel, module, error="unbalanced braces — the regex analyzer cannot read this file")
        line = Lines(text)
        return facts.FileFacts(
            rel=rel, module=module,
            functions=self._functions(body, line, braces) if "functions" in self._patterns else (),
            imports=self._imports(text, body, line, rel) if "imports" in self._patterns else (),
            top_symbols=self._top_symbols(body, braces) if "top_symbols" in self._patterns else frozenset(),
        )
