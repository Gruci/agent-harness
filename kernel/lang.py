"""kernel/lang.py — 언어팩 로더.

언어 하나를 늘리는 비용을 **데이터 파일 하나**로 만드는 것이 이 모듈의 목적이다.
커널에는 언어별 파서가 없다. 언어별로 다른 것은 전부 선언이다.

  EXT              이 언어의 소스 확장자
  SYNTAX           구문 이름 — 컴포넌트 그래프의 technology.syntax 와 같은 값
  PATTERNS         관용구 정규식 — 환경변수 읽기·임의 타입·주석 접두 등
  NOT_APPLICABLE   이 언어에서는 규칙 자체가 성립하지 않는 게이트와 그 사유
  LINTERS          이 언어의 표준 도구. 우리가 다시 만들지 않고 위임한다
  QUERIES          tree-sitter 쿼리 — functions(@def·@name)·imports(@path)·top_symbols(@name).
                   Python 은 표준 ast 라 없다. 실행은 kernel/analyzers/treesitter.py
  MODULE_RULE      파일·import 를 모듈 키로 바꾸는 규칙 이름 — MODULE_RULES 중 하나
  PUBLIC_RULE      공개 이름 판정 — PUBLIC_RULES 중 하나
  FIXTURES         적합성 검사용 최소 예제 — 서식은 kernel/pack_check.py 헤더
  ANALYZER         구문 사실을 만드는 분석기 — ANALYZERS 중 하나. 비우면 SYNTAX 로 추정한다
                   (python → 표준 ast, 그 밖에 QUERIES 가 있으면 tree-sitter)
  ANALYZER_CMD     ANALYZER="command" 일 때 실행할 명령. 파일 경로를 인자로 받아 FileFacts JSON 배열을
                   stdout 에 낸다 — 계약은 kernel/analyzers/command.py 헤더
  GRAMMAR          tree-sitter 문법 패키지 모듈 이름. 비우면 tree_sitter_<SYNTAX> 다
  REQUIRES         이 팩이 1급으로 돌기 위해 필요한 외부 도구 — {"name", "check"(확인 명령), "install"(설치 안내)}.
                   `harness_install.py --doctor` 가 확인 명령을 돌려 없는 것만 보고한다. 설치는 사용자가 결정한다

`NOT_APPLICABLE` 이 따로 있는 이유: "못 함"과 "해당 없음"은 다르다. Go 에 타입힌트
게이트가 안 도는 건 손실이 아니라 언어가 이미 보장하기 때문이고, 커넥션 블록 게이트가
안 도는 건 진짜 손실이다. 둘을 같은 `[SKIP]` 으로 뭉뚱그리면 무엇을 잃었는지 알 수 없다.

선언을 적었다는 것만으로 1급 팩(사실 기반 게이트가 실제로 동작함이 확인된 팩)이 되지는 않는다.
`python -X utf8 -m kernel.pack_check <이름>` 이 FIXTURES 예제로 사실 기반 게이트가 위반을 실제로 잡는지 판정한다.

실물은 `profiles/lang/<이름>.py` 이고, 프로파일의 `LANG` 이 어느 것을 쓸지 정한다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

from kernel.context import ROOT
from kernel.langs import python as _python

# 커널이 싣고 다니는 팩이 기본이고, 프로젝트가 같은 이름으로 덮어쓸 수 있다.
# 커널 쪽에 두는 이유: 언어팩은 프로젝트 설정이 아니라 **검사기가 그 언어를 이해하는 방법**이라
# 검사기와 함께 이동해야 한다. 프로파일만 있는 곳에 두면 검사기를 복사해도 안 따라온다.
SHIPPED_DIR = Path(__file__).resolve().parent / "langs"
PROJECT_DIR = "profiles/lang"

# 언어팩이 선언을 빠뜨렸을 때의 기본값. 관용구 패턴은 파이썬팩이 정본이다.
DEFAULTS: dict[str, Any] = {
    "EXT": ("*.py",),
    "SYNTAX": "python",
    "PATTERNS": _python.PATTERNS,
    "NOT_APPLICABLE": {},
    "LINTERS": (),
    "QUERIES": {},
    "MODULE_RULE": None,
    "PUBLIC_RULE": None,
    "FIXTURES": {},
    "ANALYZER": None,
    "ANALYZER_CMD": (),
    "GRAMMAR": None,
    "REQUIRES": (),
}
_PACK_KEYS = ("EXT", "SYNTAX", "NOT_APPLICABLE", "LINTERS", "QUERIES", "MODULE_RULE", "PUBLIC_RULE", "FIXTURES",
              "ANALYZER", "ANALYZER_CMD", "GRAMMAR", "REQUIRES")

# 분석기(kernel/analyzers/treesitter.py)가 구현한 규칙 이름. 팩은 이 중 하나만 고른다.
MODULE_RULES = ("go_package",)
PUBLIC_RULES = ("capitalized", "underscore")
# kernel/analyzers/ 에 실물이 있는 분석기. 팩은 이 중 하나를 고르거나 비워서 추정에 맡긴다.
ANALYZERS = ("python", "treesitter", "command")
_REQUIRE_KEYS = ("name", "check", "install")


def unselected() -> dict[str, Any]:
    """LANG 을 선언하지 않은 상태 — 확장자도 구문도 비어 있다. 하네스가 파이썬으로 쓰였다고 제품 언어도 파이썬이라 짐작하지 않는다."""
    return {"EXT": (), "SYNTAX": None, "PATTERNS": {}, "NOT_APPLICABLE": {}, "LINTERS": (),
            "QUERIES": {}, "MODULE_RULE": None, "PUBLIC_RULE": None, "FIXTURES": {},
            "ANALYZER": None, "ANALYZER_CMD": (), "GRAMMAR": None, "REQUIRES": ()}


def analyzer_kind(pack: dict[str, Any]) -> str | None:
    """이 팩이 쓸 분석기 이름. 선언이 없으면 SYNTAX 로 추정하고, 추정할 근거도 없으면 None(분석기 없음)이다."""
    declared = pack.get("ANALYZER")
    if declared:
        return str(declared)
    if pack.get("SYNTAX") == "python":
        return "python"
    return "treesitter" if pack.get("QUERIES") else None


def grammar_module(pack: dict[str, Any]) -> str | None:
    """tree-sitter 분석기가 import 할 문법 패키지. tree-sitter 를 안 쓰는 팩은 None 이다."""
    if analyzer_kind(pack) != "treesitter":
        return None
    return str(pack.get("GRAMMAR") or f"tree_sitter_{pack.get('SYNTAX')}")


def _is_str_seq(value: object) -> bool:
    return isinstance(value, (tuple, list)) and all(isinstance(item, str) and item for item in value)


def _check_analyzer(pack: dict[str, Any], name: str) -> None:
    """분석기 선언과 그 분석기가 필요로 하는 재료가 같이 있는지 본다. 선언만 있고 재료가 없으면 [TOOL] 이 아니라 팩 오류다."""
    kind = pack["ANALYZER"]
    if kind is not None and kind not in ANALYZERS:
        raise ValueError(f"language pack ANALYZER must be one of {' '.join(ANALYZERS)}: {name}")
    if kind == "python" and pack["SYNTAX"] != "python":
        raise ValueError(f"language pack ANALYZER='python' only works with SYNTAX='python': {name}")
    if kind == "treesitter" and not pack["QUERIES"]:
        raise ValueError(f"language pack ANALYZER='treesitter' needs QUERIES: {name}")
    if not _is_str_seq(pack["ANALYZER_CMD"]):
        raise ValueError(f"language pack ANALYZER_CMD must be a list of command strings: {name}")
    if kind == "command" and not pack["ANALYZER_CMD"]:
        raise ValueError(f"language pack ANALYZER='command' needs ANALYZER_CMD: {name}")
    grammar = pack["GRAMMAR"]
    if grammar is not None and (not isinstance(grammar, str) or not grammar):
        raise ValueError(f"language pack GRAMMAR must be a grammar package module name or None: {name}")
    if not valid_requires(pack["REQUIRES"]):
        raise ValueError(f"language pack REQUIRES must list mappings of name, check (command list), install: {name}")


def valid_requires(requires: object) -> bool:
    """REQUIRES 서식 — 언어팩과 프레임워크팩이 같이 쓴다."""
    return isinstance(requires, (tuple, list)) and all(
        isinstance(item, dict) and all(key in item for key in _REQUIRE_KEYS)
        and isinstance(item["name"], str) and item["name"] and _is_str_seq(item["check"]) and item["check"]
        and isinstance(item["install"], str) for item in requires)


def find_pack(kind: str, shipped: Path, project_dir: Path, name: str) -> Path | None:
    """팩 파일 경로. 같은 이름이면 프로젝트 쪽(`project_dir`)이 커널 쪽(`shipped`)보다 우선한다. 아키텍처팩 로더도 이 함수를 쓴다."""
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name):
        raise ValueError(f"invalid {kind} name: {name!r}")
    for candidate in (project_dir / f"{name}.py", shipped / f"{name}.py"):
        if candidate.is_file():
            return candidate
    return None


def list_packs(shipped: Path, project_dir: Path) -> list[str]:
    names: set[str] = set()
    for directory in (shipped, project_dir):
        if directory.is_dir():
            names |= {p.stem for p in directory.glob("*.py") if not p.stem.startswith("_")}
    return sorted(names)


def run_pack(kind: str, shipped: Path, project_dir: Path, name: str) -> ModuleType:
    """팩 파일을 실행한 모듈. 못 찾거나 실행이 실패하면 ValueError — 프로파일 오류로 보고된다."""
    path = find_pack(kind, shipped, project_dir, name)
    if path is None:
        raise ValueError(f"{kind} not found: {name}")
    spec = importlib.util.spec_from_file_location(f"_pack_{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot create a loader for {kind}: {name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError(f"{kind} load failed: {name}: {type(exc).__name__}") from exc
    return module


def available() -> list[str]:
    return list_packs(SHIPPED_DIR, ROOT / PROJECT_DIR)


def load(name: str | None) -> dict[str, Any]:
    """선언한 팩은 반드시 읽고 검증한다. 선언하지 않았을 때만 기본값을 쓴다."""
    pack = dict(DEFAULTS)
    pack["PATTERNS"] = dict(DEFAULTS["PATTERNS"])
    if name is None:
        return pack
    module = run_pack("language pack", SHIPPED_DIR, ROOT / PROJECT_DIR, name)
    for key in _PACK_KEYS:
        if hasattr(module, key):
            pack[key] = getattr(module, key)
    given = getattr(module, "PATTERNS", None)
    if given is not None and not isinstance(given, dict):
        raise ValueError(f"language pack PATTERNS must be a mapping: {name}")
    if given:
        pack["PATTERNS"].update(given)   # 선언한 것만 덮고 나머지는 기본값 유지
    if not isinstance(pack["NOT_APPLICABLE"], dict):
        raise ValueError(f"language pack NOT_APPLICABLE must be a mapping: {name}")
    if not isinstance(pack["EXT"], (tuple, list)) or not pack["EXT"] or not all(
            isinstance(item, str) and item for item in pack["EXT"]):
        raise ValueError(f"language pack EXT must be a list of source patterns: {name}")
    if not isinstance(pack["SYNTAX"], str) or not pack["SYNTAX"]:
        raise ValueError(f"language pack SYNTAX must be a name: {name}")
    if not isinstance(pack["LINTERS"], (tuple, list)) or not all(
            isinstance(item, dict) for item in pack["LINTERS"]):
        raise ValueError(f"language pack LINTERS must be a list of check declarations: {name}")
    if not isinstance(pack["QUERIES"], dict) or not all(
            isinstance(kind, str) and isinstance(source, str) and source for kind, source in pack["QUERIES"].items()):
        raise ValueError(f"language pack QUERIES must map fact kinds to query strings: {name}")
    if pack["MODULE_RULE"] is not None and pack["MODULE_RULE"] not in MODULE_RULES:
        raise ValueError(f"language pack MODULE_RULE must be one of {' '.join(MODULE_RULES)}: {name}")
    if pack["PUBLIC_RULE"] is not None and pack["PUBLIC_RULE"] not in PUBLIC_RULES:
        raise ValueError(f"language pack PUBLIC_RULE must be one of {' '.join(PUBLIC_RULES)}: {name}")
    if not isinstance(pack["FIXTURES"], dict):
        raise ValueError(f"language pack FIXTURES must be a mapping: {name}")
    _check_analyzer(pack, name)
    return pack
