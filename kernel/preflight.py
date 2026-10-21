"""kernel/preflight.py — `harness_install.py --doctor` 의 환경 점검. 훅이 실제로 돌고 `--verify` 가 [TOOL] 로 멈추지 않는지 본다.

예전 진단은 없는 도구를 찍고도 "0 installs required" 와 exit 0 을 냈고, 정작 검증은 [TOOL] 로 막혔다. 여기서는 막는 항목
(훅 인터프리터·git 사용자·검사 도구·분석기)과 정보 항목(gh·원격)을 가르고, 막는 항목이 하나라도 없으면 exit 1 이다.
설치는 하지 않는다 — 사용자 환경을 바꾸는 일이라 사용자가 정한다.
"""

from __future__ import annotations

import argparse
import ast
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from kernel import facts, lang, linters, profile, tests_run
from kernel.context import READ_ENC, ROOT, shown_command

Check = tuple[bool, bool, str]       # (갖춤, 없으면 막힘, 한 줄)


def _run(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _interpreter() -> Check:
    name = "python" if shutil.which("python") else "python3" if shutil.which("python3") else ""
    version = ".".join(map(str, sys.version_info[:2]))
    if not name:
        return (False, True, "hook interpreter — neither `python` nor `python3` is on PATH, so no hook can run")
    return (sys.version_info >= (3, 10), True, f"hook interpreter — `{name}` (this run: Python {version}; 3.10+ needed)")


def _identity() -> Check:
    missing = [key for key in ("user.name", "user.email")
               if not ((done := _run("git", "config", key)) and done.stdout.strip())]
    if missing:
        return (False, True, f"git user — {', '.join(missing)} unset: git config --global user.name/user.email")
    return (True, True, "git user — set")


def _github() -> list[Check]:
    if not shutil.which("gh"):
        gh: Check = (False, False, "GitHub CLI — not installed (optional: https://cli.github.com)")
    else:
        done = _run("gh", "auth", "status")
        gh = (bool(done and done.returncode == 0), False,
              "GitHub CLI — signed in" if done and done.returncode == 0 else "GitHub CLI — installed, not signed in (gh auth login)")
    origin = _run("git", "remote", "get-url", "origin")
    has = bool(origin and origin.returncode == 0)
    return [gh, (has, False, "remote — origin set" if has else "remote — none yet: finished tasks merge locally only")]


def _tools() -> list[Check]:
    found: list[Check] = []
    for entry in profile.LINTERS:
        if isinstance(entry, dict):
            absent = linters.missing_tool(entry)
            name = str(entry.get("slug") or "?")
            found.append((not absent, True, f"check tool {name} — " + (f"missing: {entry.get('install', '')}" if absent else "found")))
    npm = linters.ui_npm_dir() if profile.UI else None
    if npm is not None:
        ready = npm.is_dir() and linters.ui_eslint_bin(npm) is not None
        found.append((ready, True, "UI checks (ESLint) — " + ("found" if ready else f"missing: {profile.UI['ESLINT_INSTALL']}")))
    if profile.LANG:
        _analyzer, reason = facts.select(profile.SYNTAX)
        found.append((not reason, True, f"syntax analyzer — {reason or 'ready'}"))
    return found


def report() -> int:
    """점검 결과를 찍는다. 막는 항목이 빠졌으면 1."""
    checks = [_interpreter(), _identity(), *_github(), *_tools(), *_contracts()]
    print("\nPreflight:")
    for ok, blocking, line in checks:
        print(f"   [{'ok' if ok else 'missing' if blocking else 'info'}] {line}")
    blockers = sum(1 for ok, blocking, _line in checks if blocking and not ok)
    if blockers:
        print(f"{blockers} blocking item(s) — hooks or `--verify` stop on these until fixed ([TOOL] is not a pass).")
        return 1
    print("Nothing blocking.")
    return 0


def _contracts() -> list[Check]:
    checks: list[Check] = []
    for error in profile.PROFILE_ERRORS:
        checks.append((False, True, f"profile — {error}; fix harness_profile.py, then rerun --doctor"))
    if tests_run.declaration_errors(profile.TESTS):
        return checks or [(False, True, "product tests — invalid TESTS declaration; fix harness_profile.py, then rerun --doctor")]
    if not profile.TESTS:
        return [*checks, (False, False, f"product tests — not declared; choose the stack, then run `{shown_command('preflight')} --configure`")]
    for entry in profile.TESTS:
        command = entry["cmd"]
        executable = shutil.which(command[0])
        ready = bool(executable)
        if ready and len(command) > 2 and command[1] == "-m":
            done = _run(executable, "-c", "import importlib.util,sys; sys.exit(importlib.util.find_spec(" + repr(command[2]) + ") is None)")
            ready = bool(done and done.returncode == 0)
        runner = " ".join(command[:3] if len(command) > 2 and command[1] == "-m" else command[:1])
        repair = (f"run `{command[0]} -m pip install pytest` in the project's test environment"
                  if tuple(command[1:3]) == ("-m", "pytest") else "restore the declared test environment")
        checks.append((ready, True, f"product test {entry.get('slug', '?')} — " +
                       ("runner found" if ready else f"runner missing: {runner}; {repair}, then rerun --doctor")))
    checks.append(("tests" in profile.REQUIRED_CHECKS, False,
                   "product test requirement — " + ("required" if "tests" in profile.REQUIRED_CHECKS else
                   f"optional; run `{shown_command('preflight')} --configure` to require the declared tests")))
    return checks


def _fill_settings(source: str, settings: dict[str, object]) -> str:
    """Replace only plain assignment values, preserving comments and unrelated code."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    additions: list[str] = []
    for name, value in settings.items():
        matches = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                   and any(isinstance(target, ast.Name) and target.id == name for target in
                           (node.targets if isinstance(node, ast.Assign) else [node.target]))]
        bindings = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store)]
        if (len(matches) != len(bindings) or len(matches) > 1
                or any(isinstance(node, ast.Assign) and len(node.targets) != 1 for node in matches)):
            raise ValueError(f"{name} needs one plain assignment before it can be configured")
        if not matches:
            additions.append(f"{name} = {value!r}\n")
            continue
        node = matches[0].value
        if node is None:
            raise ValueError(f"{name} needs an assignment value")
        ast.literal_eval(node)  # Never rewrite a dynamic declaration.
        start = sum(map(len, lines[:node.lineno - 1])) + len(lines[node.lineno - 1].encode("utf-8")[:node.col_offset].decode("utf-8"))
        end = sum(map(len, lines[:node.end_lineno - 1])) + len(lines[node.end_lineno - 1].encode("utf-8")[:node.end_col_offset].decode("utf-8"))
        edits.append((start, end, repr(value)))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source.rstrip("\n") + "\n" + "".join(additions)


def configure(root: Path, command: tuple[str, ...] = ()) -> int:
    """Fill completion settings for an already chosen stack; install nothing."""
    path = root / "harness_profile.py"
    try:
        source = path.read_text(encoding=READ_ENC)
        values = runpy.run_path(str(path))
        errors = profile._shape_errors(SimpleNamespace(**values))
        if errors:
            raise ValueError("; ".join(errors))
        selected = values.get("LANG")
        if not selected:
            raise ValueError("choose LANG in harness_profile.py with the user before configuring tests")
        entries = values.get("TESTS", ())
        if command:
            if entries and tuple(entries[0]["cmd"]) != command:
                raise ValueError("TESTS already has a different command; edit that decision explicitly")
            entries = entries or ({"slug": "product", "cmd": command},)
        if not entries and selected == "python":
            pyproject = root / "pyproject.toml"
            declared = ((root / "pytest.ini").is_file() or
                        (pyproject.is_file() and "[tool.pytest.ini_options]" in pyproject.read_text(encoding=READ_ENC)))
            if declared:
                entries = ({"slug": "pytest", "cmd": ("python", "-m", "pytest", "-q", "--junitxml={report}")},)
        if not entries:
            raise ValueError("test command is unknown; supply --test-command <command with {report}> after --configure")
        errors = tests_run.declaration_errors(entries)
        if errors:
            raise ValueError("; ".join(errors))
        linters_selected = values["LINTERS"] if "LINTERS" in values else lang.load(selected).get("LINTERS", ())
        required = [*values.get("REQUIRED_CHECKS", ()),
                    *(f"lint:{entry['slug']}" for entry in linters_selected if isinstance(entry, dict) and entry.get("slug")), "tests"]
        updated = _fill_settings(source, {"TESTS": entries, "REQUIRED_CHECKS": tuple(dict.fromkeys(required))})
        if updated != source:
            path.write_text(updated, encoding="utf-8")
        print("[SETUP] Completion settings ready. Existing test commands and requirements were preserved; no tools installed.")
        print(f"[SETUP] Next: run `{shown_command('preflight')}`, then verify hook wiring, the first product test and required CI.")
        return 0
    except (OSError, ValueError, SyntaxError, ImportError, KeyError, TypeError) as error:
        print(f"[SETUP] {error}. No profile settings were written.")
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False, description="Diagnose the environment or fill completion settings for a chosen stack.")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--test-command", nargs=argparse.REMAINDER, default=[])
    arguments = parser.parse_args()
    if arguments.test_command and not arguments.configure:
        parser.error("--test-command requires --configure")
    raise SystemExit(configure(ROOT, tuple(arguments.test_command)) if arguments.configure else report())
