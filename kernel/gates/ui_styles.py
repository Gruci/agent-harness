"""kernel/gates/ui_styles.py — 스크립트 밖 화면 스타일(스타일시트·템플릿)의 색 리터럴과 고정 폭.

ESLint 규칙(`kernel/eslint.harness.mjs`)은 스크립트 AST 만 본다. `.css` 파일과 Vue·Svelte·HTML 의 `<style>`·`style=` 은
여기서 텍스트로 본다. 결과는 같은 slug(`hex_literal`·`responsive`) 섹션에 합친다.

선언 값(`속성: 값`)만 본다 — `#add` 같은 ID 선택자가 색으로 읽히지 않는다. 토큰 정본 파일, CSS 변수 정의 줄(`--x: …`),
테스트 파일, `ALLOWLIST["ui_hex"]`, `ui_admin` 레이어는 뺀다. 고정 폭은 ESLint 와 같은 `px-ok` 표시로 면제한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, _rel
from kernel.gates.tests_pairing import is_test_path

STYLE_EXT = ("*.css", "*.scss", "*.less", "*.vue", "*.svelte", "*.html")
SHEET_SUFFIXES = (".css", ".scss", ".less")

_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_PRELUDE = re.compile(r"@(?:media|container|supports)\b[^{;]*")
_STYLE_ATTR = re.compile(r"""(?<![\w-]):?style\s*=\s*(["'])(.*?)\1""", re.S | re.I)
_VALUE = re.compile(r"([\w-]+)\s*:\s*([^;,{}\n]*)")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_HSL = re.compile(r"\b(?:rgba?|hsla?)\s*\(")
_FIXED = re.compile(r"""^\s*['"]?\d{3,}px""")
_VW = re.compile(r"\b100vw\b")
_WIDTH_PROPS = ("width", "min-width", "minWidth")
_COLOR_PROPS = ("color", "background", "background-color", "backgroundColor", "border-color", "borderColor",
                "fill", "stroke")
_COLOR_WORD = re.compile(r"""^\s*['"]?([A-Za-z]+)['"]?\s*(?:!important\s*)?$""")
_COLOR_KEYWORDS = frozenset(("transparent", "currentcolor", "inherit", "initial", "unset", "none", "revert", "auto"))


def _without_preludes(css: str) -> str:
    """`@media (min-width: 768px)` 같은 조건부 규칙의 머리는 폭 선언이 아니라 분기점이다 — 같은 길이의 공백으로 지운다."""
    return _PRELUDE.sub(lambda match: " " * len(match.group(0)), css)


def _regions(text: str, suffix: str) -> list[tuple[int, str]]:
    """(시작 오프셋, 스타일 텍스트). 스타일시트는 통째로, 템플릿은 `<style>` 블록과 `style=`·`:style=` 속성값만."""
    if suffix in SHEET_SUFFIXES:
        return [(0, _without_preludes(text))]
    regions = [(match.start(1), _without_preludes(match.group(1))) for match in _STYLE_BLOCK.finditer(text)]
    return regions + [(match.start(2), match.group(2)) for match in _STYLE_ATTR.finditer(text)]


def _findings(prop: str, value: str, tokens_note: str) -> list[tuple[str, str]]:
    """선언 하나의 (slug, 메시지)."""
    found = [("hex_literal", f"hex literal {hex_value} — use {tokens_note}") for hex_value in _HEX.findall(value)]
    if _RGB_HSL.search(value):
        found.append(("hex_literal", f"rgb()/hsl() color literal — use {tokens_note}"))
    word = _COLOR_WORD.match(value) if prop in _COLOR_PROPS else None
    if word and word.group(1).lower() not in _COLOR_KEYWORDS:
        found.append(("hex_literal", f"named color {word.group(1)} — use {tokens_note}"))
    if prop in _WIDTH_PROPS and _FIXED.match(value):
        found.append(("responsive", "fixed px width — use max-width, %, minmax or clamp (if unavoidable: `px-ok: reason`)"))
    if _VW.search(value):
        found.append(("responsive", "100vw overflows horizontally by the vertical scrollbar width — use 100%"))
    return found


def _exempt(rel: str, slug: str) -> bool:
    admin = profile.layer("ui_admin")
    tokens = profile.layer_raw("ui_tokens")
    allowed = tuple(profile.ALLOWLIST["ui_hex"]) if slug == "hex_literal" else ()
    return bool((admin and rel.startswith(admin)) or rel == tokens or (allowed and rel.startswith(allowed)))


def check_styles(files: list[Path]) -> dict[str, list[str]]:
    """slug → 위반 목록. 위반 문장은 ESLint 결과와 같은 `경로:행: 메시지` 형식이다."""
    tokens = profile.layer_raw("ui_tokens")
    note = f"{tokens} or a CSS variable" if tokens else "the token file or a CSS variable"
    found: dict[str, list[str]] = {"hex_literal": [], "responsive": []}
    for path in files:
        rel = _rel(path)
        if is_test_path(rel):
            continue
        text = path.read_text(encoding=READ_ENC, errors="replace")
        lines = text.splitlines()
        for offset, region in _regions(text, path.suffix):
            for match in _VALUE.finditer(region):
                prop, value = match.group(1), match.group(2)
                if prop.startswith("--"):
                    continue                     # CSS 변수 정의가 토큰을 담는 자리다
                number = text.count("\n", 0, offset + match.start()) + 1
                for slug, message in _findings(prop, value, note):
                    escaped = slug == "responsive" and "px-ok" in lines[number - 1]
                    if not escaped and not _exempt(rel, slug):
                        found[slug].append(f"{rel}:{number}: {message}")
    return found
