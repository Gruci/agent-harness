"""Optional filename pairing for explicitly selected behavior and UI test scopes.

Filename correspondence does not prove behavior or port conformance.
Declared port contracts are checked statically and executed by kernel.port_contracts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, ROOT, _rel, read_list

BASELINE_FILE = ROOT / "test_pairing_baseline.txt"

# 테스트 파일 이름 관례 — 테스트 레이어를 선언하지 않은 프로젝트(Go 의 `_test.go`, 화면의 `*.test.tsx`)도 알아본다.
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__)/|(?:^|/)(?:test_[^/]*|[^/]*_test\.\w+|[^/]*\.(?:test|spec)\.\w+)$")


def is_test_path(rel: str) -> bool:
    """테스트 레이어 아래이거나 이름이 테스트 관례인 파일. 중복·한 주인·이름 검사가 함께 쓴다 — 테스트는 같은 준비 코드를
    되풀이하는 게 관례이고, 기능을 소유하지 않는다."""
    tests = profile.layer("tests")
    return bool(tests and rel.startswith(tests)) or bool(_TEST_PATH.search(rel))


def _test_file_stems() -> list[str]:
    """테스트 루트 아래 test_*.py 파일명에서 접두와 확장자를 뗀 목록. rglob 으로 파일을 직접 훑으므로
    아직 커밋하지 않은 새 테스트도 인정한다."""
    tests = profile.layer("tests")
    tests_dir = ROOT / tests if tests else None
    if tests_dir is None or not tests_dir.exists():
        return []
    return [p.stem[len("test_"):] for p in tests_dir.rglob("test_*.py")]


def check_module_test_pairing(py_files: list[Path]) -> list[str]:
    """명시적으로 선택한 모듈에 대응 테스트 파일이 없으면 위반."""
    roots = tuple(profile.BEHAVIOR_TESTED_ROOTS)
    if not roots:
        return []
    baseline = read_list(BASELINE_FILE)
    test_stems = _test_file_stems()
    tests = profile.layer("tests") or "tests/"
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if not rel.startswith(roots) or f.name == "__init__.py" or rel in baseline:
            continue
        if any(f.stem in stem for stem in test_stems):
            continue
        bad.append(
            f"{rel}: no matching behavior test — write {tests}test_{f.stem}.py "
            f"or list it in {BASELINE_FILE.name} with a reason"
        )
    return bad


# ── 프론트 테스트 짝 ───────────────────────────────────────────────────────────
#
# `tsc`·`vitest`·`vite build` 셋 다 **값이 틀린 것을 못 잡는다.** 타입이 맞고 빌드가 되는 한
# 환산이 틀려도 초록불이다. 로직(.ts)과 컴포넌트(.tsx)는 성격도 테스트 방법도 달라서(순수 함수
# 단언 vs 렌더 테스트) 검사를 나눴다. 짝은 같은 디렉토리에 있는 같은 이름의 `<이름>.test.*`·`<이름>.spec.*` 다.
# 어느 확장자가 로직이고 컴포넌트인지는 화면팩의 `LOGIC_EXT`·`COMPONENT_EXT` 가 정한다(React: `.ts`·`.tsx`).
# 설치 전부터 있던 파일은 설치 시점에 harness_baseline.txt 에 동결해 예외로 둔다.

# export 함수가 있으면 로직 파일이다. 상수·타입 전용 .ts 는 단언할 행동이 없어 대상이 아니다.
_EXPORT_FN = re.compile(r"^export (?:function|const \w+ = [(<])", re.M)


def ui_test_exts(key: str) -> tuple[str, ...]:
    """화면팩이 선언한 짝 대상 확장자(`LOGIC_EXT`·`COMPONENT_EXT`). 팩이 없거나 비웠으면 빈 튜플 — 러너가 [N/A] 로 찍는다."""
    return tuple(profile.UI[key]) if profile.UI else ()


def _has_pair(f: Path) -> bool:
    """glob 이 아니라 이름 접두로 본다 — `[id].tsx` 같은 라우트 파일 이름의 대괄호가 glob 문자 범위로 읽힌다."""
    heads = (f"{f.stem}.test.", f"{f.stem}.spec.")
    return any(name.startswith(heads) for name in os.listdir(f.parent))


def _targets(ui_files: list[Path], key: str) -> list[Path]:
    exts = ui_test_exts(key)
    return [f for f in ui_files if f.suffix in exts and not f.name.endswith(".d.ts") and not is_test_path(_rel(f))]


def check_ui_logic_test_pairing(ui_files: list[Path]) -> list[str]:
    """export 함수가 있는 로직 파일에 같은 디렉토리·같은 이름의 행동 테스트가 없으면 위반."""
    bad: list[str] = []
    for f in _targets(ui_files, "LOGIC_EXT"):
        if _EXPORT_FN.search(f.read_text(encoding=READ_ENC)) and not _has_pair(f):
            bad.append(f"{_rel(f)}: no matching behavior test — write {f.stem}.test.<ext> (or .spec) next to it")
    return bad


def check_ui_component_test_pairing(ui_files: list[Path]) -> list[str]:
    """컴포넌트 파일에 같은 디렉토리·같은 이름의 렌더 테스트가 없으면 위반. 앱 진입 파일(화면팩 `ENTRY_MARKERS`)은
    화면 전체를 띄우는 곳이라 렌더 테스트 짝 대상이 아니다."""
    markers = tuple(profile.UI["ENTRY_MARKERS"]) if profile.UI else ()
    bad: list[str] = []
    for f in _targets(ui_files, "COMPONENT_EXT"):
        if _has_pair(f) or (markers and any(m in f.read_text(encoding=READ_ENC) for m in markers)):
            continue
        bad.append(f"{_rel(f)}: no matching render test — write {f.stem}.test.<ext> (or .spec) next to it")
    return bad
