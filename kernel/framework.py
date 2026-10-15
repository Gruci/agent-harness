"""kernel/framework.py — 프레임워크팩 로더.

언어팩(`kernel/lang.py`)·아키텍처팩(`kernel/arch.py`) 옆의 세 번째 팩 축이다. 웹·화면 게이트의
판정은 `kernel/gates/` 와 `kernel/eslint.harness.mjs` 에 한 벌뿐이고, 프레임워크마다 다른 것은
**선언**뿐이라 여기로 온다. 역할은 둘이고, 프로파일의 `FRAMEWORK` 가 역할별로 최대 하나씩 고른다.

  ROLE = "server"
    ROUTE_PATTERN        라우트 선언을 찾는 정규식. 그룹 1 이 경로다 — 소비 UI 없는 라우트(31)
    ASYNC_HANDLER        await 없는 async 핸들러(13)의 판정 방식. ASYNC_HANDLERS 중 하나. 없으면 그 프레임워크에서 성립하지 않음
    STREAM_RETURNS       await 없이도 정상인 스트림 반환 타입 이름 — 접미 일치
    ERROR_STATUS_KWARG   에러 상태를 실어 보내는 키워드 인자 — 라우트 에러 응답(16). 없으면 성립하지 않음
    RESPONSE_EXEMPT      응답 래퍼 대신 돌려줘도 되는 응답 타입 이름 — 스트림·리다이렉트·파일. 정확히 같은 이름만(16)
    PREFIX_PATTERN       라우트 파일의 라우터 접두 선언 정규식. 그룹 1 이 접두다 — 소비 UI 없는 라우트(31)가 경로 앞에 붙인다
    INFRA_ROUTES         화면이 소비하지 않는 기반 라우트(헬스체크·지표·문서) — 31 이 보지 않는다
  ROLE = "ui"
    UI_EXT               화면 소스 패턴. 프로파일 UI_EXT 의 기본값이다
    ESLINT_PARSER        화면 게이트 6종이 쓸 ESLint 파서 패키지
    PARSER_OPTIONS       그 파서에 넘길 parserOptions
    PARSERS              확장자 glob 마다 따로 쓸 파서 패키지 — 예: Svelte 팩의 `*.ts` 는 TS 파서
    ESLINT_INSTALL       실행 파일이 없을 때 안내할 설치 명령. 없으면 파서 이름으로 만든다
    LOGIC_EXT            행동 테스트 짝을 요구할 로직 파일 확장자(43). 비우면 그 검사는 [N/A]
    COMPONENT_EXT        렌더 테스트 짝을 요구할 컴포넌트 파일 확장자(44). 비우면 [N/A]
    ENTRY_MARKERS        이 문자열을 담은 파일은 앱 진입점이라 렌더 테스트 짝 대상이 아니다
    OWNED                한 모듈만 맡을 화면 기능 — 서식은 언어팩 OWNED 와 같다
  공통
    FIXTURES             적합성 검사 예제 — 서식은 kernel/pack_check.py 헤더
    REQUIRES             1급으로 돌기 위한 외부 도구 — 서식은 언어팩과 같다(kernel/lang.py 헤더). --doctor 가 보고한다

역할이 없는 게이트가 선택되지 않은 팩을 만나면 [SKIP](프레임워크팩 미선택)이고, 팩이 판정 방식을
선언하지 않으면 [N/A](이 프레임워크에서 성립하지 않음)다. 둘을 가르는 것이 이 축의 존재 이유다.

실물은 `kernel/frameworks/<이름>.py` 이고, 같은 이름을 `profiles/framework/<이름>.py` 에 두면 프로젝트 것이 이긴다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel.context import ROOT
from kernel.lang import find_pack, list_packs, run_pack, valid_patterns, valid_requires

SHIPPED_DIR = Path(__file__).resolve().parent / "frameworks"
PROJECT_DIR = "profiles/framework"
KIND = "framework pack"

ROLES = ("server", "ui")
# 게이트(kernel/gates/layers.py)가 구현한 판정 방식. 팩은 이 중 하나만 고른다.
ASYNC_HANDLERS = ("python_ast",)

_SERVER_DEFAULTS: dict[str, Any] = {
    "ROUTE_PATTERN": "", "ASYNC_HANDLER": None, "STREAM_RETURNS": (), "ERROR_STATUS_KWARG": None, "FIXTURES": {},
    "REQUIRES": (), "RESPONSE_EXEMPT": (), "PREFIX_PATTERN": "", "INFRA_ROUTES": (),
}
_UI_DEFAULTS: dict[str, Any] = {
    "UI_EXT": (), "ESLINT_PARSER": "", "PARSER_OPTIONS": {}, "ESLINT_INSTALL": "", "FIXTURES": {}, "REQUIRES": (),
    "PARSERS": {}, "LOGIC_EXT": (), "COMPONENT_EXT": (), "ENTRY_MARKERS": (), "OWNED": {},
}


def unselected() -> dict[str, dict[str, Any] | None]:
    """FRAMEWORK 를 선언하지 않은 상태 — 두 역할 다 비어 있다."""
    return {"server": None, "ui": None}


def available() -> list[str]:
    return list_packs(SHIPPED_DIR, ROOT / PROJECT_DIR)


def exists(name: str) -> bool:
    return find_pack(KIND, SHIPPED_DIR, ROOT / PROJECT_DIR, name) is not None


def _is_str_seq(value: object) -> bool:
    return isinstance(value, (tuple, list)) and all(isinstance(item, str) and item for item in value)


def _check_server(pack: dict[str, Any], name: str) -> None:
    pattern = pack["ROUTE_PATTERN"]
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"{KIND} ROUTE_PATTERN must be a regex string: {name}")
    try:
        groups = re.compile(pattern).groups
    except re.error as exc:
        raise ValueError(f"{KIND} ROUTE_PATTERN is not a valid regex: {name}: {exc}") from exc
    if groups < 1:
        raise ValueError(f"{KIND} ROUTE_PATTERN must capture the path in group 1: {name}")
    if pack["ASYNC_HANDLER"] is not None and pack["ASYNC_HANDLER"] not in ASYNC_HANDLERS:
        raise ValueError(f"{KIND} ASYNC_HANDLER must be one of {' '.join(ASYNC_HANDLERS)}: {name}")
    if not _is_str_seq(pack["STREAM_RETURNS"]):
        raise ValueError(f"{KIND} STREAM_RETURNS must be a list of type names: {name}")
    kwarg = pack["ERROR_STATUS_KWARG"]
    if kwarg is not None and (not isinstance(kwarg, str) or not kwarg):
        raise ValueError(f"{KIND} ERROR_STATUS_KWARG must be a keyword name or None: {name}")
    for key in ("RESPONSE_EXEMPT", "INFRA_ROUTES"):
        if not _is_str_seq(pack[key]):
            raise ValueError(f"{KIND} {key} must be a list of strings: {name}")
    prefix = pack["PREFIX_PATTERN"]
    if prefix and (not isinstance(prefix, str) or valid_patterns({"PREFIX_PATTERN": prefix}, None)
                   or re.compile(prefix).groups < 1):
        raise ValueError(f"{KIND} PREFIX_PATTERN must be a regex capturing the prefix in group 1: {name}")


def _check_ui(pack: dict[str, Any], name: str) -> None:
    if not _is_str_seq(pack["UI_EXT"]) or not pack["UI_EXT"]:
        raise ValueError(f"{KIND} UI_EXT must be a list of UI source patterns: {name}")
    parser = pack["ESLINT_PARSER"]
    if not isinstance(parser, str) or not parser:
        raise ValueError(f"{KIND} ESLINT_PARSER must be a parser package name: {name}")
    if not isinstance(pack["PARSER_OPTIONS"], dict):
        raise ValueError(f"{KIND} PARSER_OPTIONS must be a mapping: {name}")
    if not isinstance(pack["ESLINT_INSTALL"], str):
        raise ValueError(f"{KIND} ESLINT_INSTALL must be an install command string: {name}")
    for key in ("LOGIC_EXT", "COMPONENT_EXT", "ENTRY_MARKERS"):
        if not _is_str_seq(pack[key]):
            raise ValueError(f"{KIND} {key} must be a list of strings: {name}")
    parsers = pack["PARSERS"]
    if not isinstance(parsers, dict) or not all(isinstance(glob, str) and glob and isinstance(parser, str) and parser
                                                for glob, parser in parsers.items()):
        raise ValueError(f"{KIND} PARSERS must map file globs to parser packages: {name}")
    error = valid_patterns(pack["OWNED"], None)
    if error:
        raise ValueError(f"{KIND} OWNED {error}: {name}")
    if not pack["ESLINT_INSTALL"]:
        pack["ESLINT_INSTALL"] = f"npm i -D eslint {parser}"


def load_one(name: str) -> dict[str, Any]:
    """팩 하나를 읽고 역할에 맞게 검증한다. 못 찾거나 선언이 틀리면 ValueError — 프로파일 오류로 보고된다."""
    module = run_pack(KIND, SHIPPED_DIR, ROOT / PROJECT_DIR, name)
    role = getattr(module, "ROLE", None)
    if role not in ROLES:
        raise ValueError(f"{KIND} ROLE must be one of {' '.join(ROLES)}: {name}")
    defaults = _SERVER_DEFAULTS if role == "server" else _UI_DEFAULTS
    pack: dict[str, Any] = {"NAME": name, "ROLE": role, **defaults}
    for key in defaults:
        if hasattr(module, key):
            pack[key] = getattr(module, key)
    if not isinstance(pack["FIXTURES"], dict):
        raise ValueError(f"{KIND} FIXTURES must be a mapping: {name}")
    if not valid_requires(pack["REQUIRES"]):
        raise ValueError(f"{KIND} REQUIRES must list mappings of name, check (command list), install: {name}")
    if role == "server":
        _check_server(pack, name)
    else:
        _check_ui(pack, name)
        # 짝 확장자를 선언하기 전의 팩은 예전 판정(.ts 로직·.tsx 컴포넌트)을 그대로 받는다 — 업그레이드로 검사가 조용히 꺼지지 않게
        for key, glob, suffix in (("LOGIC_EXT", "*.ts", ".ts"), ("COMPONENT_EXT", "*.tsx", ".tsx")):
            if not hasattr(module, key) and glob in pack["UI_EXT"]:
                pack[key] = (suffix,)
    return pack


def load(names: tuple[str, ...]) -> dict[str, dict[str, Any] | None]:
    """프로파일 FRAMEWORK 전체를 역할별 팩으로. 같은 역할이 둘이면 프로파일 오류다 — 어느 선언을 믿을지 정할 수 없다."""
    packs = unselected()
    for name in names:
        pack = load_one(name)
        held = packs[pack["ROLE"]]
        if held is not None:
            raise ValueError(f"{KIND} role {pack['ROLE']} chosen twice: {held['NAME']} · {name} — pick one per role")
        packs[pack["ROLE"]] = pack
    return packs
