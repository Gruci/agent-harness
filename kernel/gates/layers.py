"""Technical environment, route and TLS checks scoped by CHECK_PATHS."""

from __future__ import annotations
import ast
import re
from pathlib import Path
from kernel import profile
from kernel.context import READ_ENC, _rel
from kernel.gates.core import COMMENT_MARKS


def _under(rel: str, layer_name: str) -> bool:
    prefix = profile.layer(layer_name)
    return bool(prefix) and rel.startswith(prefix)


def _parse(f: Path) -> ast.AST | None:
    try:
        return ast.parse(f.read_text(encoding=READ_ENC))
    except SyntaxError:
        return None


def _route_trees(py_files: list[Path]) -> list[tuple[str, ast.AST]]:
    """(경로, ast) — 라우트 레이어 아래에서 파싱되는 파일만."""
    found: list[tuple[str, ast.AST]] = []
    for f in py_files:
        rel = _rel(f)
        if not _under(rel, "routes"):
            continue
        tree = _parse(f)
        if tree is not None:
            found.append((rel, tree))
    return found


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
    for rel, tree in _route_trees(py_files):
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
            if stripped.startswith(COMMENT_MARKS):
                continue
            if call_re.search(line):
                bad.append(f"{rel}:{i}: global SSL patch called outside an entry point — {stripped[:50]}")
    return bad


def _call_name(value: ast.expr | None) -> str:
    if not isinstance(value, ast.Call):
        return ""
    func = value.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def _own_returns(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """이 함수 자신의 return — 안쪽 함수·람다·클래스의 return 은 그 함수의 것이다."""
    found: list[ast.Return] = []
    stack: list[ast.AST] = list(node.body)
    while stack:
        sub = stack.pop()
        if isinstance(sub, ast.Return):
            found.append(sub)
        if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(sub))
    return sorted(found, key=lambda ret: ret.lineno)


def _route_functions(tree: ast.AST, route_re: re.Pattern[str]) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """라우트 데코레이터가 붙은 함수. 데코레이터 판정은 서버팩의 `ROUTE_PATTERN` 이 한다 — 줄바꿈과 따옴표는 unparse 가 고른다."""
    return [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(route_re.search("@" + ast.unparse(dec)) for dec in node.decorator_list)]


_LITERALS = (ast.Dict, ast.List, ast.Tuple, ast.Set, ast.DictComp, ast.ListComp, ast.JoinedStr)


def _bypasses_wrapper(value: ast.expr | None, wrapper: str, exempt: tuple[str, ...]) -> bool:
    """래퍼를 확실히 건너뛴 값인가 — 리터럴 값, 또는 래퍼가 아닌 프레임워크 응답 클래스(`…Response`) 호출.
    다른 모듈의 함수 호출은 그 안에서 래퍼를 썼을 수 있어 보지 않는다(유스케이스를 돌려주는 라우트가 정상이다)."""
    if value is None or isinstance(value, ast.Constant) and value.value is None:
        return False
    name = _call_name(value)
    if name:
        return name != wrapper and name not in exempt and name.endswith("Response")
    return isinstance(value, _LITERALS) or isinstance(value, ast.Constant)


def _status(value: ast.expr, kwarg: str) -> int:
    """응답 호출이 싣는 상태 코드 — 숫자 리터럴이나 `status.HTTP_404_…` 이름. 모르면 0."""
    for kw in value.keywords if isinstance(value, ast.Call) and kwarg else ():
        if kw.arg != kwarg:
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return kw.value.value
        code = re.match(r"HTTP_(\d{3})", getattr(kw.value, "attr", ""))
        return int(code.group(1)) if code else 0
    return 0


def _assigned(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> list[ast.expr]:
    """함수 자신의 본문에서 그 이름에 대입한 값들 — `resp = JSONResponse(…); return resp` 를 따라간다."""
    found: list[ast.expr] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        sub = stack.pop()
        targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target] if isinstance(sub, ast.AnnAssign) else []
        if targets and sub.value is not None and any(isinstance(t, ast.Name) and t.id == name for t in targets):
            found.append(sub.value)
        if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(sub))
    return found


def _expand(value: ast.expr | None, func: ast.FunctionDef | ast.AsyncFunctionDef,
            helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef], wrapper: str) -> list[tuple[ast.expr | None, str]]:
    """반환값을 실제 응답 식으로 한 단계 푼다 — 지역 변수는 그 대입으로, 같은 파일의 도우미 호출은 도우미의 return 으로.
    (식, 경로 설명) 목록이다. 다른 모듈의 함수는 풀지 않는다."""
    if isinstance(value, ast.Name):
        return [(sub, f"{value.id} = ") for sub in _assigned(func, value.id)]
    helper = helpers.get(_call_name(value)) if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) else None
    if helper is None or helper is func or helper.name == wrapper:
        return [(value, "")]
    found: list[tuple[ast.expr | None, str]] = []
    for ret in _own_returns(helper):
        inner = _assigned(helper, ret.value.id) if isinstance(ret.value, ast.Name) else [ret.value]
        found += [(sub, f"{helper.name}(…), which returns ") for sub in inner]
    return found


