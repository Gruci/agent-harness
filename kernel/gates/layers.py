"""Technical environment, route and TLS checks scoped by CHECK_PATHS."""

from __future__ import annotations
import ast
import re
from pathlib import Path
from kernel import profile
from kernel.context import READ_ENC, _rel


def _under(rel: str, layer_name: str) -> bool:
    prefix = profile.layer(layer_name)
    return bool(prefix) and rel.startswith(prefix)


def _parse(f: Path) -> ast.AST | None:
    try:
        return ast.parse(f.read_text(encoding=READ_ENC))
    except SyntaxError:
        return None


def check_env_access(py_files: list[Path]) -> list[str]:
    """설정 모듈 밖에서 환경변수를 읽는 것. 읽는 방법은 언어마다 다르므로 패턴은 언어팩이 준다."""
    settings = profile.FILES.get("settings")
    pattern = profile.pattern("env_read")
    if not settings or not pattern:
        return []
    env_re = re.compile(pattern)
    comment = profile.pattern("comment") or "#"
    allow = tuple(profile.ALLOWLIST["env_access"])
    tests = profile.layer("tests")
    exempt = profile.scratch() + ((tests,) if tests else ())
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if rel == settings or rel.startswith(exempt) or rel in allow:
            continue
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(comment):
                continue
            if env_re.search(line):
                bad.append(f"{rel}:{i}: environment variable read outside {settings} — {stripped[:60]}")
    return bad


def _async_has_await(node: ast.AsyncFunctionDef) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return True
    return False


def _is_async_generator(node: ast.AsyncFunctionDef) -> bool:
    for sub in ast.walk(node):
        # 중첩 함수 내부 yield 는 제외 — 이 함수 자신 스코프의 yield 만
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not node:
            continue
        if isinstance(sub, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def _returns_stream(node: ast.AsyncFunctionDef, stream_returns: tuple[str, ...]) -> bool:
    """반환 타입 이름이 서버팩의 스트림 타입으로 끝나는가. 스트림 응답은 await 없이도 정상이다."""
    ann = node.returns
    name = ""
    if isinstance(ann, ast.Name):
        name = ann.id
    elif isinstance(ann, ast.Attribute):
        name = ann.attr
    return bool(stream_returns) and name.endswith(stream_returns)


def check_web_async_no_await(py_files: list[Path]) -> list[str]:
    """await 없는 async 핸들러. 판정 방식(`ASYNC_HANDLER`)과 스트림 타입은 서버 프레임워크팩이 선언한다. 러너가 선언 없는 팩을 먼저 거른다."""
    server = profile.SERVER
    if server is None or server["ASYNC_HANDLER"] is None:
        return []
    stream_returns = tuple(server["STREAM_RETURNS"])
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if not _under(rel, "routes"):
            continue
        tree = _parse(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if _async_has_await(node) or _is_async_generator(node) or _returns_stream(node, stream_returns):
                continue
            bad.append(f"{rel}:{node.lineno}: async def '{node.name}' has no await — make it a plain def")
    return bad


def check_ssl_bypass_location(py_files: list[Path]) -> list[str]:
    """전역 SSL 패치는 명시한 스크립트 진입점에서만 호출한다. 항상 import 되는 모듈에서 켜면 프로세스 전체로 퍼진다."""
    bypass = profile.symbol("ssl_bypass")
    if not bypass:
        return []
    call_re = re.compile(rf"\b{re.escape(bypass)}\s*\(")
    home = profile.FILES.get("ssl_util")
    allowed = profile.scratch()
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if rel.startswith(allowed) or rel == home:
            continue
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if call_re.search(line):
                bad.append(f"{rel}:{i}: global SSL patch called outside an entry point — {stripped[:50]}")
    return bad


def check_routes_error_response(py_files: list[Path]) -> list[str]:
    """에러는 예외로 올린다. 성공 응답용 래퍼(상태코드 없음·2xx)는 위반이 아니다. 상태를 싣는 키워드 이름은 서버 프레임워크팩이 선언한다."""
    wrapper = profile.symbol("error_response")
    server = profile.SERVER
    if not wrapper or server is None or not server["ERROR_STATUS_KWARG"]:
        return []
    status_kwarg = server["ERROR_STATUS_KWARG"]
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if not _under(rel, "routes"):
            continue
        tree = _parse(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != wrapper:
                continue
            for kw in node.value.keywords:
                if kw.arg == status_kwarg and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, int) and kw.value.value >= 400:
                    bad.append(f"{rel}:{node.lineno}: error returned as {wrapper}(status "
                               f"{kw.value.value}) — raise an exception instead")
    return bad
