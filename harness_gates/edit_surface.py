"""harness_gates/edit_surface.py — 면제·제외 목록은 줄어들기만 한다.

게이트를 느슨하게 만드는 가장 쉬운 방법은 게이트 코드를 고치는 게 아니라 면제 목록에 한 줄을
더하는 것이다. 회고(harness-retro)의 판정을 아직 사람이 하는 지금도 이 길은 막아 둬야, 나중에
판정을 자동화할 여지가 생긴다. 결과를 평가할 기준(적합도 함수) 없이 제안과 수용을 자동화하면
그 루프는 가장 쉽게 통과하는 쪽으로 흘러가고, 그 쉬운 길이 바로 면제 목록 추가다.

이 레포에만 해당하는 규칙이라 커널이 아니라 여기에 둔다. 커널에는 특정 프로젝트에만 맞는 규칙을
넣지 않는다. 동결본(현재 허용 목록을 고정해 둔 파일)은 `harness_surface.txt` 이고, 형식은 기존
래칫 baseline 파일(항목이 줄어들기만 허용되는 목록)들과 같다.
"""

from __future__ import annotations

from pathlib import Path

from kernel import profile
from kernel.context import ROOT, read_pairs

SURFACE_FILE = ROOT / "harness_surface.txt"
TITLE = "Edit surface ratchet (exemption and exclusion lists)"
SCOPE_KEY = 'SCOPE["exclude_all"]'


def current() -> set[tuple[str, str]]:
    """프로파일이 현재 선언한 면제·제외 항목 전체."""
    found = {(f"ALLOWLIST[{key}]", value)
             for key, values in profile.ALLOWLIST.items() for value in values}
    return found | {(SCOPE_KEY, value) for value in profile.SCOPE["exclude_all"]}


def frozen() -> set[tuple[str, str]]:
    """동결본. 형식은 `<표면 키>\\t<값>` 이고 주석과 빈 줄은 건너뛴다."""
    return read_pairs(SURFACE_FILE)


def run(py_files: list[Path], ui_files: list[Path]) -> list[tuple[str, list[str]]]:
    """레포 전체를 판정하므로 인자로 받은 파일 목록은 쓰지 않는다. 편집이 있을 때마다 면제·제외 목록 전체를 다시 본다."""
    del py_files, ui_files
    if not SURFACE_FILE.exists():
        return [(TITLE, [f"{SURFACE_FILE.name} missing — without a baseline file for the exemption and exclusion lists, "
                         f"nobody notices when exemptions grow. Create it by copying the profile's current declarations"])]
    added = sorted(current() - frozen())
    return [(TITLE, [f"{SURFACE_FILE.name}: '{value}' was added to {key} — this loosens a gate. "
                     f"First see whether the code can be fixed instead of exempted; if it is still needed, "
                     f"record the reason in dev/REJECTED.md, then add a row to this file"
                     for key, value in added])]
