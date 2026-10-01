"""kernel/analyzers/command.py — 외부 명령이 낸 JSON 을 검증해 FileFacts 로 바꾸는 분석기.

tree-sitter 를 못 쓰는 환경의 탈출구다. 언어팩이 `ANALYZER = "command"` 와 `ANALYZER_CMD` 를 선언하면
그 명령이 파일을 읽고 사실을 낸다. 명령은 그 언어 자신의 도구(go/ast·TS compiler API)로 짠 스크립트가
보통이고, 초기 설정의 스택 맞춤이 생성해 둔다. 이 모듈은 어느 언어도 모른다 — 계약을 검사할 뿐이다.

계약: `<ANALYZER_CMD...> <상대경로>` 를 프로젝트 루트에서 실행하면 stdout 에 JSON 배열이 온다. 원소 하나가 파일 하나다.

  [{"rel": "orders/a.go", "module": "orders",
    "functions": [{"name": "F", "line": 3, "end_line": 90, "parent": null, "public": true,
                   "missing_types": null, "missing_return": false, "is_async": false, "awaits": false}],
    "imports": [{"module": "db.reads", "external": null, "symbol": null, "line": 1}],
    "top_symbols": ["F"], "error": null}]

  module         이 파일의 모듈 키 — 컴포넌트 그래프의 public 계약과 같은 표기
  parent         감싸는 함수 이름. 없으면 null
  missing_types  타입 없는 파라미터 이름 목록. 언어가 타입을 강제하면 null (그 팩은 type_hints 를 NOT_APPLICABLE 로 둔다)
  imports.module 레포 안 모듈 키. 외부 패키지면 null 로 두고 external 에 이름을 적는다
  error          읽기·파싱 실패 사유. 있으면 나머지는 비어도 된다
  missing_return·is_async·awaits 는 생략하면 false 다.

모양이 계약과 다르면 그 파일은 `error` 사실이 된다 — 통과가 아니다. 명령 실행 파일이 없으면 `build` 가 사유를
돌려주고 러너는 그 게이트를 [TOOL] 로 찍는다. 실행 중 실패·시간 초과도 그 파일의 `error` 다.

디스크에 없는 소스(pack_check 의 예제)는 임시 디렉토리에 같은 상대경로로 쓰고, 팩 FIXTURES["files"] 에 적힌
보조 파일(go.mod 등)을 루트에서 함께 복사한 뒤 거기서 명령을 돌린다. 명령은 cwd 기준 상대경로만 믿으면 된다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from kernel import facts
from kernel.context import READ_ENC

TIMEOUT_SECONDS = 60
KINDS = frozenset({"functions", "nesting", "types", "imports", "top_symbols"})
_FUNCTION_KEYS = ("name", "line", "end_line", "parent", "public", "missing_types")
_IMPORT_KEYS = ("module", "external", "symbol", "line")


def _missing(command: str) -> str:
    return f"analyzer command {command} cannot run — create it in the initial stack setup"


def build(pack: Mapping[str, object], root: Path) -> tuple["Engine | None", str]:
    """팩의 엔진을 돌려주고, 명령을 실행할 수 없으면 그 사유를 돌려준다. 사유는 러너가 [TOOL] 로 찍는다."""
    command = tuple(str(part) for part in (pack.get("ANALYZER_CMD") or ()))   # type: ignore[call-overload]  # lang.load 가 목록임을 검증했다
    if not command:
        return None, "language pack declares no ANALYZER_CMD"
    if shutil.which(command[0]) is None and not (root / command[0]).is_file():
        return None, _missing(command[0])
    return Engine(command, pack, root), ""


def _optional_str(value: object, field: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{field} must be a string or null")


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be true/false")
    return value


def _function(item: object) -> facts.Function:
    if not isinstance(item, dict) or any(key not in item for key in _FUNCTION_KEYS):
        raise ValueError(f"functions items must be objects with {', '.join(_FUNCTION_KEYS)}")
    types = item["missing_types"]
    if types is not None and not (isinstance(types, list) and all(isinstance(name, str) for name in types)):
        raise ValueError("missing_types must be a list of names or null")
    name = item["name"]
    if not isinstance(name, str) or not name:
        raise ValueError("functions.name must be a name")
    return facts.Function(
        name=name, line=_int(item["line"], "functions.line"), end_line=_int(item["end_line"], "functions.end_line"),
        parent=_optional_str(item["parent"], "functions.parent"), public=_bool(item["public"], "functions.public"),
        missing_types=None if types is None else tuple(types),
        missing_return=_bool(item.get("missing_return", False), "functions.missing_return"),
        is_async=_bool(item.get("is_async", False), "functions.is_async"),
        awaits=_bool(item.get("awaits", False), "functions.awaits"),
    )


def _import(item: object) -> facts.Import:
    if not isinstance(item, dict) or any(key not in item for key in _IMPORT_KEYS):
        raise ValueError(f"imports items must be objects with {', '.join(_IMPORT_KEYS)}")
    return facts.Import(_optional_str(item["module"], "imports.module"), _optional_str(item["external"], "imports.external"),
                        _optional_str(item["symbol"], "imports.symbol"), _int(item["line"], "imports.line"))


def convert(entry: object, rel: str, fallback_module: str) -> facts.FileFacts:
    """JSON 원소 하나를 FileFacts 로. 계약 위반은 예외가 아니라 error 사실이다 — 검사기가 대상을 못 읽는 상태를 숨기지 않는다."""
    try:
        if not isinstance(entry, dict):
            raise ValueError("item is not an object")
        error = _optional_str(entry.get("error"), "error")
        module = entry.get("module")
        if not isinstance(module, str) or not module:
            raise ValueError("module must be a module key")
        if error:
            return facts.FileFacts(rel, module, error=error)
        symbols = entry.get("top_symbols")
        if not isinstance(symbols, list) or not all(isinstance(name, str) for name in symbols):
            raise ValueError("top_symbols must be a list of names")
        functions, imports = entry.get("functions"), entry.get("imports")
        if not isinstance(functions, list) or not isinstance(imports, list):
            raise ValueError("functions and imports must be lists")
        return facts.FileFacts(rel=rel, module=module, functions=tuple(_function(item) for item in functions),
                               imports=tuple(_import(item) for item in imports), top_symbols=frozenset(symbols))
    except ValueError as exc:
        return facts.FileFacts(rel, fallback_module, error=f"analyzer output breaks the contract: {exc}")


def _pick(payload: object, rel: str) -> object:
    """배열에서 이 파일의 원소. rel 이 일치하는 것이 우선이고, 하나뿐이면 그것이다."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("stdout is not a non-empty JSON array")
    for entry in payload:
        if isinstance(entry, dict) and entry.get("rel") == rel:
            return entry
    if len(payload) == 1:
        return payload[0]
    raise ValueError(f"no item for rel={rel}")


