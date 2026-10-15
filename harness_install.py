"""harness_install.py — 프로파일 설치와 검사 진단.

새 프로젝트는 스택이 정해지지 않은 템플릿 프로파일 하나에서 시작한다.
첫 코드를 쓰기 전에 사용자와 함께 분류 그래프와 언어별 검사 도구를 구성한다.
설치는 기존 위반을 자동으로 동결(baseline 등록)하지 않고, 프로젝트 정본 파일도 지우지 않는다.
이미 있는 파일 단위 baseline은 --prune으로 줄일 수 있다.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

from kernel import fresh_repo, preflight, profile, runner, shipped, upgrade
from kernel.context import KERNEL_HOME, ROOT
from kernel.gates import api_types

PRESET_DIR = KERNEL_HOME / "profiles"
DEFAULT_PRESET = "_template"
# 플러그인 설치 — 커널이 프로젝트 밖(플러그인 폴더)에 있다. 업데이트와 배선 검사는 플러그인 런타임의 몫이다.
PLUGIN = KERNEL_HOME != ROOT
PLUGIN_UPDATE = "[UPDATE] Plugin install — upgrade with `/plugin update agent-harness@agent-harness`. --upgrade is for template installs only."
# 편집 표면 동결본. 설치가 프리셋 선언으로 뜬다 — 하네스 레포의 것을 물려받지 않는다(harness_gates/edit_surface.py).
SURFACE_FILE = "harness_surface.txt"

BASELINE_HEADER = """# harness_baseline.txt — baseline of violations that already existed when the harness was installed.
#
# Format: <gate slug>\\t<file path>
# Ratchet: this file may only shrink. When you fix a file, delete its row.
#       (`python -X utf8 harness_install.py --prune` removes fixed rows automatically.)
# New files are not listed here, so they must pass every gate from the start — that is the point of this design.
"""

# 존재해야 게이트가 켜지는 동결 파일. 없으면 그 게이트가 [SKIP] 이다.
API_BASELINE_HEADER = "# Nothing was baselined at install — a new required array field is caught\n"

# 하네스 자체 업데이트는 `kernel/upgrade.py` 다. clone 해 간 프로젝트는 원류와 git 연결이 끊겨 있어 파일마다 원류 이력으로
# 판정한다. 프로파일·MD·harness_gates/·docs/ 는 프로젝트 소유라 절대 건드리지 않는다. 플러그인 설치는 여기서 거절한다.
def _plugin_update(action: object) -> int:
    if PLUGIN:
        print(PLUGIN_UPDATE)
        return 2
    return int(action())   # type: ignore[operator]


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
    print("[INSTALL LOCATION] The harness is in a subfolder, not at the repo root.\n")
    print(f"   repo root : {ROOT.parents[len(Path(nested).parts) - 1]}")
    print(f"   harness   : {ROOT}   (= {nested}/)")
    print("\n   In this state no hook runs. The hook commands in `.claude/settings.json` are relative to")
    print("   the git top level (`$(git rev-parse --show-toplevel)/.claude/hooks/...`), so without `.claude/`")
    print("   at the repo root every one fails. And that failure leaves nothing on screen.")
    print("\n   Fix — move the harness contents up to the repo root:")
    print(f"       cd {ROOT.parent}")
    print(f"       git mv {nested}/* {nested}/.[!.]* .  2>/dev/null || "
          f"(mv {nested}/* {nested}/.[!.]* . )")
    print(f"       rmdir {nested}")
    print("       python -X utf8 harness_install.py")
    print("\n   If you are starting a new repo, it is better to clone straight into the project folder:")
    print("       git clone <url> my-project")
    print("       cd my-project")
    print("       python -X utf8 harness_install.py --new")
    return False


def print_language_report() -> None:
    """이 프로젝트의 언어 설정과, 그 언어팩에 필요한 도구가 설치됐는지 출력한다.

    도구가 없으면 그 검사는 안 도는데, 설치 전에는 그 사실이 설치 화면에 안 나온다.
    온보딩이 이걸 보고 "무엇이 지금 안 지켜지는지"를 사용자에게 말해줘야 한다.
    """
    from kernel import arch, lang, linters

    print(f"Available language packs: {' '.join(lang.available())}")
    print(f"Available architecture packs: {' '.join(arch.available())}\n")
    print(f"Current settings — LANG={profile.LANG!r} SYNTAX={profile.SYNTAX!r} ARCH={profile.ARCH!r}")
    print(f"   server source: {' '.join(profile.SOURCE_EXT)}")
    print(f"   UI source: {' '.join(profile.UI_EXT)}")

    if profile.NOT_APPLICABLE:
        print("\nChecks not applicable to this language and architecture (no loss):")
        for slug, why in sorted(profile.NOT_APPLICABLE.items()):
            print(f"   {slug:<16} {why}")

    if not profile.LINTERS:
        print("\nNo external tools to delegate to.")
    else:
        print("\nExternal tools:")
        for entry in profile.LINTERS:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("slug") or "?")
            absent = linters.missing_tool(entry)
            if absent:
                print(f"   [missing] {name:<14} {absent} not installed — {entry.get('install', 'no install instructions given')}")
            else:
                print(f"   [found] {name:<14} {' '.join(entry.get('cmd', []))}")
        print("\nFor a missing tool, its check runs switched off as [TOOL]. It does not count as a pass.")
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
        return "stdlib ast", "nothing to install"
    if kind == "regex":
        return "regex", "nothing to install"
    if kind == "treesitter":
        grammar = lang.grammar_module(pack) or "?"
        core = "found" if importlib.util.find_spec("tree_sitter") else "missing"
        found = "found" if importlib.util.find_spec(grammar) else "missing"
        fallback = " — regex fallback runs meanwhile" if "missing" in (core, found) and pack.get("REGEX") else ""
        return "tree-sitter", f"tree_sitter {core} · grammar {grammar} {found}{fallback}"
    if kind == "command":
        command = [str(part) for part in pack.get("ANALYZER_CMD") or ()]
        found = "found" if command and (shutil.which(command[0]) or (ROOT / command[0]).is_file()) else "missing"
        return "external analyzer", f"{' '.join(command)} — executable {found}"
    return "none", "syntax fact gates stay [TOOL]"


def print_stack_report(pack: dict, frameworks: list[dict] | None = None) -> int:
    """언어팩이 고른 분석기와 언어팩·프레임워크팩 REQUIRES 의 설치 상태를 찍고, 없는 도구 수를 돌려준다.

    설치는 여기서 하지 않는다 — 사용자 환경을 바꾸는 일이라 사용자가 결정한다. 하네스 자신은 아무것도 요구하지 않으므로
    이 레포에서는 언제나 0 이어야 한다.
    """
    name, status = analyzer_status(pack)
    print(f"\nSyntax analyzer: {name} — {status}")
    requires = [entry for source in (pack, *(frameworks or ()))
                for entry in (source.get("REQUIRES") or ()) if isinstance(entry, dict)]
    if not requires:
        print("Pack requirements beyond the linters above: none.")
        return 0
    missing = 0
    print("Tools required by the packs:")
    for entry in requires:
        if requirement_present(entry):
            print(f"   [found] {entry['name']:<14} {' '.join(entry['check'])}")
        else:
            missing += 1
            print(f"   [missing] {entry['name']:<14} install: {entry['install'] or 'no install instructions given'}")
    print(f"Missing tools: {missing}. The user decides whether to install — without them the pack is not a verified pack.")
    return missing


def presets() -> list[str]:
    """새 프로젝트에 권할 수 있는 프로파일만 돌려준다. `PRESET_SUMMARY` 를 선언한 프로파일이 곧 프리셋이다.

    선언을 요구하는 이유: `profiles/` 에는 특정 프로젝트의 실제 프로파일도 섞여 있다.
    그걸 새 프로젝트에 권하면 다른 프로젝트의 레이어 이름과 어휘를 물려받게 된다.
    """
    return [name for name in profile_modules() if _preset_meta(name)[0]]


def _preset_module(name: str) -> ModuleType | None:
    """프리셋 파일을 실행한 모듈. 이 프로세스의 `kernel.profile` 은 교체 전 프로파일을 들고 있어서 프리셋 파일을 직접 읽는다."""
    spec = importlib.util.spec_from_file_location(f"_preset_{name}", PRESET_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def _preset_meta(name: str) -> tuple[str, str]:
    """프리셋의 (한 줄 요약, 언제 고르는지). 없으면 빈 문자열."""
    module = _preset_module(name)
    if module is None:
        return "", ""
    return getattr(module, "PRESET_SUMMARY", ""), getattr(module, "PRESET_FITS", "")


def write_surface(preset: str) -> None:
    """프리셋 선언으로 편집 표면 동결본을 뜬다. 템플릿은 면제 0건이라 그 뒤에 늘어나는 것은 전부 이 프로젝트의 완화다.

    플러그인 설치도 같다 — 게이트 모듈은 플러그인 폴더에서 오고 동결본은 프로젝트에 둔다.
    """
    from harness_gates import edit_surface

    module = _preset_module(preset)
    rows = edit_surface.declared(module) if module is not None else set()
    edit_surface.write(rows, ROOT / SURFACE_FILE)
    print(f"[SURFACE] {SURFACE_FILE} written from preset {preset} — {len(rows)} exemption rows; the list may only shrink")


def print_presets() -> None:
    """사람이 고를 수 있게 요약과 함께 나열한다.

    이름만 나열하면 무엇이 자기 경우인지 모른다. 스택 이름을 아는 사람만 고를 수 있는 목록은 목록이 아니다.
    """
    print("Available presets:\n")
    for name in presets():
        summary, fits = _preset_meta(name)
        print(f"  {name}")
        if summary:
            print(f"      {summary}")
        if fits:
            print(f"      → {fits}")
        print()
    print("If you cannot choose, start claude and say \"set up the harness\" — it asks and picks for you.")


def install_profile(preset: str) -> bool:
    """프로파일 파일이 없으면 프리셋에서 만든다. 반환값은 새로 만들었는지 여부다.

    하네스 레포를 clone 해 온 경우 하네스 **자신의** 프로파일이 딸려 온다. 그건 이 프로젝트의
    설정이 아니라 하네스가 자기를 검사하려고 둔 파일이고, 레이어가 전부 비어 있어 그대로 두면
    게이트가 전부 꺼진 채로 통과 표시가 뜬다. 그래서 하네스 자신의 프로파일은 없는 것으로 취급해 덮어쓴다.
    """
    if preset not in profile_modules():
        raise ValueError(f"Preset not available: {preset}")
    target = ROOT / profile.PROFILE_FILE
    if target.exists() and not profile.IS_HARNESS_SELF:
        print(f"[PROFILE] {profile.PROFILE_FILE} already exists — left untouched")
        return False
    if target.exists():
        print("[PROFILE] Replacing the harness's own profile that came with the clone with this project's profile")
        shipped.reset(ROOT)
    shutil.copy2(PRESET_DIR / f"{preset}.py", target)
    print(f"[PROFILE] {profile.PROFILE_FILE} created (preset {preset})")
    write_surface(preset)
    print("   → Approve the classification with the user and wire up the language check tools.")
    return True


def install_gate_baselines() -> None:
    path = api_types.BASELINE
    if not path.exists():
        path.write_text(API_BASELINE_HEADER, encoding="utf-8")
        print(f"[BASELINE FILE] {path.name} created — without it that gate is [SKIP]")


def report_unlisted_layers() -> None:
    """컴포넌트 분류 정본(그래프)이 있는지, 있으면 프로파일 언어와 묶여 있는지 알린다. 검사 경로를 채웠다고 분류가 된 것은 아니다."""
    from kernel import component_graph, graph_checks

    graph = ROOT / profile.COMPONENT_GRAPH
    if not graph.is_file():
        print(f"\n[CLASSIFY] {profile.COMPONENT_GRAPH} missing — approve the classification with the user before the first code.")
        return
    try:
        mismatched = graph_checks.binding_errors(component_graph.load(ROOT))
    except (OSError, ValueError, KeyError, TypeError):
        return                          # 형식 오류는 러너의 graph_schema 가 보고한다
    for error in mismatched:
        print(f"\n[CLASSIFY] {error}")


def _write_baseline(pairs: list[tuple[str, str]]) -> None:
    body = "".join(f"{slug}\t{path}\n" for slug, path in pairs)
    runner.BASELINE_FILE.write_text(BASELINE_HEADER + body, encoding="utf-8")


def _report(pairs: list[tuple[str, str]], label: str) -> None:
    by_gate = Counter(slug for slug, _path in pairs)
    print(f"\n{label} — {len(pairs)} found ({len(by_gate)} gates)")
    for slug in sorted(by_gate, key=lambda s: (-by_gate[s], s)):
        print(f"   {by_gate[slug]:>4}  {slug}")


def _prune() -> int:
    frozen = runner.load_baseline()
    still_broken = set(runner.collect_all_violations()) & frozen
    removed = sorted(frozen - still_broken)
    _write_baseline(sorted(still_broken))
    _report(removed, "[PRUNE] Fixed entries removed from the baseline")
    print(f"Baseline entries left: {len(still_broken)}.")
    return 0


def _parse(argv: list[str]) -> argparse.Namespace:
    # 모르는 옵션은 무시하지 않고 거절한다(argparse 기본 exit 2). `--dryrun` 오타가 실제 설치로 실행돼
    # 동결 파일을 덮어쓰는 것이 실제로 사고가 나는 경로다. `allow_abbrev=False` — 줄임 옵션도 오타와 같이 거절한다.
    parser = argparse.ArgumentParser(prog="harness_install.py", allow_abbrev=False,
                                     description="Install the harness profile and verify; with no option, install and verify.")
    for flag, about in (("--new", "start a fresh project from a just-cloned harness: new git history, install, first commit"),
                        ("--doctor", "check the environment: hook interpreter, git user, check tools; exit 1 if something blocks"),
                        ("--list", "list profile presets"),
                        ("--dry-run", "show current violations without installing"),
                        ("--prune", "drop fixed rows from harness_baseline.txt"),
                        ("--check-update", "say whether a newer harness exists upstream"),
                        ("--upgrade", "update harness-owned files from upstream"),
                        ("--keep-local", "with --upgrade: keep files you changed and upgrade the rest"),
                        ("--check-agents", "check Claude Code and Codex hook wiring")):
        parser.add_argument(flag, action="store_true", help=about)
    parser.add_argument("--preset", default=DEFAULT_PRESET, help="profile preset to install (default: %(default)s)")
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

        if PLUGIN:
            print("[AGENTS] The plugin registers the hooks — the project wiring check applies to template installs only.")
            return 0
        return check_agents(ROOT)

    if args.check_update:
        return _plugin_update(upgrade.check_update)

    if args.upgrade:
        return _plugin_update(lambda: upgrade.run(["--keep-local"] if args.keep_local else []))

    if args.doctor:
        from kernel.harness_setup import check_agents

        print_language_report()
        blocked = preflight.report()
        return max(blocked, 0 if PLUGIN else check_agents(ROOT))

    # 설치 위치를 가장 먼저 확인한다. 위치가 틀리면 나머지를 다 해도 훅이 하나도 실행되지 않는다.
    if not report_install_location():
        return 2

    if args.new:
        code = fresh_repo.prepare(ROOT)
        if code:
            return code

    if not args.prune and not args.dry_run:
        try:
            created = install_profile(args.preset)
        except ValueError as exc:
            print(f"[PROFILE] {exc}")
            return 2
        install_gate_baselines()
        if args.new and fresh_repo.commit(ROOT):
            return 2
        if created:
            print("\nProfile created. Decide the stack and classification graph with the user, then wire up the check tools.")
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
        _report(current, "[DRY RUN] Current violations (not baselined automatically)")
        return 0

    _report(current, "[INSTALL] Violations to fix")

    # 신규 위반을 동결하지 않고 실제 검증 결과를 반환한다.
    print("\nRunning verification:")
    code = runner.main(["--verify", "--compact"])
    if code == 0:
        print("\nInstall verified — no violations were baselined automatically.")

    else:
        print("\nVerification failed — fix the classification issues, check configuration issues and code violations reported above.")

    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