def _describe(value: ast.expr | None) -> str:
    name = _call_name(value)
    return f"{name}(…)" if name else "a plain dict" if isinstance(value, ast.Dict) else "a bare value"


def _off_shape(rel: str, tree: ast.AST, wrapper: str, exempt: tuple[str, ...], route_re: re.Pattern[str],
               status_kwarg: str) -> list[str]:
    """라우트 함수가 응답 래퍼를 건너뛰고 리터럴이나 다른 응답 클래스를 돌려주는 return, 그리고 래퍼가 아닌 응답에
    4xx·5xx 를 실어 돌려주는 return. 래퍼를 직접 돌려주는 return 은 파일 전체 검사(`check_routes_error_response`)가 본다."""
    helpers = {node.name: node for node in getattr(tree, "body", ()) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    allowed = f" (streams, redirects and files: {', '.join(exempt)})" if exempt else ""
    bad: list[str] = []
    for node in _route_functions(tree, route_re):
        for ret in _own_returns(node):
            for value, via in _expand(ret.value, node, helpers, wrapper):
                where = f"{rel}:{ret.lineno}: route {node.name} returns {via}{_describe(value)}"
                status = _status(value, status_kwarg) if value is not None else 0
                if _bypasses_wrapper(value, wrapper, exempt):
                    bad.append(f"{where} — answer with {wrapper}(…) so every route has one response shape{allowed}")
                elif via.endswith("= ") and isinstance(value, ast.Call) and _call_name(value) == wrapper:
                    bad += [f"{where} — {problem}" for problem in _wrapper_misuse(value, wrapper, status_kwarg)]
                elif status >= 400 and _call_name(value) != wrapper:
                    bad.append(f"{where} with status {status} — raise an exception instead so every error has one shape")
    return bad


def _wrapper_misuse(call: ast.Call, wrapper: str, status_kwarg: str) -> list[str]:
    """응답 래퍼에 에러를 실은 것 — 4xx·5xx 상태, 또는 성공 봉투 안의 에러 본문."""
    found: list[str] = []
    status = _status(call, status_kwarg)
    if status >= 400:
        found.append(f"error returned as {wrapper}(status {status}) — raise an exception instead")
    if _error_body(call):
        found.append(f"error body returned through {wrapper}(…) — raise an exception instead so every error has one shape")
    return found


def check_routes_error_response(py_files: list[Path]) -> list[str]:
    """라우트 응답 모양. 라우트 함수는 응답 래퍼·None·서버팩 `RESPONSE_EXEMPT` 타입만 돌려준다 — `JSONResponse({"error":…})`·
    평범한 dict·봉투 생략이 여기 걸린다. 에러는 예외로 올린다 — 래퍼에 4xx 를 실은 반환도 위반이다(상태를 싣는 키워드
    이름은 서버팩의 `ERROR_STATUS_KWARG`). 성공 응답용 래퍼(상태코드 없음·2xx)는 위반이 아니다."""
    wrapper = profile.symbol("error_response")
    server = profile.SERVER
    if not wrapper or server is None:
        return []
    status_kwarg = server["ERROR_STATUS_KWARG"]
    route_re = re.compile(server["ROUTE_PATTERN"])
    exempt = tuple(server["RESPONSE_EXEMPT"])
    bad: list[str] = []
    for rel, tree in _route_trees(py_files):
        bad += _off_shape(rel, tree, wrapper, exempt, route_re, status_kwarg)
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) and _call_name(node.value) == wrapper:
                bad += [f"{rel}:{node.lineno}: {problem}" for problem in _wrapper_misuse(node.value, wrapper, status_kwarg)]
    return bad


def _error_body(call: ast.Call) -> bool:
    """성공 래퍼의 첫 인자가 에러를 담은 dict 리터럴인가 — `{"error": …}`, 또는 성공 깃발을 내린 `{"ok": False, …}`.
    상태 코드 없이 에러를 성공 봉투에 싣는 것이다."""
    payload = call.args[0] if call.args else None
    if not isinstance(payload, ast.Dict):
        return False
    pairs = [(key.value, value) for key, value in zip(payload.keys, payload.values) if isinstance(key, ast.Constant)]
    return any(key in ("error", "errors") or key in ("ok", "success") and isinstance(value, ast.Constant)
               and value.value is False for key, value in pairs)