class Engine:
    label = "external analyzer"
    kinds = KINDS

    def __init__(self, command: tuple[str, ...], pack: Mapping[str, object], root: Path) -> None:
        self._command = command
        self._root = root
        self.suffixes = tuple(str(pattern).lstrip("*") for pattern in pack["EXT"])   # type: ignore[union-attr]
        fixtures = pack.get("FIXTURES") or {}
        self._support = tuple(str(name) for name in (fixtures.get("files") or {}))   # type: ignore[union-attr]

    def module_key(self, rel: str) -> str:
        """명령이 답하기 전(읽기 실패·계약 위반)에 쓰는 키 — 경로가 곧 키다."""
        return rel.rsplit(".", 1)[0].replace("/", ".")

    def _run(self, cwd: Path, rel: str) -> facts.FileFacts | str:
        """명령 한 번. 사실을 얻지 못하면 사유 문자열을 돌려준다."""
        try:
            done = subprocess.run([*self._command, rel], cwd=cwd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return f"analyzer command gave no answer within {TIMEOUT_SECONDS}s"
        except OSError as exc:
            return f"analyzer command failed to run {exc.__class__.__name__}"
        if done.returncode:
            return f"analyzer command exit code {done.returncode}: {(done.stderr or done.stdout).strip()[:300]}"
        try:
            entry = _pick(json.loads(done.stdout), rel)
        except ValueError as exc:
            return f"analyzer output breaks the contract: {exc}"
        return convert(entry, rel, self.module_key(rel))

    def _on_disk(self, rel: str, text: str) -> bool:
        target = self._root / rel
        try:
            return target.is_file() and target.read_text(encoding=READ_ENC) == text
        except (OSError, UnicodeError):
            return False

    def analyze(self, text: str, rel: str) -> facts.FileFacts:
        if self._on_disk(rel, text):
            found = self._run(self._root, rel)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                scratch = Path(tmp)
                for name in self._support:
                    source = self._root / name
                    if source.is_file():
                        (scratch / name).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, scratch / name)
                target = scratch / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                found = self._run(scratch, rel)
        if isinstance(found, str):
            return facts.FileFacts(rel, self.module_key(rel), error=found)
        return found
