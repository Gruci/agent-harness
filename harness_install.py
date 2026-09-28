"""harness_install.py — 프로파일 설치와 검사 진단.

새 프로젝트는 스택이 정해지지 않은 템플릿 프로파일 하나에서 시작한다.
첫 코드를 쓰기 전에 사용자와 함께 분류 그래프와 언어별 검사 도구를 구성한다.
설치는 기존 위반을 자동으로 동결(baseline 등록)하지 않고, 프로젝트 정본 파일도 지우지 않는다.
이미 있는 파일 단위 baseline은 --prune으로 줄일 수 있다.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

from kernel import KERNEL_VERSION, UPSTREAM, UPSTREAM_BRANCH, profile, runner
from kernel.context import ROOT
from kernel.gates import api_types

PRESET_DIR = ROOT / "profiles"
DEFAULT_PRESET = "_template"

BASELINE_HEADER = """# harness_baseline.txt — 하네스 설치 시점에 이미 있던 위반의 동결 목록.
#
# 형식: <게이트 slug>\\t<파일 경로>
# 래칫: 이 파일은 줄어들기만 해야 한다. 파일을 고쳤으면 해당 행을 지운다.
#       (`python -X utf8 harness_install.py --prune` 이 고쳐진 행을 자동으로 걷어낸다.)
# 신규 파일은 여기 없으므로 처음부터 전 게이트를 통과해야 한다 — 그게 이 설계의 목적이다.
"""

# 존재해야 게이트가 켜지는 동결 파일. 없으면 그 게이트가 [SKIP] 이다.
API_BASELINE_HEADER = "# 설치 시점에 동결한 항목 없음 — 필수 배열 필드가 새로 생기면 걸린다\n"

# ── 하네스 자체 업데이트 ────────────────────────────────────────────────────────
#
# clone 해 간 프로젝트는 원류(하네스 원본 레포)와 git 연결이 끊겨 있다. 그래서 커널 개선을 받으려면
# 손으로 옮겨 오는 "역이식"밖에 없었다. `--check-update` 는 원류 기본 브랜치의 KERNEL_VERSION 만 읽어
# 알려 주고, `--upgrade` 는 하네스가 소유한 파일만 갈아끼운다. 프로파일·MD·harness_gates/·docs/ 는
# 프로젝트 소유라 절대 건드리지 않는다.
UPGRADE_DIRS = ("kernel", ".claude/hooks")           # 원류 파일 갱신, 프로젝트 추가 파일 보존
UPGRADE_PRESET_DIR = "profiles"                      # 최상위 프리셋 *.py 만 덮어쓴다 — lang/·arch/ 오버라이드는 남긴다
_VERSION_RE = re.compile(r'^KERNEL_VERSION\s*=\s*"([^"]+)"', re.M)


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def upstream_version() -> str:
    """원류 기본 브랜치의 KERNEL_VERSION 을 돌려준다. 파일 하나만 내려받고, clone 은 --upgrade 때만 한다."""
    raw = UPSTREAM.replace("https://github.com/", "https://raw.githubusercontent.com/")
    # 캐시를 우회한다 — raw CDN 이 몇 분 전 버전을 돌려주면 최신이라고 잘못 판단한다
    url = f"{raw}/{UPSTREAM_BRANCH}/kernel/__init__.py?t={int(time.time())}"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8", "replace")
    found = _VERSION_RE.search(body)
    return found.group(1) if found else ""


def check_update() -> int:
    try:
        latest = upstream_version()
    except Exception as exc:                                  # 네트워크 오류·404 — 알리기만 하고 끝낸다
        print(f"[UPDATE] 원류 확인 실패 — {exc.__class__.__name__}: {exc}")
        return 2
    if not latest:
        print("[UPDATE] 원류에서 KERNEL_VERSION 을 못 읽었다 — 원류가 아직 버전 상수를 넣기 전의 버전이다")
        return 2
    if _version_tuple(latest) > _version_tuple(KERNEL_VERSION):
        print(f"[UPDATE] 하네스 {KERNEL_VERSION} → {latest} 있음.")
        print("   python -X utf8 harness_install.py --upgrade 가 kernel/ · .claude/hooks/ · profiles/*.py 만 갈아끼운다.")
        print("   harness_profile.py · 정본 MD · harness_gates/ · docs/ 는 안 건드린다. 설치본은 지금 그대로다.")
        return 1
    print(f"[UPDATE] 최신이다 ({KERNEL_VERSION}).")
    return 0


def upgrade() -> int:
    """하네스가 소유한 파일만 교체한다. 되돌리기는 git 에 맡기므로 작업 트리가 깨끗해야 시작한다."""
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8").stdout.strip()
    if dirty:
        print("[UPGRADE] 작업 트리가 깨끗하지 않다 — 커밋하거나 되돌린 뒤 다시 실행하라. 교체는 git 으로 되돌릴 수 있어야 한다.")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "upstream"
        done = subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", UPSTREAM_BRANCH,
                               UPSTREAM, str(target)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            print(f"[UPGRADE] 원류 clone 실패 — {done.stderr.strip()[:300]}")
            return 2
        found = _VERSION_RE.search((target / "kernel" / "__init__.py").read_text(encoding="utf-8"))
        latest = found.group(1) if found else "?"
        for rel in UPGRADE_DIRS:
            shutil.copytree(target / rel, ROOT / rel, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
            print(f"[UPGRADE] {rel}/ 갱신 (프로젝트 추가 파일 보존)")
        for preset in sorted((target / UPGRADE_PRESET_DIR).glob("*.py")):
            shutil.copy2(preset, ROOT / UPGRADE_PRESET_DIR / preset.name)
        print(f"[UPGRADE] {UPGRADE_PRESET_DIR}/*.py 덮어씀 (lang/·arch/ 오버라이드는 그대로)")
    print(f"\n[UPGRADE] {KERNEL_VERSION} → {latest}. 다음 순서:")
    print("   python -X utf8 -m kernel.profile     새로 생긴 프로파일 항목 확인")
    print("   python -X utf8 -m kernel.runner      모든 게이트 다시 검증")
    print("   git diff 로 변경을 검토하라. 설정·스킬·공통 절차는 필요한 항목만 병합한다.")
    # 새 프로세스에서 교체된 커널을 읽는다. 현재 프로세스는 이전 모듈을 캐시하고 있다.
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "kernel.harness_setup"],
                          cwd=ROOT).returncode

def profile_modules() -> list[str]:
    """`--preset` 으로 지정할 수 있는 모든 프로파일. 다른 프로젝트의 프로파일도 포함된다."""
    return sorted(p.stem for p in PRESET_DIR.glob("*.py") if p.stem != "__init__")


def check_install_location() -> str:
    """하네스가 세션 루트에 있는가. 어긋나면 그 사유를 돌려준다(정상이면 빈 문자열).

    훅 command 는 `$(git rev-parse --show-toplevel)/.claude/hooks/...` 다. 하네스가 git 최상위가
    아닌 하위 폴더에 있으면 그 경로에 훅이 없어 훅이 하나도 실행되지 않는다. **이 상태는 화면에 아무것도 나타나지 않는다.**
    검사기가 아예 불리지 않으니 [SKIP] 조차 없다. 하네스가 작동을 멈추는 경우 중 가장 알아채기 어려운 경우다.

    판정은 git 최상위와 대조한다. 레포 루트가 곧 세션 루트라는 보장은 없지만, 하네스가
    레포 안쪽 하위 폴더에 들어가 있는 경우는 확실히 잘못이고, 실제로 그런 사고가 났다.
    """
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        return ""                       # git 밖이면 다른 검사가 이미 잡는다
    top = Path(done.stdout.strip()).resolve()
    if top == ROOT:
        return ""
    try:
        nested = ROOT.relative_to(top).as_posix()
    except ValueError:
        return ""                       # 레포 밖 — 판단 근거 없음
    return nested


def report_install_location() -> bool:
    """설치 위치가 잘못됐으면 고치는 법을 출력한다. 반환은 '계속 진행해도 되는가'."""
    nested = check_install_location()
    if not nested:
        return True
    print("[설치 위치] 하네스가 레포 루트가 아니라 하위 폴더에 있다.\n")
    print(f"   레포 루트 : {ROOT.parents[len(Path(nested).parts) - 1]}")
    print(f"   하네스    : {ROOT}   (= {nested}/)")
    print("\n   이 상태로는 훅이 하나도 안 걸린다. `.claude/settings.json` 의 훅 명령은")
    print("   git 최상위 기준(`$(git rev-parse --show-toplevel)/.claude/hooks/...`)이라, 레포 루트에")
    print("   `.claude/` 가 없으면 전부 실패한다. 그리고 그 실패는 화면에 아무것도 안 남긴다.")
    print("\n   고치는 법 — 하네스 내용물을 레포 루트로 올린다:")
    print(f"       cd {ROOT.parent}")
    print(f"       git mv {nested}/* {nested}/.[!.]* .  2>/dev/null || "
          f"(mv {nested}/* {nested}/.[!.]* . )")
    print(f"       rmdir {nested}")
    print("       python -X utf8 harness_install.py")
    print("\n   레포를 새로 시작하는 경우라면 clone 자체를 프로젝트 폴더로 하는 게 낫다:")
    print("       git clone <url> my-project && cd my-project && rm -rf .git && git init")
    return False


def print_language_report() -> None:
    """이 프로젝트의 언어 설정과, 그 언어팩에 필요한 도구가 설치됐는지 출력한다.

    도구가 없으면 그 검사는 안 도는데, 설치 전에는 그 사실이 설치 화면에 안 나온다.
    온보딩이 이걸 보고 "무엇이 지금 안 지켜지는지"를 사용자에게 말해줘야 한다.
    """
    from kernel import arch, lang, linters

    print(f"쓸 수 있는 언어팩: {' '.join(lang.available())}")
    print(f"쓸 수 있는 아키텍처팩: {' '.join(arch.available())}\n")
    print(f"현재 설정 — LANG={profile.LANG!r} SYNTAX={profile.SYNTAX!r} ARCH={profile.ARCH!r}")
    print(f"   서버 소스: {' '.join(profile.SOURCE_EXT)}")
    print(f"   화면 소스: {' '.join(profile.UI_EXT)}")

    if profile.NOT_APPLICABLE:
        print("\n이 언어·아키텍처에서 해당 없는 검사 (손실 아님):")
        for slug, why in sorted(profile.NOT_APPLICABLE.items()):
            print(f"   {slug:<16} {why}")

    if not profile.LINTERS:
        print("\n위임할 외부 도구 없음.")
    else:
        print("\n외부 도구:")
        for entry in profile.LINTERS:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("slug") or "?")
            absent = linters.missing_tool(entry)
            if absent:
                print(f"   [없음] {name:<14} {absent} 설치 안 됨 — {entry.get('install', '설치 방법이 적혀 있지 않다')}")
            else:
                print(f"   [있음] {name:<14} {' '.join(entry.get('cmd', []))}")
        print("\n없는 도구는 해당 검사가 [TOOL] 로 꺼진 채 돈다. 통과로 처리되지는 않는다.")
    print_stack_report(profile.PACK, [pack for pack in (profile.SERVER, profile.UI) if pack])


def requirement_present(entry: dict) -> bool:
    """REQUIRES 항목의 확인 명령이 exit 0 이면 있는 것이다. 실행 파일이 없거나 응답이 없으면 없는 것이다."""
    try:
        return subprocess.run(list(entry["check"]), capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def analyzer_status(pack: dict) -> tuple[str, str]:
    """(분석기 이름, 상태 한 줄). 팩이 고른 분석기가 지금 이 환경에서 돌 수 있는지를 말한다."""
    from kernel import lang

    kind = lang.analyzer_kind(pack)
    if kind == "python":
        return "표준 ast", "설치 없음"
    if kind == "treesitter":
        grammar = lang.grammar_module(pack) or "?"
        core = "있음" if importlib.util.find_spec("tree_sitter") else "없음"
        found = "있음" if importlib.util.find_spec(grammar) else "없음"
        return "tree-sitter", f"tree_sitter {core} · 문법 {grammar} {found}"
    if kind == "command":
        command = [str(part) for part in pack.get("ANALYZER_CMD") or ()]
        found = "있음" if command and (shutil.which(command[0]) or (ROOT / command[0]).is_file()) else "없음"
        return "외부 분석기", f"{' '.join(command)} — 실행 파일 {found}"
    return "없음", "구문 사실 게이트가 [TOOL] 로 남는다"


def print_stack_report(pack: dict, frameworks: list[dict] | None = None) -> int:
    """언어팩이 고른 분석기와 언어팩·프레임워크팩 REQUIRES 의 설치 상태를 찍고, 없는 도구 수를 돌려준다.

    설치는 여기서 하지 않는다 — 사용자 환경을 바꾸는 일이라 사용자가 결정한다. 하네스 자신은 아무것도 요구하지 않으므로
    이 레포에서는 언제나 0 이어야 한다.
    """
    name, status = analyzer_status(pack)
    print(f"\n구문 분석기: {name} — {status}")
    requires = [entry for source in (pack, *(frameworks or ()))
                for entry in (source.get("REQUIRES") or ()) if isinstance(entry, dict)]
    if not requires:
        print("팩이 요구하는 도구 없음 — 설치 요구 0건.")
        return 0
    missing = 0
    print("팩이 요구하는 도구:")
    for entry in requires:
        if requirement_present(entry):
            print(f"   [있음] {entry['name']:<14} {' '.join(entry['check'])}")
        else:
            missing += 1
            print(f"   [없음] {entry['name']:<14} 설치: {entry['install'] or '설치 안내가 적혀 있지 않다'}")
    print(f"설치 요구 {missing}건. 설치할지는 사용자가 정한다 — 없는 채로는 그 팩이 1급이 아니다.")
    return missing


def presets() -> list[str]:
    """새 프로젝트에 권할 수 있는 프로파일만 돌려준다. `PRESET_SUMMARY` 를 선언한 프로파일이 곧 프리셋이다.

    선언을 요구하는 이유: `profiles/` 에는 특정 프로젝트의 실제 프로파일도 섞여 있다.
    그걸 새 프로젝트에 권하면 다른 프로젝트의 레이어 이름과 어휘를 물려받게 된다.
    """
    return [name for name in profile_modules() if _preset_meta(name)[0]]


def _preset_meta(name: str) -> tuple[str, str]:
    """프리셋의 (한 줄 요약, 언제 고르는지). 없으면 빈 문자열."""
    spec = importlib.util.spec_from_file_location(f"_preset_{name}", PRESET_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        return "", ""
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return "", ""
    return getattr(module, "PRESET_SUMMARY", ""), getattr(module, "PRESET_FITS", "")


def print_presets() -> None:
    """사람이 고를 수 있게 요약과 함께 나열한다.

    이름만 나열하면 무엇이 자기 경우인지 모른다. 스택 이름을 아는 사람만 고를 수 있는 목록은 목록이 아니다.
    """
    print("쓸 수 있는 프리셋:\n")
    for name in presets():
        summary, fits = _preset_meta(name)
        print(f"  {name}")
        if summary:
            print(f"      {summary}")
        if fits:
            print(f"      → {fits}")
        print()
    print("고르기 어려우면 claude 를 켜고 \"하네스 깔아줘\" 라고 하라 — 물어보고 골라준다.")


def install_profile(preset: str) -> bool:
    """프로파일 파일이 없으면 프리셋에서 만든다. 반환값은 새로 만들었는지 여부다.

    하네스 레포를 clone 해 온 경우 하네스 **자신의** 프로파일이 딸려 온다. 그건 이 프로젝트의
    설정이 아니라 하네스가 자기를 검사하려고 둔 파일이고, 레이어가 전부 비어 있어 그대로 두면
    게이트가 전부 꺼진 채로 통과 표시가 뜬다. 그래서 하네스 자신의 프로파일은 없는 것으로 취급해 덮어쓴다.
    """
    if preset not in profile_modules():
        raise ValueError(f"사용할 수 없는 프리셋: {preset}")
    target = ROOT / profile.PROFILE_FILE
    if target.exists() and not profile.IS_HARNESS_SELF:
        print(f"[프로파일] {profile.PROFILE_FILE} 이미 있음 — 건드리지 않는다")
        return False
    if target.exists():
        print("[프로파일] clone 과 함께 딸려 온 하네스 자신의 프로파일을 이 프로젝트의 것으로 교체한다")
        reset_shipped_state()
    shutil.copy2(PRESET_DIR / f"{preset}.py", target)
    print(f"[프로파일] {profile.PROFILE_FILE} 생성 (프리셋 {preset})")
    print("   → 업무 분류를 사용자와 승인하고 언어별 검사 도구를 연결하라.")
    return True


# 하네스 레포 자신의 상태 파일이다. 프로파일과 함께 딸려 오지만 이 프로젝트의 것이 아니다.
# 관찰 기록은 하네스 레포 세션의 기록이라 첫 회고가 엉뚱한 패턴을 읽게 되고, 표면 동결본은 하네스 레포의 면제 목록이다.
SHIPPED_TRACE = "harness_trace.jsonl"
SHIPPED_SURFACE = "harness_surface.txt"


def reset_shipped_state() -> None:
    """하네스 자신의 프로파일을 교체하는 시점에만 부른다. 그 뒤에 쌓이는 것은 이 프로젝트의 기록이다."""
    trace = ROOT / SHIPPED_TRACE
    if trace.exists():
        trace.write_text("", encoding="utf-8")
        print(f"[동봉 상태] {SHIPPED_TRACE} 비움 — 하네스 레포 자신의 관찰 기록이었다")
    surface = ROOT / SHIPPED_SURFACE
    if surface.exists():
        surface.unlink()
        print(f"[동봉 상태] {SHIPPED_SURFACE} 제거 — 하네스 레포 자신의 면제 동결본이었다. "
              f"edit_surface 게이트를 켤 때 이 프로젝트의 표면으로 다시 뜬다")
    # 그림과 그래프 및 스키마는 프로젝트 정본이 섞일 수 있어 자동 삭제하지 않는다.


def install_gate_baselines() -> None:
    path = api_types.BASELINE
    if not path.exists():
        path.write_text(API_BASELINE_HEADER, encoding="utf-8")
        print(f"[동결 파일] {path.name} 생성 — 이게 없으면 해당 게이트가 [SKIP] 이다")


def report_unlisted_layers() -> None:
    """컴포넌트 분류 정본(그래프)이 있는지 알린다. 검사 경로를 채웠다고 분류가 된 것은 아니다."""
    graph = ROOT / profile.COMPONENT_GRAPH
    if not graph.is_file():
        print(f"\n[분류 필요] {profile.COMPONENT_GRAPH} 없음 — 첫 코드 전에 사용자와 분류를 승인하라.")


def _write_baseline(pairs: list[tuple[str, str]]) -> None:
    body = "".join(f"{slug}\t{path}\n" for slug, path in pairs)
    runner.BASELINE_FILE.write_text(BASELINE_HEADER + body, encoding="utf-8")


def _report(pairs: list[tuple[str, str]], label: str) -> None:
    by_gate = Counter(slug for slug, _path in pairs)
    print(f"\n{label} — {len(pairs)}건 (게이트 {len(by_gate)}종)")
    for slug in sorted(by_gate, key=lambda s: (-by_gate[s], s)):
        print(f"   {by_gate[slug]:>4}  {slug}")


def _prune() -> int:
    frozen = runner.load_baseline()
    still_broken = set(runner.collect_all_violations()) & frozen
    removed = sorted(frozen - still_broken)
    _write_baseline(sorted(still_broken))
    _report(removed, "[PRUNE] 고쳐져서 동결 목록에서 뺀 항목")
    print(f"남은 동결 {len(still_broken)}건.")
    return 0


def _parse(argv: list[str]) -> argparse.Namespace:
    # 모르는 옵션은 무시하지 않고 거절한다(argparse 기본 exit 2). `--dryrun` 오타가 실제 설치로 실행돼
    # 동결 파일을 덮어쓰는 것이 실제로 사고가 나는 경로다. `allow_abbrev=False` — 줄임 옵션도 오타와 같이 거절한다.
    parser = argparse.ArgumentParser(prog="harness_install.py", allow_abbrev=False)
    for flag in ("--list", "--doctor", "--prune", "--dry-run", "--check-update", "--upgrade",
                 "--check-agents"):
        parser.add_argument(flag, action="store_true")
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        args = _parse(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    if args.list:
        print_presets()
        return 0

    if args.check_agents:
        from kernel.harness_setup import check_agents

        return check_agents(ROOT)

    if args.check_update:
        return check_update()

    if args.upgrade:
        return upgrade()

    if args.doctor:
        from kernel.harness_setup import check_agents

        print_language_report()
        return check_agents(ROOT)

    # 설치 위치를 가장 먼저 확인한다. 위치가 틀리면 나머지를 다 해도 훅이 하나도 실행되지 않는다.
    if not report_install_location():
        return 2

    if not args.prune and not args.dry_run:
        try:
            created = install_profile(args.preset)
        except ValueError as exc:
            print(f"[프로파일] {exc}")
            return 2
        install_gate_baselines()
        if created:
            print("\n프로파일을 만들었다. 사용자와 스택과 분류 그래프를 정하고 검사 도구를 연결하라.")
            return 0

    if profile.PROFILE_ERRORS:
        for error in profile.PROFILE_ERRORS:
            print(f"[PROFILE] {error}")
        return 2
    report_unlisted_layers()

    if args.prune:
        return _prune()

    current = runner.collect_all_violations()
    if args.dry_run:
        _report(current, "[DRY RUN] 현재 위반 (자동 동결하지 않음)")
        return 0

    _report(current, "[INSTALL] 수정이 필요한 위반")

    # 신규 위반을 동결하지 않고 실제 검증 결과를 반환한다.
    print("\n검증 실행:")
    code = runner.main(["--verify"])
    if code == 0:
        print("\n설치 검증 완료 — 위반을 자동 동결하지 않았다.")

    else:
        print("\n검증을 통과하지 못했다 — 위에 보고된 분류 문제, 검사 설정 문제, 코드 위반을 해결하라.")

    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
