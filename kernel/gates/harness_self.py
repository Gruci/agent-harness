"""kernel/gates/harness_self.py — 하네스가 자기를 바르게 서술하는가.

대상이 앱 코드가 아니라 **하네스 자신**이라는 점에서 나머지 게이트와 다르다. 하네스가 자기를
잘못 서술하면 그 오류를 다음 세션이 사실로 믿는다. 게다가 그 상태에서도 검사 결과는 초록불로 보인다.

  모델 정책   에이전트 frontmatter 의 model·effort vs 프로파일 `AGENT_MODEL_POLICY`
  승격 상태   사고 기록 각 절의 `> 강제:` 선언

모델 라우팅은 기계로 검사할 수 있는데, 산문으로만 적어 두면 실제 설정과 어긋나도 아무도 모르고
넘어간다. 사고 기록도 마찬가지다. 적어 두기만 하고 게이트로 만들지 판단하지 않으면 그 규칙은
산문으로만 남고, 다음 세션부터 점점 지켜지지 않는다. 그래서 강제 수단 선언 자체를 필수로 만들어,
게이트로 만들지 여부를 사고 기록을 쓰는 시점에 정하게 한다.
"""

from __future__ import annotations

import re

from kernel import profile
from kernel.context import READ_ENC, ROOT

AGENTS_DIR = ".claude/agents"

_FM_MODEL = re.compile(r"^model:\s*(\S+)\s*$", re.M)
_FM_EFFORT = re.compile(r"^effort:\s*(\S+)\s*$", re.M)

_GATE_ROW = re.compile(r"^\|\s*([\d·~\s]+)\s*\|")
_LESSON_HEADING = re.compile(r"^##\s+§(\d+)\s")
_LESSON_ENFORCE = re.compile(r"^>\s*강제:\s*(.+?)\s*$")   # ko-ok: parses the Korean key in dev/LESSONS.md
_LESSON_GATE_REF = re.compile(r"검사\s*([\d·~\s]+)")      # ko-ok: parses the Korean key in dev/LESSONS.md


def check_agent_model_policy() -> list[str]:
    """등재된 에이전트의 frontmatter 가 정책 표와 어긋나면 위반.

    정책에 없는 에이전트(벤더 사본·신규)는 검사하지 않는다. 정책 표에 등재한 에이전트만 이 계약을 따른다.
    """
    bad: list[str] = []
    for name, spec in sorted(profile.AGENT_MODEL_POLICY.items()):
        model, effort = spec
        path = ROOT / AGENTS_DIR / f"{name}.md"
        if not path.exists():
            bad.append(f"{AGENTS_DIR}/{name}.md missing — listed in the policy but the file does not exist")
            continue
        text = path.read_text(encoding=READ_ENC, errors="replace")
        found_model = _FM_MODEL.search(text)
        found_effort = _FM_EFFORT.search(text)
        if not found_model or found_model.group(1) != model:
            actual = found_model.group(1) if found_model else "none"
            bad.append(f"{AGENTS_DIR}/{name}.md: model {actual!r} ≠ policy {model!r} — "
                       f"if you changed the routing, fix the profile in the same commit")
        if not found_effort or found_effort.group(1) != effort:
            actual = found_effort.group(1) if found_effort else "none"
            bad.append(f"{AGENTS_DIR}/{name}.md: effort {actual!r} ≠ policy {effort!r} — "
                       f"if you raised or lowered effort, fix the policy in the same commit")
    return bad


def mapped_gate_numbers(text: str) -> set[int]:
    """하네스 지도의 게이트 표에서 번호 열을 읽어 개별 번호로 펼친다. `1~7`, `8·9` 같은 묶음 표기도 펼친다."""
    numbers: set[int] = set()
    for line in text.splitlines():
        match = _GATE_ROW.match(line.strip())
        if not match:
            continue
        for token in match.group(1).replace(" ", "").split("·"):
            if "~" in token:
                start, _sep, end = token.partition("~")
                if start.isdigit() and end.isdigit():
                    numbers.update(range(int(start), int(end) + 1))
            elif token.isdigit():
                numbers.add(int(token))
    return numbers


def _declared_enforcement(lines: list[str], index: int) -> str:
    """사고 절 제목 바로 뒤 4줄 안의 `> 강제:` 선언."""
    for follow in lines[index + 1:index + 5]:
        found = _LESSON_ENFORCE.match(follow.strip())
        if found:
            return found.group(1)
    return ""


def check_lessons_promotion() -> list[str]:
    """사고 절마다 강제 수단 선언이 있는지 본다. 게이트로 올릴지(승격) 판단을 미룰 여지를 없앤다.

    산문 전용으로 남기는 것 자체는 괜찮다. 다만 사유가 있어야 하고, 게이트 번호를 인용했다면
    그 번호가 하네스 지도에 있어야 한다. 그래서 산문 전용 목록이 곧 다음 승격 후보 목록이 된다.
    """
    doc_name = profile.LESSONS_DOC
    if not doc_name:
        return []
    doc = ROOT / doc_name
    harness_map = ROOT / profile.HARNESS_MAP
    if not doc.exists():
        return []
    mapped: set[int] = set()
    if harness_map.exists():
        mapped = mapped_gate_numbers(harness_map.read_text(encoding=READ_ENC, errors="replace"))

    lines = doc.read_text(encoding=READ_ENC, errors="replace").splitlines()
    bad: list[str] = []
    for i, line in enumerate(lines):
        heading = _LESSON_HEADING.match(line)
        if not heading:
            continue
        section = heading.group(1)
        declared = _declared_enforcement(lines, i)
        if not declared:
            bad.append(f"{doc_name}:{i + 1}: §{section} has no `> 강제:` declaration — "  # ko-ok: cites a Korean doc key
                       f"name a gate or write `산문 전용 — <reason>`")
            continue
        if "산문 전용" in declared:  # ko-ok: parses the Korean key in dev/LESSONS.md
            if not declared.split("산문 전용", 1)[1].strip(" —-"):  # ko-ok: parses the Korean key in dev/LESSONS.md
                bad.append(f"{doc_name}:{i + 1}: §{section} `산문 전용` has no reason")  # ko-ok: cites a Korean doc key
            continue
        cited = _LESSON_GATE_REF.search(declared)
        if not cited or not mapped:
            continue          # 게이트를 이름으로 선언했거나 지도에 번호 표가 없다
        for token in re.findall(r"\d+", cited.group(1)):
            if int(token) not in mapped:
                bad.append(f"{doc_name}:{i + 1}: §{section} cites check {token}, "
                           f"which is not in the {profile.HARNESS_MAP} gate table")
    return bad
