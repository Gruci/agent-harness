"""Optional filename pairing for explicitly selected behavior and UI test scopes.

Filename correspondence does not prove behavior or port conformance.
Declared port contracts are checked statically and executed by kernel.port_contracts.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, ROOT, _rel, read_list

BASELINE_FILE = ROOT / "test_pairing_baseline.txt"


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
            f"{rel}: 대응 행동 테스트 없음 — {tests}test_{f.stem}.py 작성 "
            f"또는 사유와 함께 {BASELINE_FILE.name} 등재"
        )
    return bad


# ── 프론트 테스트 짝 ───────────────────────────────────────────────────────────
#
# `tsc`·`vitest`·`vite build` 셋 다 **값이 틀린 것을 못 잡는다.** 타입이 맞고 빌드가 되는 한
# 환산이 틀려도 초록불이다. 로직(.ts)과 컴포넌트(.tsx)는 성격도 테스트 방법도 달라서(순수 함수
# 단언 vs 렌더 테스트) 검사를 나눴다. 짝은 같은 디렉토리에 있는 같은 이름의 `<이름>.test.ts(x)` 다.
# 설치 전부터 있던 파일은 설치 시점에 harness_baseline.txt 에 동결해 예외로 둔다.

# export 함수가 있으면 로직 파일이다. 상수·타입 전용 .ts 는 단언할 행동이 없어 대상이 아니다.
_EXPORT_FN = re.compile(r"^export (?:function|const \w+ = [(<])", re.M)


def check_ui_logic_test_pairing(ui_files: list[Path]) -> list[str]:
    """export 함수가 있는 .ts 에 같은 디렉토리·같은 이름의 행동 테스트가 없으면 위반."""
    bad: list[str] = []
    for f in ui_files:
        rel = _rel(f)
        if f.suffix != ".ts" or rel.endswith((".d.ts", ".test.ts")):
            continue
        if not _EXPORT_FN.search(f.read_text(encoding=READ_ENC)):
            continue
        if not f.with_name(f"{f.stem}.test.ts").exists():
            bad.append(f"{rel}: 대응 행동 테스트 없음 — {f.stem}.test.ts 를 같은 자리에 작성")
    return bad


def check_ui_component_test_pairing(ui_files: list[Path]) -> list[str]:
    """모든 .tsx 에 같은 디렉토리·같은 이름의 렌더 테스트가 없으면 위반."""
    bad: list[str] = []
    for f in ui_files:
        rel = _rel(f)
        if f.suffix != ".tsx" or rel.endswith(".test.tsx"):
            continue
        if not f.with_name(f"{f.stem}.test.tsx").exists():
            bad.append(f"{rel}: 대응 렌더 테스트 없음 — {f.stem}.test.tsx 를 같은 자리에 작성")
    return bad
