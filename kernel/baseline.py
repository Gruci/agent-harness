"""kernel/baseline.py — 설치 시점에 동결한 위반 목록(래칫: 줄기만 하고 늘지 않는 목록)을 읽어 적용한다.

하네스를 기존 레포에 설치한 첫 실행이 위반을 수백 건 쏟아내면 사람은 게이트를 통째로 끈다.
하네스가 실제로 버려지는 경로가 이것이다. 그래서 설치할 때 현재 위반을 (slug, 파일) 단위로 동결해
모든 검사가 통과한 상태에서 출발한다. 줄번호로 동결하지 않는 이유는 코드가 한 줄만 밀려도 동결이 풀리기 때문이다.

러너는 동결을 적용하고, 설치 스크립트는 동결 목록을 만들고, trace 는 위반에서 파일 경로를 뽑는다.
셋이 같은 판정을 쓰므로 러너 밖으로 뺐다. 러너 파일이 400줄 상한을 지키게 하려는 것도 이유다.

`growth` 는 래칫이 실제로 늘었는지를 **관찰**한다. 면제 파일에 행을 더하는 일은 어떤 훅도 걸지 않아 기록에 남지 않았고,
막힌 세션의 가장 싼 출구가 그 한 줄이었다. 판정은 하지 않는다 — 늘어난 행을 돌려주면 `kernel.task finish` 가 알리고
관찰로 남기며, 차단으로 올릴지는 회고가 그 관찰을 보고 정한다(`dev/REJECTED.md` 「편집 표면 래칫 확대」 보류).
"""

from __future__ import annotations

import ast
from pathlib import Path

from kernel.context import ROOT, git_output, read_pairs

BASELINE_FILE = ROOT / "harness_baseline.txt"
# 래칫 파일 전부 — 커널·로컬 게이트의 `*_baseline.txt`·`*_allowlist.txt`·`harness_surface.txt` 상수와 같아야 한다.
# 원류 tests/test_trace.py 가 상수 grep 으로 빠진 것이 없는지 단언한다.
RATCHET_FILES = ("harness_baseline.txt", "md_style_baseline.txt", "md_ref_allowlist.txt", "dup_decl_baseline.txt",
                 "dup_block_baseline.txt", "test_pairing_baseline.txt", "ddl_types_baseline.txt",
                 "api_array_baseline.txt", "harness_surface.txt")
# 프로파일의 문서 제외 목록 — 값이 늘면 문서 검사가 그만큼 꺼진다.
MD_EXCLUDE_KEYS = ("style_exclude", "doc_exclude", "ref_exclude")
PROFILE_NAME = "harness_profile.py"


def violation_path(violation: str) -> str | None:
    """위반 문자열 앞머리의 파일 경로. 파일에 귀속되지 않는 전역 위반이면 None."""
    head = violation.split(":", 1)[0].strip()
    if not head or " " in head or ("/" not in head and "." not in head):
        return None
    return head


def load_baseline() -> set[tuple[str, str]]:
    return read_pairs(BASELINE_FILE)


def apply_baseline(sections: list) -> list:
    """동결된 (slug, 파일) 쌍의 위반을 걸러낸다. Section 형태의 정의는 runner 에 있다."""
    frozen = load_baseline()
    if not frozen:
        return sections
    kept = []
    for slug, title, violations, skipped in sections:
        live = [v for v in violations
                if (slug, violation_path(v) or "") not in frozen]
        kept.append((slug, title, live, skipped))
    return kept


def _git_out(tree: Path, *args: str) -> str:
    """그 체크아웃에서 git 한 번. 실패는 빈 문자열 — 관찰은 끝내기를 막지 않는다."""
    return git_output("-C", str(tree), *args) or ""


def _added_rows(tree: Path, base: str) -> list[str]:
    """`base...HEAD` 가 래칫 파일에 더한 비주석 행."""
    found: list[str] = []
    current = ""
    for line in _git_out(tree, "diff", "-U0", f"{base}...HEAD", "--", *RATCHET_FILES).splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/").strip()
        elif line.startswith("+") and not line.startswith("+++"):
            body = line[1:].split("#", 1)[0].strip()
            if body:
                found.append(f"{current}: +{body}")
    return found


def md_excludes(source: str) -> dict[str, set[str]]:
    """프로파일 원문의 `MD = {...}` 에서 제외 목록 세 키의 값 집합. 마지막 대입이 이긴다(파이썬 의미). 읽을 수 없으면 비어 있다."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    found: dict[str, set[str]] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if not any(isinstance(target, ast.Name) and target.id == "MD" for target in targets) or node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            return {}
        found = {key: set(value.get(key) or ()) for key in MD_EXCLUDE_KEYS} if isinstance(value, dict) else {}
    return found


def _added_excludes(tree: Path, base: str) -> list[str]:
    """`base` 와 HEAD 의 프로파일을 대조해 늘어난 제외 값."""
    before = md_excludes(_git_out(tree, "show", f"{base}:{PROFILE_NAME}"))
    after = md_excludes(_git_out(tree, "show", f"HEAD:{PROFILE_NAME}"))
    return [f"{PROFILE_NAME}: MD[{key!r}] += {value!r}"
            for key in MD_EXCLUDE_KEYS for value in sorted(after.get(key, set()) - before.get(key, set()))]


def growth(tree: Path, base: str) -> list[str]:
    """`base` 이후 이 체크아웃이 래칫 파일에 더한 행과 프로파일 MD 제외 목록에 더한 값. 판정하지 않고 행만 돌려준다."""
    return _added_rows(tree, base) + _added_excludes(tree, base)
