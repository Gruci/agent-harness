"""tests/test_release_identity.py — 배포 정체(버전 표기)가 모든 곳에서 같은가 (release-identity).

`KERNEL_VERSION` 은 clone 해 간 프로젝트가 `--check-update` 로 원본 레포와 대조하는 상수다.
사람은 그 숫자를 README 두 개에서 읽는다. 두 README 는 서로의 번역이라 같은 내용이어야 한다.
한 곳만 고치면 버전 표기가 둘로 갈라지는데도 **코드는 멀쩡히 돈다**. 그래서 테스트로 고정한다.

  머리 버전    두 README 머리와 KERNEL_VERSION 이 같은 숫자인가
  변경 이력    두 README 의 버전 행 목록이 같고, 맨 위가 현재 버전인가
  매니페스트   플러그인·마켓플레이스 버전이 KERNEL_VERSION 과 같고, 훅·스킬 경로가 실존하는가

실행: `python -X utf8 tests/test_release_identity.py`
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
READMES = ("README.md", "README.ko.md")
PLUGIN_DIR = REPO / ".claude-plugin"
_PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"']+)")

_VERSION = re.compile(r"\b[Hh]arness v(\d+\.\d+\.\d+)|하네스 v(\d+\.\d+\.\d+)")
_CHANGELOG_ROW = re.compile(r"^\|\s*\*\*v(\d+\.\d+\.\d+)\*\*\s*\|", re.M)


def test_readme_versions_agree() -> None:
    """두 README 머리의 버전과 커널 상수, 셋이 모두 같다."""
    sys.path.insert(0, str(REPO))
    from kernel import KERNEL_VERSION       # noqa: E402  (경로 삽입 후에만 import 가능)

    heads: set[str] = set()
    for name in READMES:
        match = _VERSION.search((REPO / name).read_text(encoding="utf-8"))
        assert match, f"{name}: 머리에 하네스 버전이 없다"
        heads.add(match.group(1) or match.group(2))
    assert heads == {KERNEL_VERSION}, \
        f"머리 버전이 KERNEL_VERSION({KERNEL_VERSION}) 과 다르다: {sorted(heads)}"


def test_readme_changelogs_agree() -> None:
    """변경 이력 목록이 두 README 에서 같고 맨 위가 현재 버전이다.

    머리만 대조하면 이력이 갈라진 것을 못 잡는다 — 실제로 한쪽은 v3.0.0 까지 적고 다른
    쪽은 v3.3.0 을 "초기 공개 버전"이라 적은 채로 배포됐다.
    """
    sys.path.insert(0, str(REPO))
    from kernel import KERNEL_VERSION       # noqa: E402  (경로 삽입 후에만 import 가능)

    logs = {name: tuple(_CHANGELOG_ROW.findall((REPO / name).read_text(encoding="utf-8")))
            for name in READMES}
    assert all(logs.values()), f"변경 이력 표를 못 찾았다: {[(k, len(v)) for k, v in logs.items()]}"
    assert len(set(logs.values())) == 1, \
        f"두 README 의 변경 이력이 다르다: {[(k, list(v)) for k, v in logs.items()]}"
    assert logs[READMES[0]][0] == KERNEL_VERSION, \
        f"변경 이력 맨 위가 현재 버전이 아니다: {logs[READMES[0]][0]} ≠ {KERNEL_VERSION}"


def test_plugin_manifest_matches_kernel() -> None:
    """매니페스트 버전은 커널 상수와 같고, 매니페스트가 가리키는 훅·스킬·훅 명령의 파일은 전부 있다."""
    sys.path.insert(0, str(REPO))
    from kernel import KERNEL_VERSION       # noqa: E402  (경로 삽입 후에만 import 가능)

    plugin = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((PLUGIN_DIR / "marketplace.json").read_text(encoding="utf-8"))
    versions = {plugin["version"], *(entry["version"] for entry in market["plugins"])}
    assert versions == {KERNEL_VERSION}, f"매니페스트 버전이 KERNEL_VERSION({KERNEL_VERSION}) 과 다르다: {sorted(versions)}"
    for skill in plugin["skills"]:
        assert (REPO / skill / "SKILL.md").is_file(), f"plugin.json 의 스킬 {skill} 에 SKILL.md 가 없다"
    hooks_file = REPO / plugin["hooks"]
    assert hooks_file.is_file(), f"plugin.json 의 hooks {plugin['hooks']} 가 없다"
    hooks = json.loads(hooks_file.read_text(encoding="utf-8"))["hooks"]
    commands = [hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]]
    assert commands, "hooks.json 에 명령이 없다"
    for command in commands:
        for rel in _PLUGIN_PATH.findall(command):
            assert (REPO / rel).exists(), f"hooks.json 명령이 없는 파일을 가리킨다: {rel}"


def demo() -> None:
    for check in (test_readme_versions_agree, test_readme_changelogs_agree, test_plugin_manifest_matches_kernel):
        check()
        print(f"  [OK] {check.__name__}")
    print("배포 정체 테스트 전건 통과")


if __name__ == "__main__":
    demo()
