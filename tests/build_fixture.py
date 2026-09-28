"""tests/build_fixture.py — 시험용 미니 프로젝트를 만든다.

게이트마다 위반을 **정확히 1건씩** 심은 가짜 프로젝트다. 이 프로젝트를 검사기로 돌린 출력을
정답지(`tests/golden/full.txt`)로 고정해 두면, 리팩터 뒤 결과가 달라진 줄이 곧 망가진
게이트를 가리킨다. 파일 내용의 정본은 `tests/fixture_files.py` 이고, 이 파일은 디스크에 쓰는 일만 한다.

재생성: python -X utf8 tests/build_fixture.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_files import FILES          # noqa: E402  (경로 삽입 후에만 import 가능)
from fixture_go import FILES as GO_FILES  # noqa: E402

HERE = Path(__file__).resolve().parent
DEST = HERE / "fixtures" / "miniproj"
DEST_GO = HERE / "fixtures" / "goproj"
# 화면 린터가 위반을 잡는지 확인하는 테스트용 npm 프로젝트. 위반 파일은 miniproj 의 frontend/src 와 같은 정본에서 만들어진다.
# package.json 과 package-lock.json 은 손으로 관리하는 정본이라 여기서 만들지 않는다.
DEST_UILINT = HERE / "fixtures" / "uilint"
UI_PREFIX = "frontend/src/"

# 파일 길이 상한 게이트용 — 상한을 정확히 1줄 넘긴다
LONG_FILE = DEST / "utils" / "long_report.py"
LONG_FILL = 399


def write_long_file() -> None:
    lines = ['"""픽스처: 단일 책임을 잃은 파일."""', ""]
    lines += [f"# 채움 {n:03d}" for n in range(LONG_FILL)]
    LONG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_all(dest: Path, files: dict[str, str]) -> None:
    allowed = {DEST.resolve(), DEST_GO.resolve(), (DEST_UILINT / "src").resolve()}
    if dest.resolve() not in allowed:
        raise ValueError(f"Refusing fixture replacement outside explicit targets: {dest}")
    if dest.exists():
        shutil.rmtree(dest)
    for rel, body in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def component_graph(syntax: str) -> dict:
    """Intentional ownership and dependency errors, independent of profile migration."""
    patterns = ["db/**/*.go", "batches/**/*.go", "utils/**/*.go"] if syntax == "go" else [
        "db/**/*.py", "web/**/*.py", "batches/**/*.py", "kofia/**/*.py", "settings.py", "batch_runner.py",
        "frontend/**/*.ts", "frontend/**/*.tsx"]
    components = [{"id": "application", "name": "Application fixture", "category": "fixture",
                   "responsibility": "Exercise classified adapter code", "excludes": ["Domain policy"],
                   "root": ".", "roles": {"adapters": patterns}, "public": [],
                   "state": "implemented", "external": ["os"]}]
    if syntax == "python":
        components.append({"id": "policy", "name": "Policy fixture", "category": "fixture",
                           "responsibility": "Pure policy", "excludes": ["Environment access"],
                           "root": "utils", "roles": {"domain": ["**/*.py"]}, "public": [],
                           "state": "implemented", "external": ["typing"]})
    return {"schema": 1, "revision": 1,
            "categories": [{"id": "fixture", "name": "Fixture", "description": "Gate regression evidence",
                            "roles": ["domain", "adapters"]}],
            "components": components, "edges": [],
            "technology": {"sources": ["**/*.go"] if syntax == "go" else ["**/*.py", "**/*.ts", "**/*.tsx"],
                           "syntax": syntax, "exclude": [{"path": "kernel", "reason": "Checker code"},
                               {"path": "harness_profile.py", "reason": "Checker configuration"},
                               {"path": "tests", "reason": "Test code"}]},
            "role_dependencies": {"domain": ["domain"], "adapters": ["adapters", "domain"]}}


def main() -> int:
    write_all(DEST, FILES)
    write_long_file()
    print(f"픽스처 생성: {DEST}")
    print(f"  파일 {len(FILES) + 1}개")

    write_all(DEST_GO, GO_FILES)
    print(f"픽스처 생성: {DEST_GO}")
    print(f"  파일 {len(GO_FILES)}개")

    ui_files = {rel[len(UI_PREFIX):]: body for rel, body in FILES.items() if rel.startswith(UI_PREFIX)}
    write_all(DEST_UILINT / "src", ui_files)
    print(f"픽스처 생성: {DEST_UILINT / 'src'}")
    print(f"  파일 {len(ui_files)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
