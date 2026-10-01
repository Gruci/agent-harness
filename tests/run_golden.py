"""tests/run_golden.py — 픽스처를 검사기로 돌려 정답지와 대조한다.

검사기는 `git ls-files` 로 대상을 모으므로 픽스처가 git 레포여야 한다. 중첩 레포를 만들지
않으려고 매번 임시 디렉토리에 복사해 거기서 돌린다.

  python -X utf8 tests/run_golden.py            대조 — 다르면 diff 출력 후 exit 1
  python -X utf8 tests/run_golden.py --update   현재 출력을 정답지로 저장
  python -X utf8 tests/run_golden.py --bare     스택 미선택·첫 코드 분류 대기
  python -X utf8 tests/run_golden.py --go       Go 프로젝트
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FIXTURE = HERE / "fixtures" / "miniproj"
GOLDEN = HERE / "golden" / "full.txt"
# 스택과 그래프가 아직 정해지지 않은 첫날 상태(schema 3)에서 나오는 결정 요청의 정답지.
GOLDEN_BARE = HERE / "golden" / "bare.txt"
# Go 구문 검사는 지원하지 않아 [TOOL]로 나오고, 완료 검증을 통과할 수 없다.
FIXTURE_GO = HERE / "fixtures" / "goproj"
GOLDEN_GO = HERE / "golden" / "go.txt"


def _ensure_fixtures() -> None:
    """픽스처 프로파일이 없거나 정본과 다르면 다시 짓는다.

    픽스처 `.gitignore` 가 `harness_profile.py` 를 제외하는데, 이 규칙이 바깥 레포에도 적용된다.
    그래서 픽스처 프로파일은 한 번도 커밋된 적이 없고 clone 직후에는 없다. 프로파일이 없으면
    전 게이트 대조가 프로파일 없는 상태로 돌아 `--bare` 와 같은 출력을 낸다. 정답지와 달라서
    실패는 하지만, 사람 눈에는 "게이트 수십 건이 사라졌다"는 diff 로 보여 원인을 게이트에서
    찾게 된다. **평가기의 절반이 아무 경고 없이 꺼지는 경로다.**

    내용의 정본은 `tests/fixture_files.py` 와 `tests/fixture_go.py` 이므로 다시 지으면 된다.
    """
    sys.path.insert(0, str(HERE))
    from fixture_files import FILES
    from fixture_go import FILES as GO_FILES
    expected = ((FIXTURE, FILES), (FIXTURE_GO, GO_FILES))
    if all((fixture / "harness_profile.py").exists() and
           (fixture / "harness_profile.py").read_text(encoding="utf-8") == files["harness_profile.py"]
           for fixture, files in expected):
        return
    sys.path.insert(0, str(HERE))
    import build_fixture                 # noqa: E402  (경로 삽입 후에만 import 가능)

    print("[픽스처] 프로파일을 현재 정본과 일치하도록 다시 짓는다")
    build_fixture.main()


def prepare_graph(work: Path, syntax: str) -> None:
    """Use a recorded fixture decision, not an unverified approved boolean."""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(HERE))
    from kernel import feature_map, graph_workflow
    from build_fixture import component_graph

    directory = work / "docs/architecture"
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "docs/architecture/components.schema.json", directory)
    graph = component_graph(syntax)
    proposal = graph_workflow.propose(work, graph, "Review the regression fixture boundaries", "golden")
    graph_workflow.decide(work, proposal["id"], "approve", "Approve these fixture boundaries",
                          "fixture://golden/user-decision")
    graph_workflow.apply(work, proposal["id"])
    feature_map.generate(work)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=cwd, check=True,
                   capture_output=True, text=True)


def capture(checker_dir: Path, bare: bool = False, fixture: Path | None = None,
            plugin: bool = False) -> str:
    """픽스처와 검사기를 임시 레포에 준비하고 전체 검사 출력을 받는다.

    bare=True는 스택을 아직 고르지 않은 상태다. 이때 첫 코드는 분류 결정 없이 통과하면 안 된다.
    plugin=True 는 플러그인 설치다. 커널을 복사하지 않고 이 레포의 커널이 픽스처를 밖에서 검사한다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "proj"
        if bare:
            work.mkdir()
            (work / "harness_profile.py").write_text("PROFILE_SCHEMA = 1\nARCH = 'headless'\n", encoding="utf-8")
            (work / "first.rb").write_text("puts 'classification pending'\n", encoding="utf-8")
        else:
            shutil.copytree(fixture or FIXTURE, work)
            if fixture != FIXTURE_GO:
                (work / "unclassified.py").write_text("VALUE = 1\n", encoding="utf-8")

        if plugin:
            command = [sys.executable, "-X", "utf8", str(checker_dir)]
        else:
            shutil.copytree(checker_dir, work / "kernel", ignore=shutil.ignore_patterns("__pycache__"))
            command = [sys.executable, "-X", "utf8", "-m", "kernel.runner"]
        if not bare:
            command.append("--verify")

        _git(work, "init", "-q")
        _git(work, "add", "-A")
        if not bare:
            prepare_graph(work, "go" if fixture == FIXTURE_GO else "python")

        done = subprocess.run(command, cwd=work, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        body = done.stdout
        if done.stderr.strip():
            body += "\n--- stderr ---\n" + done.stderr
        return f"exit={done.returncode}\n{body}".replace(str(work), "<fixture>")


def assert_meaningful(actual: str, bare: bool, go: bool) -> None:
    """Reject broken setup snapshots before they can replace useful regressions."""
    if "Traceback" in actual or "profile_shape)" in actual:
        raise ValueError("Fixture setup failed; do not accept this as a golden")
    required = ("exit=3", "needs_decision") if bare else (
        ("exit=2", "component_classification", "Component syntax analysis", "[TOOL]") if go else
        ("exit=2", "component_classification", "component_dependencies", "unclassified.py", "private module bypass"))
    missing = [marker for marker in required if marker not in actual]
    if missing:
        raise ValueError(f"Regression evidence missing: {missing}")


def main(argv: list[str]) -> int:
    checker_dir = REPO / "kernel"
    if not FIXTURE.exists():
        print("픽스처가 없다 — 먼저 tests/build_fixture.py 를 돌려라", file=sys.stderr)
        return 2
    _ensure_fixtures()

    bare, go = "--bare" in argv, "--go" in argv
    if go:
        golden, fixture, label = GOLDEN_GO, FIXTURE_GO, "Go 프로젝트"
    elif bare:
        golden, fixture, label = GOLDEN_BARE, FIXTURE, "스택 미선택·첫 코드 분류 대기"
    else:
        golden, fixture, label = GOLDEN, FIXTURE, "전 게이트"
    actual = capture(checker_dir, bare=bare, fixture=fixture)
    assert_meaningful(actual, bare, go)

    if "--update" in argv:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
        counts = {tag: sum(1 for ln in actual.splitlines() if ln.startswith(f"[{tag}]"))
                  for tag in ("FAIL", "OK", "SKIP", "REPORT")}
        print(f"정답지 저장: {golden}  ({label})")
        print("  " + " · ".join(f"[{tag}] {n}" for tag, n in counts.items()))
        return 0

    if not golden.exists():
        print("정답지가 없다 — --update 로 먼저 만들어라", file=sys.stderr)
        return 2

    expected = golden.read_text(encoding="utf-8")
    if actual == expected:
        print(f"정답지 일치 ({checker_dir.name} · {label})")
        return 0

    print("정답지와 다르다 — 아래가 바뀐 줄이다:\n", file=sys.stderr)
    for line in difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="golden", tofile="actual", lineterm="",
    ):
        print(line, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
