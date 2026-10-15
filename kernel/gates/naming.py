"""kernel/gates/naming.py — 이름 일관성: 함수 표기, 같은 대상의 읽기 동사, 응답 키 표기, 화면 API 타입 표기.

표기는 언어팩 `NAMING` 위에 프로파일 `NAMING` 이 덮은 `profile.NAMING` 이 정한다. 함수 이름은 구문 사실(`kernel/facts.py`)에서
읽으므로 언어마다 다른 코드가 없다.

  함수 표기       구문 사실의 함수 이름 ↔ NAMING["function"]          Python 의 `getCustomerEmail`
  읽기 동사       같은 디렉터리에서 get·fetch·load·retrieve·read·obtain 뒤의 대상이 같은 함수들
  응답 키         서버 소스의 따옴표 키 ↔ NAMING["keys"]               snake 프로젝트의 `{"customerId": …}`
  화면 API 타입   API 타입 파일의 속성 ↔ NAMING["ui_keys"](기본은 keys), 그리고 한 타입 안에 두 표기가 섞인 것

`find`·`query`·`search` 는 동사 묶음에서 뺀다 — 없을 수 있음·여러 개라는 다른 뜻이다. 강제하는 것은 고정 접두가 아니라
같은 대상에 같은 동사다. 외부 API 가 다른 표기를 요구하면 그 줄에 `key-ok: 사유`, 함수 이름은 `name-ok: 사유` 를 단다.
필드 집합은 맞대지 않는다(`dev/REJECTED.md` 「API 응답 스키마 ↔ 프론트 타입 필드 대조」 보류) — 표기법만 본다.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from kernel import facts, profile
from kernel.context import READ_ENC, _rel
from kernel.gates.api_types import _api_type_files
from kernel.gates.tests_pairing import is_test_path

KEY_ESCAPE = "key-ok"
NAME_ESCAPE = "name-ok"
READ_VERBS = ("get", "fetch", "load", "retrieve", "read", "obtain")

_HUMP = re.compile(r"[a-z0-9][A-Z]")
_JOIN = re.compile(r"[a-z0-9]_[A-Za-z0-9]")
_VERB = re.compile(rf"^_*({'|'.join(READ_VERBS)})(?:_([A-Za-z]\w*)|([A-Z]\w*))$")
_QUOTED_KEY = re.compile(r"""(?:^\s*|[{,]\s*)(["'])([A-Za-z_][A-Za-z0-9_]*)\1\s*:""", re.M)
_TS_DECL = re.compile(r"\b(?:interface\s+([A-Za-z_$][\w$]*)[^{=;]*|type\s+([A-Za-z_$][\w$]*)[^{=;]*=\s*)\{")
_TS_PROP = re.compile(r"""(?:^|[;,{])\s*(?:readonly\s+)?(["']?)([A-Za-z_$][\w$]*)\1\??\s*:""", re.M)
_NESTED = re.compile(r"\{[^{}]*\}")


def style_ok(name: str, styles: str) -> bool:
    """`styles`(`snake|camel` 처럼 `|` 로 이은 표기) 중 하나에 맞는가. 앞뒤 밑줄은 보지 않는다.

    snake 는 첫 마디에 혹(`aB`)이 없으면 맞다 — `visit_FunctionDef` 처럼 프레임워크가 정한 뒷마디는 건드리지 않는다.
    camel·pascal 은 낱말 사이 밑줄(`a_b`)이 없으면 맞다. 상수(`MAX_SIZE`)는 어느 쪽도 위반이 아니다.
    """
    core = name.strip("_")
    for style in styles.split("|"):
        if not core:
            return True
        if style == "snake" and not _HUMP.search(core.split("_", 1)[0]):
            return True
        if style in ("camel", "pascal") and not _JOIN.search(core) and not (style == "pascal" and core[0].islower()):
            return True
    return False


def _server_files(files: list[Path]) -> list[tuple[Path, str, list[str]]]:
    scratch = profile.scratch()
    out: list[tuple[Path, str, list[str]]] = []
    for path in files:
        rel = _rel(path)
        if is_test_path(rel) or (scratch and rel.startswith(scratch)):
            continue
        try:
            out.append((path, rel, path.read_text(encoding=READ_ENC).splitlines()))
        except OSError:
            continue
    return out


def _function_names(sources: list[tuple[Path, str, list[str]]]) -> list[tuple[str, int, str]]:
    """(경로, 줄, 이름) — 구문 사실의 함수 전부. 이름 탈출 주석을 단 줄은 뺀다."""
    found: list[tuple[str, int, str]] = []
    for path, rel, lines in sources:
        known = facts.facts_for(path, rel)
        if known is None or known.error:
            continue
        found += [(rel, fn.line, fn.name) for fn in known.functions
                  if not (0 < fn.line <= len(lines) and NAME_ESCAPE in lines[fn.line - 1])]
    return found


def _python_params(sources: list[tuple[Path, str, list[str]]]) -> list[tuple[str, int, str]]:
    """(경로, 줄, 이름) — Python 함수의 매개변수. 구문 사실이 이미 파싱해 둔 트리를 다시 쓴다. 다른 언어는 비어 있다."""
    if profile.SYNTAX != "python":
        return []
    found: list[tuple[str, int, str]] = []
    for path, rel, lines in sources:
        known = facts.facts_for(path, rel)
        tree = known.extra.get("tree") if known is not None and not known.error else None
        if not isinstance(tree, ast.AST):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.arg not in ("self", "cls") \
                    and not (0 < node.lineno <= len(lines) and NAME_ESCAPE in lines[node.lineno - 1]):
                found.append((rel, node.lineno, node.arg))
    return found


def _check_function_style(names: list[tuple[str, int, str]], styles: str) -> list[str]:
    return [f"{rel}:{line}: function {name} is not {styles.replace('|', ' or ')} case — rename it to the "
            f"project style (if a framework fixes the name, `{NAME_ESCAPE}: reason` on that line)"
            for rel, line, name in names if not style_ok(name, styles)]


def _check_read_verbs(names: list[tuple[str, int, str]]) -> list[str]:
    """같은 디렉터리·같은 대상에 읽기 동사가 둘 이상이면, 그 자리에서 많이 쓴 동사 밖의 함수가 위반이다.
    동률이면 레포 전체에서 많이 쓴 동사가 이긴다 — 새로 들어온 동사가 기존 관례를 위반으로 몰지 않게."""
    groups: dict[tuple[str, str], list[tuple[str, int, str, str]]] = defaultdict(list)
    for rel, line, name in names:
        match = _VERB.match(name)
        if match:
            subject = (match.group(2) or match.group(3)).replace("_", "").lower()
            groups[(rel.rsplit("/", 1)[0] if "/" in rel else "", subject)].append((rel, line, name, match.group(1)))
    overall = [member[3] for members in groups.values() for member in members]
    bad: list[str] = []
    for (_folder, _subject), members in groups.items():
        verbs = [verb for *_head, verb in sorted(members)]
        if len(set(verbs)) < 2:
            continue
        major = max(dict.fromkeys(verbs), key=lambda verb: (verbs.count(verb), overall.count(verb)))
        anchor = next(m for m in sorted(members) if m[3] == major)
        bad += [f"{rel}:{line}: {name} reads the same thing as {anchor[2]} ({anchor[0]}) with another verb "
                f"'{verb}' — use '{major}' for both (if they mean different things, `{NAME_ESCAPE}: reason`)"
                for rel, line, name, verb in sorted(members) if verb != major]
    return bad


def _server_keys(path: Path, rel: str, lines: list[str]) -> list[tuple[int, str]]:
    """(줄, 키) — 서버 소스의 따옴표 키. Python 은 구문 사실의 ast 로 dict 리터럴 키만 본다(독스트링 속 JSON 예시 제외)."""
    known = facts.facts_for(path, rel) if profile.SYNTAX == "python" else None
    tree = known.extra.get("tree") if known is not None and not known.error else None
    if isinstance(tree, ast.AST):
        return [(key.lineno, key.value) for node in ast.walk(tree) if isinstance(node, ast.Dict)
                for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
                and key.value.isidentifier()]
    comment = profile.pattern("comment") or "//"
    return [(number, match.group(2)) for number, line in enumerate(lines, 1)
            if not line.lstrip().startswith(comment) for match in _QUOTED_KEY.finditer(line)]


def _check_keys(sources: list[tuple[Path, str, list[str]]], styles: str) -> list[str]:
    bad: list[str] = []
    for path, rel, lines in sources:
        for number, key in _server_keys(path, rel, lines):
            if style_ok(key, styles) or (0 < number <= len(lines) and KEY_ESCAPE in lines[number - 1]):
                continue
            bad.append(f"{rel}:{number}: response key '{key}' is not {styles.replace('|', ' or ')} case — "
                       f"keep one key style across the API (if an outside API needs it, `{KEY_ESCAPE}: reason`)")
    return bad


def _ts_decls(text: str) -> list[tuple[int, str, list[str]]]:
    """(줄, 타입 이름, 최상위 속성 이름) — interface·type 리터럴. 안쪽 중괄호는 지우고 본다."""
    found: list[tuple[int, str, list[str]]] = []
    for match in _TS_DECL.finditer(text):
        depth, end = 0, match.end() - 1
        for end in range(match.end() - 1, len(text)):
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            if depth == 0:
                break
        body = text[match.end():end]
        while _NESTED.search(body):
            body = _NESTED.sub(" ", body)
        props = [prop.group(2) for prop in _TS_PROP.finditer(body)]
        found.append((text.count("\n", 0, match.start()) + 1, match.group(1) or match.group(2), props))
    return found


def _check_ui_types(ui_files: list[Path], styles: str | None) -> list[str]:
    """API 타입 파일의 속성은 `styles` 로, 그 밖의 화면 타입은 한 타입 안에 snake·camel 이 섞였는지만 본다."""
    typed = set(_api_type_files(ui_files)) if styles else set()
    bad: list[str] = []
    for path in ui_files:
        rel = _rel(path)
        if is_test_path(rel):
            continue
        text = path.read_text(encoding=READ_ENC)
        lines = text.splitlines()
        for line, name, props in _ts_decls(text):
            if 0 < line <= len(lines) and KEY_ESCAPE in lines[line - 1]:
                continue
            if styles and path in typed:
                off = [prop for prop in props if not style_ok(prop, styles)]
                if off:
                    bad.append(f"{rel}:{line}: {name} fields {', '.join(off)} are not {styles.replace('|', ' or ')} "
                               f"case — API types use the same key style as the server")
                continue
            snake = [prop for prop in props if not style_ok(prop, "camel")]
            camel = [prop for prop in props if not style_ok(prop, "snake")]
            if snake and camel:
                bad.append(f"{rel}:{line}: {name} mixes snake_case ({', '.join(snake)}) and camelCase "
                           f"({', '.join(camel)}) fields — one type uses one key style")
    return bad


def check_naming(files: list[Path], ui_files: list[Path]) -> list[str]:
    """서버 소스와 화면 API 타입 파일의 이름 일관성 위반."""
    naming = profile.NAMING
    sources = _server_files(files)
    names = _function_names(sources)
    bad = _check_function_style(names, naming["function"]) if naming.get("function") else []
    if naming.get("function"):
        bad += [line.replace("function ", "parameter ", 1)
                for line in _check_function_style(_python_params(sources), naming["function"])]
    bad += _check_read_verbs(names)
    if naming.get("keys"):
        bad += _check_keys(sources, naming["keys"])
    return bad + _check_ui_types(ui_files, naming.get("ui_keys") or naming.get("keys"))
