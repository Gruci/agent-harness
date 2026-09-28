"""kernel/diagram/svg.py — 렌더된 HTML 에서 독립 SVG 를 뽑는다. README 는 이 SVG 로 그림을 싣는다.

GitHub 은 HTML 을 그리지 않고 SVG 는 그린다. 뷰어 HTML 의 그림은 `<svg>` 하나에 CSS 클래스로
색을 입히므로, 그 클래스 규칙과 CSS 변수와 폰트를 `<style>` 로 SVG 안에 넣어 주면 HTML 없이도 그려진다.
CSS 를 정규식 하나로 자르지 않는다. 300KB 스타일에 중첩 괄호가 있어 정규식 백트래킹이 폭증한 적이 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

_SVG_OPEN = re.compile(r"<svg\b[^>]*>")
_CLASS_ATTR = re.compile(r'class="([^"]+)"')
_VAR_USE = re.compile(r"var\((--[A-Za-z0-9_-]+)")
_VAR_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")


def _rules(css: str) -> list[tuple[str, str]]:
    """(셀렉터, 본문) 목록. 중괄호 깊이를 세며 한 번 훑고, @media 안의 규칙도 바깥 규칙과 같은 층으로 꺼낸다."""
    found: list[tuple[str, str]] = []
    depth = 0
    start = 0
    selector_stack: list[str] = []
    index = 0
    while index < len(css):
        char = css[index]
        if char == "{":
            selector_stack.append(css[start:index].strip().split("}")[-1].strip())
            depth += 1
            start = index + 1
        elif char == "}":
            body = css[start:index]
            selector = selector_stack.pop() if selector_stack else ""
            if selector and not selector.startswith("@") and "{" not in body:
                found.append((selector, body.strip()))
            depth -= 1
            start = index + 1
        index += 1
    return found


def main_svg(html: str) -> str:
    """가장 큰 `<svg>…</svg>` — 뷰어 HTML 에는 그림 하나뿐이다."""
    best = ""
    for match in _SVG_OPEN.finditer(html):
        end = html.find("</svg>", match.start())
        if end == -1:
            continue
        candidate = html[match.start():end + len("</svg>")]
        if len(candidate) > len(best):
            best = candidate
    return best


def _selector_targets_svg(selector: str, classes: set[str]) -> bool:
    if "data-theme" in selector or ":hover" in selector or ":focus" in selector:
        return False
    return any(f".{name}" in selector for name in classes) or selector.strip() in ("svg", "svg text")


def standalone_svg(html: str) -> tuple[str, set[str]]:
    """(독립 SVG, 정의 안 된 변수). 정의 안 된 변수가 남으면 색이 빠진 그림이 되므로 호출자가 검사한다."""
    svg = main_svg(html)
    if not svg:
        return "", set()
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    classes = {token for attr in _CLASS_ATTR.findall(svg) for token in attr.split()}
    font_faces = re.findall(r"@font-face\s*\{[^}]*\}", css)
    variables: dict[str, str] = {}
    picked: list[str] = []
    for selector, body in _rules(css):
        if _VAR_DEF.search(body) and "dark" not in selector.lower():
            for declaration in body.split(";"):
                name, _, value = declaration.partition(":")
                if name.strip().startswith("--") and value.strip():
                    variables[name.strip()] = value.strip()
        if _selector_targets_svg(selector, classes):
            picked.append(f"{selector} {{ {body} }}")
    root = ":root { " + " ".join(f"{k}: {v};" for k, v in variables.items()) + " }"
    style = "<style>\n" + "\n".join(font_faces) + "\n" + root + "\n" + "\n".join(picked) + "\n</style>"
    used = set(_VAR_USE.findall("\n".join(picked)))
    undefined = {name for name in used if name not in variables}
    opened = _SVG_OPEN.match(svg).group(0)
    tag = opened if 'xmlns="http://www.w3.org/2000/svg"' in opened else opened[:-1] + ' xmlns="http://www.w3.org/2000/svg">'
    return tag + "\n" + style + svg[len(opened):], undefined


def export(html_path: Path, svg_path: Path) -> set[str]:
    """HTML 옆에 SVG 를 쓴다. 반환은 정의 안 된 CSS 변수 — 비어 있어야 정상이다."""
    svg, undefined = standalone_svg(html_path.read_text(encoding="utf-8"))
    if not svg:
        raise ValueError(f"{html_path}: <svg> 가 없다")
    svg_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n", encoding="utf-8")
    return undefined
