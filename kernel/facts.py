"""kernel/facts.py — 게이트가 읽는 언어 중립 구문 사실.

게이트는 `ast` 를 직접 보지 않는다. 파일 하나를 `FileFacts` 하나로 받고, 사실을 만드는 쪽은
분석기다. 언어별 차이는 분석기와 언어팩에만 있고 판정은 어느 언어에서든 같다.

  Python   kernel/analyzers/python.py     표준 `ast`. 설치 의존 0
  그 외    kernel/analyzers/treesitter.py 언어팩의 QUERIES 를 실행한다. `tree_sitter` 가 없으면 [TOOL]

사실 종류(kind)와 소비 게이트. 러너는 게이트마다 필요한 종류를 `unavailable()` 로 묻는다.

  functions    함수 범위            func_limit
  nesting      감싸는 함수          closures
  types        타입 누락            type_hints
  imports      import 대상          component_dependencies
  top_symbols  모듈 최상위 이름     component_dependencies (공개 계약)
  python       Python ast 자체      web_async · routes_error · undefined_const — 프레임워크·Python 고유 판정

판정 불능의 방향은 기존 그대로다. 분석기 없음·종류 미제공은 [TOOL](통과 아님)이고, 언어가
보장하는 것은 팩의 NOT_APPLICABLE 이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from kernel import profile
from kernel.context import READ_ENC, ROOT, _rel


@dataclass(frozen=True)
class Function:
    name: str
    line: int
    end_line: int
    parent: str | None                       # 감싸는 함수 이름 — 중첩 판정. 클래스는 감싸는 것으로 안 센다
    public: bool
    missing_types: tuple[str, ...] | None    # 타입 없는 파라미터. None = 언어가 타입을 강제(해당 없음)
    missing_return: bool = False
    is_async: bool = False
    awaits: bool = False


@dataclass(frozen=True)
class Import:
    module: str | None       # 분석기 모듈 키 표기의 import 대상. 분석기가 외부로 확정하면 None
    external: str | None     # 외부 패키지 이름 — 분석기가 확정한 경우만. Python 은 게이트가 소스 목록으로 가른다
    symbol: str | None       # `from m import s` 의 s. 모듈 통째 import 는 None
    line: int


@dataclass(frozen=True)
class FileFacts:
    rel: str
    module: str                              # 이 파일의 모듈 키 — 컴포넌트 public 계약과 같은 표기
    functions: tuple[Function, ...] = ()
    imports: tuple[Import, ...] = ()
    top_symbols: frozenset[str] = frozenset()
    error: str | None = None                 # 파싱·읽기 실패 사유. 있으면 나머지는 비어 있다
    extra: Mapping[str, object] = field(default_factory=dict)   # 분석기 전용 — Python 의 동적 import·속성 참조·ast


class Analyzer(Protocol):
    label: str                    # 메시지용 이름 — "Python" · "tree-sitter"
    kinds: frozenset[str]         # 이 분석기가 내는 사실 종류
    suffixes: tuple[str, ...]     # 볼 수 있는 확장자

    def module_key(self, rel: str) -> str: ...

    def analyze(self, text: str, rel: str) -> FileFacts: ...


def _no_analyzer(syntax: str | None) -> str:
    return f"{syntax or '미선언'} 구문 분석기가 없어 검사 못 함"


def query_kinds(queries: Mapping[str, object]) -> frozenset[str]:
    """QUERIES 키가 약속하는 사실 종류. functions 쿼리는 중첩(nesting)도 같이 낸다."""
    kinds: set[str] = set()
    for kind in queries:
        kinds |= {"functions", "nesting"} if kind == "functions" else {kind}
    return frozenset(kinds)


def _pack_kinds(pack: Mapping[str, object]) -> frozenset[str]:
    """분석기를 만들지 않고도 아는, 이 팩이 낼 수 있는 종류. 설치가 안 됐을 때 사유를 가르는 데 쓴다."""
    from kernel.analyzers import python as python_analyzer   # 순환 import 회피

    if pack.get("SYNTAX") == "python":
        return python_analyzer.KINDS
    queries = pack.get("QUERIES")
    return query_kinds(queries) if isinstance(queries, Mapping) else frozenset()


def analyzer_for_pack(pack: Mapping[str, object], root: Path) -> tuple[Analyzer | None, str]:
    """팩 하나의 (분석기, 못 쓰는 사유). 사유가 비면 쓸 수 있다. pack_check 가 프로파일과 무관하게 쓴다."""
    # 분석기가 이 모듈의 사실형을 쓰므로 여기서는 늦게 import 한다 — 순환 import 회피.
    from kernel.analyzers import python as python_analyzer, treesitter

    syntax = pack.get("SYNTAX")
    if syntax == "python":
        return python_analyzer.PythonAnalyzer(), ""
    if pack.get("QUERIES"):
        return treesitter.build(pack, root)
    return None, _no_analyzer(syntax if isinstance(syntax, str) else None)


_SELECTED: dict[str | None, tuple[Analyzer | None, str]] = {}


def select(syntax: str | None) -> tuple[Analyzer | None, str]:
    """이 구문의 (분석기, 못 쓰는 사유). Python 은 프로파일과 무관하게 항상 있고, 그 외는 프로파일이 고른 팩만이다."""
    if syntax not in _SELECTED:
        if syntax == "python":
            _SELECTED[syntax] = analyzer_for_pack({"SYNTAX": "python"}, ROOT)
        elif syntax is not None and syntax == profile.SYNTAX:
            _SELECTED[syntax] = analyzer_for_pack(profile.PACK, ROOT)
        else:
            _SELECTED[syntax] = (None, _no_analyzer(syntax))
    return _SELECTED[syntax]


def unavailable(kind: str) -> str:
    """프로파일의 언어에서 이 사실 종류를 못 받는 사유. 빈 문자열이면 받을 수 있다.

    종류 자체를 안 내는 언어(Python 전용 판정 등)는 설치 사유를 말하지 않는다 — tree-sitter 를
    깔아도 안 켜지는 검사에 설치하라고 안내하면 그 문구가 거짓이다.
    """
    analyzer, reason = select(profile.SYNTAX)
    kinds = analyzer.kinds if analyzer is not None else _pack_kinds(profile.PACK)
    if kind not in kinds:
        return _no_analyzer(profile.SYNTAX)
    return reason


def provides(kind: str) -> bool:
    return not unavailable(kind)


_CACHE: dict[tuple[str, int, int, int], FileFacts] = {}


def facts_for(path: Path, rel: str | None = None, analyzer: Analyzer | None = None) -> FileFacts | None:
    """파일 하나의 사실. 분석기가 없으면 None — 러너가 그 게이트를 [TOOL] 로 먼저 끊으므로 게이트는 건너뛰기만 한다.

    캐시 키는 경로·수정 시각·크기·분석기다. 게이트 셋이 같은 파일을 각각 파싱하던 것을 한 번으로 줄인다.
    읽기 실패는 예외가 아니라 `error` 다 — 검사기가 대상을 못 읽는 상태를 조용히 지나치지 않는다.
    """
    if analyzer is None:
        analyzer, _reason = select(profile.SYNTAX)
        if analyzer is None:
            return None
    where = _rel(path) if rel is None else rel
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, id(analyzer))
        if key in _CACHE:
            return _CACHE[key]
        text = path.read_text(encoding=READ_ENC)
    except (OSError, UnicodeError) as exc:
        return FileFacts(where, analyzer.module_key(where), error=str(exc))
    found = analyzer.analyze(text, where)
    _CACHE[key] = found
    return found
