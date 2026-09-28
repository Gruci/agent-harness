"""kernel/gates/prompt_version.py — 프롬프트 본문이 바뀌면 헤더 버전도 올라야 한다.

프롬프트 파일 첫 줄의 `V<major>.<minor>` 는 LLM 산출물이 어느 지침으로 생성됐는지 판정할
유일한 근거다. 본문만 고치고 버전을 안 올리면 산출물 비교·회귀 판정이 통째로 무너진다.

대상 목록은 프로파일 `VERSIONED_PROMPTS` 다. 비어 있으면 러너가 [SKIP] 으로 찍는다.
원격 기본 브랜치를 못 읽으면(오프라인이거나 origin 이 없을 때) 판정할 수 없으므로 빈 목록을 돌려준다.
"""

from __future__ import annotations

import re

from kernel import profile
from kernel.context import READ_ENC, ROOT, default_branch, git_output as _git

_VERSION = re.compile(r"V(\d+)\.(\d+)")


def ready() -> bool:
    """원격 기본 브랜치를 알 수 있는가. 모르면 비교 기준이 없으므로 통과가 아니라 [SKIP] 으로 찍는 게 맞다."""
    return default_branch() is not None


def check_prompt_version() -> list[str]:
    base = default_branch()
    if base is None:
        return []
    bad: list[str] = []
    for rel in profile.VERSIONED_PROMPTS:
        path = ROOT / rel
        if not path.exists():
            continue                     # 경로 실존 확인은 md_path_refs 계열 검사가 맡는다
        old = _git("show", f"origin/{base}:{rel}")
        if old is None:
            continue                     # 원격에 아직 없는 새 파일 — 비교 기준이 없다
        new = path.read_text(encoding=READ_ENC)
        if old == new:
            continue
        new_v = _VERSION.search(new.split("\n", 1)[0])
        if not new_v:
            bad.append(f"{rel}: 첫 줄에 V<major>.<minor> 버전 헤더가 없다 — 헤더를 붙이고 버전을 올려라")
            continue
        old_v = _VERSION.search(old.split("\n", 1)[0])
        if old_v and old_v.group(0) == new_v.group(0):
            bad.append(f"{rel}: 본문이 바뀌었는데 헤더 버전이 {new_v.group(0)} 그대로다 — 버전을 올려라")
    return bad
