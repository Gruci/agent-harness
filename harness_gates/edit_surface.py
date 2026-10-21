"""harness_gates/edit_surface.py — 면제·제외 목록은 줄어들기만 한다.

게이트를 느슨하게 만드는 가장 쉬운 방법은 게이트 코드를 고치는 게 아니라 면제 목록에 한 줄을
더하는 것이다. 회고(harness-retro)의 판정을 아직 사람이 하는 지금도 이 길은 막아 둬야, 나중에
판정을 자동화할 여지가 생긴다. 결과를 평가할 기준(적합도 함수) 없이 제안과 수용을 자동화하면
그 루프는 가장 쉽게 통과하는 쪽으로 흘러가고, 그 쉬운 길이 바로 면제 목록 추가다.

커널이 아니라 여기에 두지만, 새 프로젝트에도 첫날부터 켠다(`profiles/_template.py` LOCAL_GATES). 동결본(현재 허용
목록을 고정해 둔 파일)은 `harness_surface.txt` 이고, 설치가 프리셋 선언으로 다시 뜬다(`write`). 형식은 기존
래칫 baseline 파일(항목이 줄어들기만 허용되는 목록)들과 같다.

필수 검사 목록(`REQUIRED_CHECKS`, `kernel/required.py`)은 극성이 반대다 — 빼는 것이 완화다. 같은 동결본에
`REQUIRED_CHECKS` 키로 적고, 그 행은 프로파일 선언에서 **빠지면** 위반이다. 면제 쪽 판정(`declared`)과 섞지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from kernel import profile
from kernel.context import ROOT, read_pairs

SURFACE_FILE = ROOT / "harness_surface.txt"
TITLE = "Edit surface ratchet (exemption and exclusion lists)"
SCOPE_KEY = 'SCOPE["exclude_all"]'
REQUIRED_KEY = "REQUIRED_CHECKS"
# 정본 래퍼 하나를 지정하는 키 — 관례(`dev/CONVENTIONS.md` F1·F9)가 등록하라고 요구한다. 하나뿐이면 면제가 아니라 지정이고
# 검사를 켜거나 좁힌다. 둘째부터는 우회로가 될 수 있어 다른 면제와 같이 센다.
DESIGNATIONS = ("ui_fetch_wrappers", "ui_platform")
# ko-ok: header of the Korean-language baseline file harness_surface.txt
HEADER = """# harness_surface.txt — 편집 표면 동결 목록. 게이트가 봐주기로 한 것의 전량이다.
#
# 형식: <표면 키>\\t<값>
# 판정: harness_gates/edit_surface.py — 프로파일 선언이 이 목록보다 늘면 위반이다.
#
# 래칫: 이 파일은 줄어들기만 해야 한다. 면제를 없앴으면 해당 행을 지운다.
#       늘려야 한다면 그건 게이트를 무르게 만드는 변경이다. 코드를 고치는 쪽이 먼저이고,
#       그래도 필요하면 사유를 dev/REJECTED.md 에 남긴 뒤 같은 커밋에서 여기에 더한다.
# 예외: REQUIRED_CHECKS 행은 반대다 — 늘리기만 한다. 프로파일에서 필수 검사를 빼면 위반이다.
#
# 새 프로젝트에 하네스를 깔면 설치가 프리셋 선언으로 이 파일을 다시 뜬다(harness_install.py write_surface).
"""


def declared(source: object) -> set[tuple[str, str]]:
    """프로파일 모양 객체(`ALLOWLIST`·`SCOPE` 를 가진 모듈)가 선언한 면제·제외 항목 전체."""
    allow = getattr(source, "ALLOWLIST", None) or {}
    scope = getattr(source, "SCOPE", None) or {}
    found = {(f"ALLOWLIST[{key}]", value) for key, values in allow.items() for value in (values or ())
             if not (key in DESIGNATIONS and len(values or ()) == 1)}
    # 병합 전 값을 본다 — 병합된 `profile.NAMING`·`profile.OWNED` 는 `None` 을 이미 지웠다. 프로파일 모듈에는 그 이름 그대로다
    naming = getattr(source, "NAMING_OVERRIDE", getattr(source, "NAMING", None)) or {}
    owned = getattr(source, "OWNED_OVERRIDE", getattr(source, "OWNED", None)) or {}
    families = getattr(source, "OWNED_FAMILIES", frozenset())
    # 끄기(None)·표기 넓히기(`snake|camel`)·기본 가족의 정규식 바꿔치기는 면제다. 표기를 바꾸는 것(snake → camel)과
    # 새 가족을 더하는 것은 검사를 느슨하게 하지 않아 세지 않는다
    found |= {(f"NAMING[{key}]", value or "off") for key, value in naming.items() if value is None or "|" in value}
    found |= {(f"OWNED[{key}]", value or "off") for key, value in owned.items() if value is None or key in families}
    return found | {(SCOPE_KEY, value) for value in (scope.get("exclude_all") or ())}


def required(source: object) -> set[tuple[str, str]]:
    """필수 검사 목록. 면제와 극성이 반대라 declared() 에 섞지 않는다 — 여기서는 빠지는 것이 완화다."""
    return {(REQUIRED_KEY, slug) for slug in getattr(source, "REQUIRED_CHECKS", None) or () if isinstance(slug, str)}


def frozen_rows(source: object) -> set[tuple[str, str]]:
    """동결본에 적을 행 전체 — 면제·제외와 필수 검사. 설치와 내보내기가 쓴다."""
    return declared(source) | required(source)


def current() -> set[tuple[str, str]]:
    """프로파일이 현재 선언한 면제·제외 항목 전체."""
    return declared(profile)


def frozen() -> set[tuple[str, str]]:
    """동결본. 형식은 `<표면 키>\\t<값>` 이고 주석과 빈 줄은 건너뛴다."""
    return read_pairs(SURFACE_FILE)


def write(rows: set[tuple[str, str]], path: Path = SURFACE_FILE) -> None:
    """동결본을 선언 그대로 쓴다. 설치가 프리셋 선언으로 부른다 — 하네스 레포의 면제 목록을 물려받지 않게."""
    path.write_text(HEADER + "".join(f"{key}\t{value}\n" for key, value in sorted(rows)), encoding="utf-8")


def run(py_files: list[Path], ui_files: list[Path]) -> list[tuple[str, list[str]]]:
    """레포 전체를 판정하므로 인자로 받은 파일 목록은 쓰지 않는다. 편집이 있을 때마다 면제·제외 목록 전체를 다시 본다."""
    del py_files, ui_files
    if not SURFACE_FILE.exists():
        return [(TITLE, [f"{SURFACE_FILE.name} missing — without a baseline file for the exemption and exclusion lists, "
                         f"nobody notices when exemptions grow. Create it by copying the profile's current declarations"])]
    rows = frozen()
    frozen_required = {row for row in rows if row[0] == REQUIRED_KEY}
    added = sorted(current() - (rows - frozen_required))
    removed = sorted(frozen_required - required(profile))
    return [(TITLE, [f"{SURFACE_FILE.name}: '{value}' was added to {key} — this loosens a gate. "
                     f"First see whether the code can be fixed instead of exempted; if it is still needed, "
                     f"record the reason in dev/REJECTED.md, then add a row to this file"
                     for key, value in added] +
                    [f"{SURFACE_FILE.name}: '{value}' was removed from {REQUIRED_KEY} in the profile — dropping a required check "
                     f"loosens the completion contract. If it is still needed, record the reason in dev/REJECTED.md, "
                     f"then delete the row from this file"
                     for _key, value in removed])]
