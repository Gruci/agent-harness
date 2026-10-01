"""harness_gates/english_output.py — 하네스가 내는 출력은 영어다.

출력 영어화를 잠그는 래칫이다. 하네스 코드의 문자열 리터럴(docstring 제외)과 훅 설정의 명령·문구에
한글이 있으면 위반이다. 한국어 문서나 데이터 서식을 읽어야 하는 리터럴은 그 줄에 `# ko-ok: <사유>` 를 단다.
이 레포에만 해당하는 규칙이라 커널이 아니라 여기에 둔다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from kernel.context import READ_ENC, ROOT, tracked

TITLE = "English-only harness output"
HANGUL = re.compile(r"[가-힣]")                  # ko-ok: detection pattern, not output
ESCAPE = "# ko-ok:"
CODE_ROOTS = ("kernel/", ".claude/hooks/", "harness_gates/", "profiles/")
CODE_FILES = ("harness_install.py", "setup_global_permissions.py")
HOOK_CONFIGS = (".claude/settings.json", ".claude-plugin/hooks.json", ".codex/hooks.json")


def _docstrings(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, owners) and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)}


def _escaped(lines: list[str], lineno: int) -> bool:
    """탈출 주석은 리터럴이 시작하는 줄이나 그 바로 위 줄에 둔다. 여러 줄 문자열은 시작 줄에 주석을 달 수 없다."""
    return any(ESCAPE in lines[index] for index in (lineno - 2, lineno - 1) if 0 <= index < len(lines))


def check_source(rel: str, text: str) -> list[str]:
    tree = ast.parse(text)
    lines = text.splitlines()
    skip = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                and HANGUL.search(node.value) and not _escaped(lines, node.lineno)):
            found.append(f"{rel}:{node.lineno}: Korean text in output — write it in English, "
                         f"or mark a data-format literal with `{ESCAPE} <reason>`")
    return found


def check_hook_config(rel: str, text: str) -> list[str]:
    found = []
    for index, line in enumerate(text.splitlines(), 1):
        if HANGUL.search(line):
            found.append(f"{rel}:{index}: Korean text in a hook command or message — write it in English")
    json.loads(text)                                 # 깨진 설정은 다른 검사보다 먼저 드러나야 한다
    return found


def run(_py: list[Path], _ui: list[Path]) -> list[tuple[str, list[str]]]:
    """레포 전체 하네스 코드를 판정하므로 인자로 받은 파일 목록은 쓰지 않는다."""
    found: list[str] = []
    for path in tracked("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(CODE_ROOTS) or rel in CODE_FILES:
            found += check_source(rel, path.read_text(encoding=READ_ENC))
    for rel in HOOK_CONFIGS:
        path = ROOT / rel
        if path.is_file():
            found += check_hook_config(rel, path.read_text(encoding=READ_ENC))
    return [(TITLE, found)]
