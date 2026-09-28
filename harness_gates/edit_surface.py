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
TITLE = "편집 표면 래칫(면제·제외 목록)"
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
        return [(TITLE, [f"{SURFACE_FILE.name} 없음 — 면제·제외 목록을 파일로 고정해 두지 않으면 면제가 "
                         f"늘어도 아무도 모른다. 프로파일의 현재 선언을 그대로 옮겨 적어 만들어라"])]
    added = sorted(current() - frozen())
    return [(TITLE, [f"{SURFACE_FILE.name}: {key} 에 '{value}' 가 늘었다 — 게이트를 느슨하게 "
                     f"만드는 변경이다. 면제 말고 코드를 고칠 수 없는지 먼저 보고, 그래도 "
                     f"필요하면 사유를 dev/REJECTED.md 에 남긴 뒤 이 파일에 행을 더하라"
                     for key, value in added])]
