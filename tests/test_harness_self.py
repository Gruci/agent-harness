"""tests/test_harness_self.py — 하네스 자체의 설치·저하·체크아웃·메타데이터 테스트.

`test_hooks.py` 는 사고가 난 뒤에 추가한 회귀 테스트다. 이 파일은 **사고가 나기 전에** 미리 막는 테스트다.
다른 에이전트 도구가 이미 막아 둔 실패 경로 가운데 이 하네스에도 해당하는 것을 사고 전에 옮겨 왔다.
괄호 안은 그 도구의 원본 테스트 이름이다.

  fresh 설치     clone 직후 install 두 번이 초록불로 끝나고 남의 상태 파일이 안 남는가
                 (package smoke rejects repository-only artifacts)
  훅 저하        페이로드가 깨져도 차단(exit 2)이 아닌가 (degraded: fails friendly)
  검사기 크래시  커널이 터졌을 때 "규칙 위반"으로 포장하지 않는가 (malformed input is one
                 clean machine object without a stack)
  프로파일 모양  튜플 자리의 문자열·이름 오타가 [FAIL] 로 뜨는가 (field as a string fails
                 friendly · rejects unknown fields)
  오타 옵션      설치 스크립트가 모르는 옵션을 거절하는가 (rejects a mistyped option instead of
                 writing a file named after it)
  CRLF           LF·CRLF 체크아웃에서 러너 출력이 같은가 (checkout-line-endings)
  frontmatter    스킬·에이전트 name 이 실물과 같고 description 이 1024자 안인가 (skill-metadata)
  화면 린터      ESLint 설정이 픽스처 위반 6종을 각각 잡고 면제 파일과 깨끗한 파일은 안 잡는가.
                 골든은 이 검사를 [TOOL] 로 고정해 검출을 증명하지 못하므로 여기서 대신 확인한다
  영수증 캐시    영수증 해시가 정본과 같으면 node 없이도 엔진 진단이 OK 인가
  ⑱ 문구 훅      LLM 으로 UI 문구를 판정하는 훅(check_ui_copy)이 규칙 지도에서 차단(security) 노드가 아닌가
  --file 모드     정본 MD 하나의 작성 시점 검사에 전역 REPORT 가 섞이지 않는가

실행: `python -X utf8 tests/test_harness_self.py`
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HOOKS = REPO / ".claude" / "hooks"
TEXT_SUFFIXES = (".py", ".md", ".ts", ".tsx", ".txt", ".json", ".gitignore", ".toml", ".cfg")

# 페이로드로 판정하는 훅만. Stop 훅 중 전량 검사를 도는 것은 페이로드와 무관해 뺀다.
PAYLOAD_HOOKS = ("check_file_rules", "check_bash_write", "check_pretool",
                 "check_workflow_script", "check_context_diet", "check_agent_return",
                 "check_context_growth", "check_editing_lock")

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def _run(cmd: list[str], cwd: Path, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), input=stdin, capture_output=True,
                          timeout=600)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t", *args),
                   cwd=str(cwd), check=True, capture_output=True)


def test_fresh_install_is_green() -> None:
    """clone 직후 프리셋 설치 → 동결 설치가 exit 0 이고 초록불 문구로 끝난다.

    하네스 자기 프로파일이 딸려 오는 것을 install 이 교체하는 경로까지 포함한다.
    """
    # Exercise the current checkout, including new implementation files before git add.
    checkout_files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=str(REPO), capture_output=True, check=True,
    ).stdout.decode("utf-8").split("\0")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "proj"
        for rel in dict.fromkeys(checkout_files):
            if not rel or rel.startswith("docs/tasks/"):
                continue
            src = REPO / rel
            if not src.is_file():
                continue
            dst = work / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        _git(work, "init", "-q")
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", "init")

        first = _run([sys.executable, "-X", "utf8", "harness_install.py"], work)
        assert first.returncode == 0, first.stdout.decode("utf-8", "replace")
        assert (work / "harness_profile.py").exists(), "프리셋 프로파일이 안 만들어졌다"

        second = _run([sys.executable, "-X", "utf8", "harness_install.py"], work)
        out = second.stdout.decode("utf-8", "replace")
        assert second.returncode == 0, out
        assert "설치 완료" in out, "동결 후 검증이 초록불이 아니다:\n" + out
        assert (work / "harness_trace.jsonl").read_text(encoding="utf-8").strip() == "", (
            "하네스 레포 자신의 관찰 기록이 새 프로젝트에 딸려갔다")
        assert not (work / "harness_surface.txt").exists(), "하네스 자신의 표면 동결본이 딸려갔다"
        assert not (work / "docs" / "architecture").exists(), "하네스 자신의 그림이 새 프로젝트에 딸려갔다"

        typo = _run([sys.executable, "-X", "utf8", "harness_install.py", "--dryrun"], work)
        assert typo.returncode == 2, "오타 옵션 --dryrun 이 거절되지 않고 실행됐다"


def test_runner_reports_profile_shape() -> None:
    """튜플 자리에 들어간 문자열과 설정 이름 오타가 [FAIL] 프로파일 형식으로 뜬다. 검사 범위가 경고 없이 사라지는 것을 막는다."""
    sys.path.insert(0, str(HERE))
    import run_golden                       # noqa: E402  (경로 삽입 후에만 import 가능)

    run_golden._ensure_fixtures()
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "shape"
        shutil.copytree(run_golden.FIXTURE, fixture,
                        ignore=shutil.ignore_patterns("__pycache__", ".git"))
        with (fixture / "harness_profile.py").open("a", encoding="utf-8") as out:
            out.write('\nLAYER = {"read": "db/reads"}\nSCOPE = {"exclude_all": "tests/"}\n')
        output = run_golden.capture(REPO / "kernel", fixture=fixture)
    assert "[FAIL] 프로파일 형식 (profile_shape)" in output, output
    assert "모르는 설정 이름 LAYER" in output, output
    assert "SCOPE['exclude_all'] 는 튜플이어야 한다" in output, output


def test_diagram_engine_delivers_harness_architecture() -> None:
    """실제 엔진으로 하네스 자신의 architecture 정본을 임시 디렉토리에 deliver 하고 showcase 검사가 9/9 인지 본다.

    골든은 엔진 호출 결과를 [TOOL] 로 고정하므로 엔진이 실제로 도는지는 여기서만 확인한다.
    node 가 없으면 skipped 로 출력하고 통과로 처리하지 않는다. 건너뛴 테스트는 통과가 아니다.
    """
    sys.path.insert(0, str(REPO))
    from kernel import diagram                # noqa: E402  (경로 삽입 후에만 import 가능)

    source = REPO / "docs" / "architecture" / "harness.architecture.json"
    assert source.exists(), "하네스 자신의 architecture 정본이 없다"
    if not diagram.node_path():
        print("  [SKIPPED] node 없음 — 엔진 실물 테스트를 건너뛴다(통과 아님)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        receipt = diagram.validate("architecture", source)
        assert receipt.get("ok"), "\n".join(diagram.diagnostics_lines(receipt))
        out = Path(tmp) / "harness.html"
        engine = diagram._run(["deliver", "architecture", str(source), str(out), "--repo-root", str(REPO)])
        validation = engine.get("validation") or {}
        assert engine.get("ok") and validation.get("checksPassed") == validation.get("checkCount"), (
            "\n".join(diagram.diagnostics_lines(engine)))
        assert "harness-source-evidence-data" in out.read_text(encoding="utf-8"), "소스 증거가 HTML 에 안 실렸다"


def test_rules_map_matches_wiring() -> None:
    """규칙 지도는 settings.json 의 훅 연결에서 만들어진다. 훅 항목 수와 노드 수가 같고, 노드마다 소스가 있어야 한다."""
    sys.path.insert(0, str(REPO))
    from kernel.diagram import rules          # noqa: E402  (경로 삽입 후에만 import 가능)

    entries = rules._entries()
    doc = rules.build()
    nodes = doc["nodes"]
    assert len(nodes) == len(entries), f"훅 {len(entries)}개인데 노드 {len(nodes)}개"
    assert all(node.get("sources") for node in nodes), "소스 없는 노드가 있다"
    assert all(0 <= int(node["col"]) <= rules.MAX_COL for node in nodes), "col 상한을 넘겼다"
    lane_ids = {lane["id"] for lane in doc["lanes"]}
    assert all(node["lane"] in lane_ids for node in nodes), "레인 없는 노드"


def test_harness_map_catches_ghost_rows() -> None:
    """실물은 없어지고 지도에만 남은 항목(유령 행)을 잡는다. 안내 문구에 섞인 실제 파일명은 잡지 않는다(역방향)."""
    sys.path.insert(0, str(REPO))
    from kernel.gates import md_graph            # noqa: E402  (경로 삽입 후에만 import 가능)

    text = ("## Claude 훅 실행 순서\n"
            "| ① | Stop | `check_live.py` | 살아 있는 훅 |\n"
            "| ② | Stop | `check_gone.py` | 지워진 훅 |\n"
            "| ③ | SessionStart | 프로파일 검사 | `harness_profile.py` 없음 |\n"
            "## 에이전트\n"
            "| 이름 | 용도 |\n"
            "| `qa` | 산 에이전트 — 설명 칸의 `backend` 는 이름이 아니다 |\n"
            "| `ghosty` | 지워진 에이전트 |\n")
    actuals = {"훅": {"check_live.py"}, "에이전트": {"qa"}, "스킬": set()}
    ghosts = md_graph._map_ghosts(text, actuals, live={"harness_profile.py"})

    assert any("check_gone.py" in g for g in ghosts), "지워진 훅을 못 잡았다"
    assert any("ghosty" in g for g in ghosts), "지워진 에이전트를 못 잡았다"
    assert not any("harness_profile.py" in g for g in ghosts), "실존 파일 안내를 유령으로 오인"
    assert not any("backend" in g for g in ghosts), "표 설명 칸의 이름을 지도 항목으로 오인"
    assert len(ghosts) == 2, f"유령 2건이어야 하는데 {ghosts}"


def test_runner_leaves_tree_clean() -> None:
    """전 게이트를 돌려도 git 이 추적하는 파일은 하나도 바뀌지 않는다. 게이트는 판정만 한다(`dev/LESSONS.md` §23).

    검사 48(아키텍처 그림 1:1 대조)이 엔진을 호출하면서 정본의 revision 을 다시 써서,
    Stop 훅이 커밋된 그림 파일을 바꿔 놓은 적이 있다.
    """
    before = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO), capture_output=True,
                            text=True, encoding="utf-8").stdout
    _run([sys.executable, "-X", "utf8", "-m", "kernel.runner"], REPO)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO), capture_output=True,
                           text=True, encoding="utf-8").stdout
    assert before == after, "러너가 작업 트리를 바꿨다 — 게이트가 파일을 쓴다:\n" + after


def test_hook_reports_kernel_crash_as_gate_error() -> None:
    """공통 훅의 실제 크래시 경로가 저장 경고와 종료 차단을 구분한다."""
    done = _run([sys.executable, "-X", "utf8", str(HERE / "test_shared_harness.py"),
                 "SharedHookTests.test_runner_crash_is_not_a_code_violation"], REPO)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def test_hooks_do_not_block_on_broken_payload() -> None:
    """깨진 stdin 에 exit 2 를 내는 훅이 없어야 한다. 훅이 막아 버리면 복구에 써야 할 바로 그 도구가 차단된다.

    훅은 막을 때 `harness_trace.jsonl` 에 관찰 기록을 남긴다. 테스트가 일부러 만든 실패는 관찰이 아니므로
    기록을 되돌린다. 그러지 않으면 회고가 테스트 실행 횟수를 실제 마찰 빈도로 잘못 읽는다.
    """
    trace = REPO / "harness_trace.jsonl"
    before = trace.read_bytes() if trace.exists() else None
    try:
        for name in PAYLOAD_HOOKS:
            done = _run([sys.executable, "-X", "utf8", str(HOOKS / f"{name}.py")], REPO,
                        stdin=b"this is not json")
            assert done.returncode != 2, (
                f"{name}: 페이로드 파싱 실패를 차단으로 냈다\n"
                + done.stderr.decode("utf-8", "replace"))
    finally:
        if before is not None:
            trace.write_bytes(before)


def _copy_with_eol(src: Path, dst: Path, eol: bytes) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    for path in dst.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        body = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(body.replace(b"\n", eol))


def test_runner_output_same_for_lf_and_crlf() -> None:
    """LF 체크아웃과 CRLF 체크아웃에서 전 게이트 출력이 바이트 단위로 같다."""
    sys.path.insert(0, str(HERE))
    import run_golden                       # noqa: E402  (경로 삽입 후에만 import 가능)

    run_golden._ensure_fixtures()
    outputs: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for label, eol in (("lf", b"\n"), ("crlf", b"\r\n")):
            fixture = Path(tmp) / label
            _copy_with_eol(run_golden.FIXTURE, fixture, eol)
            outputs[label] = run_golden.capture(REPO / "kernel", fixture=fixture)
    assert outputs["lf"] == outputs["crlf"], (
        "LF 와 CRLF 에서 러너 출력이 다르다. Windows 에서는 통과하고 CI 에서는 깨지는 경로다\n"
        + "\n".join(
            line for line in outputs["crlf"].splitlines()
            if line not in outputs["lf"].splitlines()))


def _frontmatter(path: Path) -> dict[str, str]:
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert match, f"{path}: frontmatter 가 없다"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


MAX_DESCRIPTION_CHARS = 1024     # 일부 런타임이 여기서 자른다 — 뒤쪽 트리거 문구가 사라진다


def _description(path: Path) -> str:
    """`description: 한 줄` 과 `description: >` 블록 둘 다 본문으로 편다."""
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    lines = match.group(1).splitlines() if match else []
    parts: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("description:"):
            inside = True
            parts.append(line.partition(":")[2].strip().lstrip(">").strip())
        elif inside and line.startswith((" ", "\t")):
            parts.append(line.strip())
        elif inside:
            break
    return " ".join(part for part in parts if part)


def test_skill_and_agent_frontmatter() -> None:
    """name 은 스킬이면 디렉토리 이름, 에이전트면 파일명과 같아야 한다. description 은 비어 있지 않고 길이 상한 안이어야 한다.

    검사 28(하네스 지도 대조)과 검사 29(모델 정책 대조)는 지도 등록과 모델 정책만 본다.
    이름이 어긋나면 스킬이 아무 경고 없이 뜨지 않는다.
    """
    for skill in sorted((REPO / ".claude" / "skills").glob("*/SKILL.md")):
        fields = _frontmatter(skill)
        assert fields.get("name") == skill.parent.name, (
            f"{skill}: name={fields.get('name')!r} ≠ 디렉토리 {skill.parent.name!r}")
        description = _description(skill)
        assert description, f"{skill}: description 이 비어 있다"
        assert len(description) <= MAX_DESCRIPTION_CHARS, (
            f"{skill}: description {len(description)}자 — {MAX_DESCRIPTION_CHARS}자에서 잘리는 런타임이 있다")
    for agent in sorted((REPO / ".claude" / "agents").glob("*.md")):
        fields = _frontmatter(agent)
        assert fields.get("name") == agent.stem, (
            f"{agent}: name={fields.get('name')!r} ≠ 파일명 {agent.stem!r}")
        assert fields.get("description"), f"{agent}: description 이 비어 있다"


UILINT = REPO / "tests" / "fixtures" / "uilint"
EXPECTED_UI = {                       # slug → (파일, 행) — fixture_files.py 의 위반 1건씩
    "ts_any": ("src/anyts.ts", 1), "raw_fetch": ("src/RawFetch.tsx", 2),
    "hex_literal": ("src/Hex.tsx", 1), "responsive": ("src/Fixed.tsx", 1),
    "browser_api": ("src/Storage.tsx", 1), "hash_nav": ("src/HashNav.tsx", 2),
}


def _ensure_uilint() -> None:
    """`node_modules` 가 없으면 `npm ci` 를 돌린다. 픽스처 프로파일을 스스로 다시 만드는 것(`dev/LESSONS.md` §18)과 같은 방식이다. npm 이 없으면 그 사실을 알리고 실패한다."""
    sys.path.insert(0, str(REPO))
    from kernel import linters                # noqa: E402  (경로 삽입 후에만 import 가능)

    if linters.ui_eslint_bin(UILINT):
        return
    npm = shutil.which("npm")
    assert npm, "npm 없음 — 화면 린터 검출 테스트는 node 가 있어야 돈다"
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=str(UILINT), check=True,
                   capture_output=True, timeout=600)


def test_ui_lint_detects_fixture_violations() -> None:
    """설정 파일이 픽스처 위반 6종을 각각 잡고, 래퍼 정본과 깨끗한 파일은 잡지 않는다."""
    _ensure_uilint()
    from kernel import framework, linters     # noqa: E402  (_ensure_uilint 가 경로를 넣는다)

    found = linters.eslint_report(UILINT, [UILINT / "src"], {"browser_api": ["src/platform.ts"]}, "토큰",
                                  framework.load_one("react"))
    for slug, (path, line) in EXPECTED_UI.items():
        hits = [v for v in found[slug] if v.startswith(f"tests/fixtures/uilint/{path}:{line}:")]
        assert hits, f"{slug}: {path}:{line} 을 못 잡았다 — {found[slug]}"
    assert not any("platform.ts" in v for v in found["browser_api"]), "래퍼 정본이 면제되지 않았다"
    assert not any("Consumer.tsx" in v for vs in found.values() for v in vs), "깨끗한 파일을 잡았다"


def test_engine_skipped_when_receipt_fresh() -> None:
    """영수증 해시가 정본과 같으면 node 없이도 엔진 진단이 OK 다. 엔진을 다시 호출하지 않는다는 증명이다."""
    sys.path.insert(0, str(REPO))
    from kernel.gates import arch_diagram     # noqa: E402  (경로 삽입 후에만 import 가능)

    with mock.patch.dict(os.environ, {"HARNESS_DIAGRAM_ENGINE": "off"}):
        sections = arch_diagram.engine_sections()
    assert sections and all(skip is None and not found for _s, _t, found, skip in sections), sections


def test_ui_copy_is_warning_tier() -> None:
    """LLM 판정 훅은 차단 노드가 아니다 — 규칙 지도에서 backend(경고) 타입이어야 한다."""
    sys.path.insert(0, str(REPO))
    from kernel.diagram import rules          # noqa: E402  (경로 삽입 후에만 import 가능)

    node = next(n for n in rules.build()["nodes"] if n["id"] == "stop-ui_copy")
    assert node["type"] == "backend", node


def test_file_mode_prints_no_global_reports() -> None:
    """정본 MD 하나의 작성 시점 검사에 전역 REPORT(경로 참조·stale 노드)가 섞이지 않는다."""
    done = subprocess.run([sys.executable, "-X", "utf8", "-m", "kernel.runner", "--file", "dev/LESSONS.md"],
                          cwd=str(REPO), capture_output=True, text=True, encoding="utf-8")
    assert "실존하지 않는 경로 참조" not in done.stdout and "revision 이후 바뀜" not in done.stdout, done.stdout


def demo() -> None:
    for check in (test_skill_and_agent_frontmatter,
                  test_hook_reports_kernel_crash_as_gate_error,
                  test_hooks_do_not_block_on_broken_payload,
                  test_runner_reports_profile_shape, test_diagram_engine_delivers_harness_architecture,
                  test_runner_leaves_tree_clean, test_rules_map_matches_wiring,
                  test_ui_lint_detects_fixture_violations, test_engine_skipped_when_receipt_fresh,
                  test_ui_copy_is_warning_tier, test_file_mode_prints_no_global_reports,
                  test_runner_output_same_for_lf_and_crlf, test_fresh_install_is_green):
        check()
        print(f"  [OK] {check.__name__}")
    print("하네스 자체 테스트 모두 통과")


if __name__ == "__main__":
    demo()
