"""kernel/conventions.py — 스택 관례 조각 합성.

문서는 두 층이다. 스택 무관 원칙은 `dev/CONVENTIONS.md` 본문에 직접 쓰고 프로파일 키로 가리킨다.
스택별 관례(훅 규칙·라우트 모양·컴포넌트 배치)는 프레임워크팩 옆 조각 `kernel/frameworks/<이름>.md`
에 두고, 초기 설정의 스택 맞춤이 프로파일 `FRAMEWORK` 가 고른 조각만 「스택 관례」 절에 넣는다.
그래서 하네스 문서는 스택을 추정하지 않고, 고른 스택의 관례는 그 프로젝트 문서에 1급으로 실린다.

절은 표식 주석 사이에 있고 손으로 고치지 않는다. 고칠 것은 조각이고, 이 모듈이 절을 다시 생성한다.
같은 이름의 `profiles/framework/<이름>.md` 가 있으면 프로젝트 것이 이긴다 — 팩 로더와 같은 규칙이다.
조각 머리의 제목과 역할 계약은 조각 파일 자신의 것이라 절에 넣을 때 떼어낸다.

실행: `python -X utf8 -m kernel.conventions <팩 이름…>` — 인자가 없으면 프로파일 `FRAMEWORK` 를 쓴다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from kernel.context import READ_ENC, ROOT

SHIPPED_DIR = Path(__file__).resolve().parent / "frameworks"
PROJECT_DIR = "profiles/framework"
DOC = "dev/CONVENTIONS.md"

BEGIN = "<!-- harness:stack-conventions begin (kernel/frameworks/*.md 에서 생성 — 손으로 고치지 않는다) -->"
END = "<!-- harness:stack-conventions end -->"
NONE_LINE = "(선택한 프레임워크팩 없음 — 초기 설정의 스택 맞춤이 채운다)"

_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*")


def fragment_path(name: str, root: Path = ROOT) -> Path | None:
    """조각 파일 경로. 프로젝트 쪽(`profiles/framework/`)이 커널 쪽(`kernel/frameworks/`)보다 우선한다."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"잘못된 프레임워크팩 이름: {name!r}")
    for candidate in (root / PROJECT_DIR / f"{name}.md", SHIPPED_DIR / f"{name}.md"):
        if candidate.is_file():
            return candidate
    return None


def _body(text: str) -> str:
    """조각 본문 — 머리의 제목(`# `)·역할 계약(`>`)·빈 줄을 뗀 나머지. 본문의 `###` 절 제목은 남긴다."""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith(("# ", ">"))):
        start += 1
    return "\n".join(lines[start:]).rstrip()


def render_conventions(names: tuple[str, ...] | list[str], root: Path = ROOT) -> str:
    """고른 팩의 조각을 이름순으로 표식 사이에 합친다. 조각이 없는 이름은 ValueError — 프로파일 오류로 보고된다."""
    parts: list[str] = []
    for name in sorted(set(names)):
        path = fragment_path(name, root)
        if path is None:
            raise ValueError(f"프레임워크팩 조각을 찾을 수 없음: {name} — {SHIPPED_DIR.name}/{name}.md 또는 {PROJECT_DIR}/{name}.md")
        rel = f"kernel/frameworks/{name}.md" if path.parent == SHIPPED_DIR else f"{PROJECT_DIR}/{name}.md"
        parts.append(f"> 조각 정본: `{rel}` — 고칠 것은 이 파일이다.\n\n"
                     + _body(path.read_text(encoding=READ_ENC)))
    inner = "\n\n".join(parts) if parts else NONE_LINE
    return f"{BEGIN}\n{inner}\n{END}"


def replace_section(text: str, rendered: str) -> str:
    """문서의 표식 절을 통째로 바꾼다. 표식이 없거나 짝이 안 맞으면 ValueError — 절 자리를 사람이 먼저 정한다."""
    lines = text.splitlines()
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise ValueError(f"「스택 관례」 표식이 없거나 짝이 안 맞음 — {BEGIN} … {END} 한 쌍이 있어야 한다")
    body = lines[:begins[0]] + rendered.splitlines() + lines[ends[0] + 1:]
    tail = "\n" if text.endswith("\n") else ""
    return "\n".join(body) + tail


def write(names: tuple[str, ...] | list[str], doc: Path = ROOT / DOC, root: Path = ROOT) -> bool:
    """문서의 절을 다시 생성해 쓴다. 내용이 이미 같으면 쓰지 않고 False."""
    before = doc.read_text(encoding=READ_ENC)
    after = replace_section(before, render_conventions(names, root))
    if after == before:
        return False
    doc.write_text(after, encoding="utf-8", newline="\n")
    return True


def main(argv: list[str]) -> int:
    names: tuple[str, ...]
    if argv:
        names = tuple(argv)
    else:
        from kernel import profile          # 프로파일은 실행 시점에만 읽는다 — 합성 자체는 프로파일 없이도 돈다
        names = profile.FRAMEWORK
    try:
        changed = write(names)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1
    state = "다시 생성" if changed else "이미 최신"
    print(f"{DOC} 「스택 관례」 {state} — 팩: {' '.join(sorted(set(names))) or '(없음)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
