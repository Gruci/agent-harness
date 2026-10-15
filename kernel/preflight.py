"""kernel/preflight.py — `harness_install.py --doctor` 의 환경 점검. 훅이 실제로 돌고 `--verify` 가 [TOOL] 로 멈추지 않는지 본다.

예전 진단은 없는 도구를 찍고도 "0 installs required" 와 exit 0 을 냈고, 정작 검증은 [TOOL] 로 막혔다. 여기서는 막는 항목
(훅 인터프리터·git 사용자·검사 도구·분석기)과 정보 항목(gh·원격)을 가르고, 막는 항목이 하나라도 없으면 exit 1 이다.
설치는 하지 않는다 — 사용자 환경을 바꾸는 일이라 사용자가 정한다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from kernel import facts, linters, profile
from kernel.context import ROOT

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
    checks = [_interpreter(), _identity(), *_github(), *_tools()]
    print("\nPreflight:")
    for ok, blocking, line in checks:
        print(f"   [{'ok' if ok else 'missing' if blocking else 'info'}] {line}")
    blockers = sum(1 for ok, blocking, _line in checks if blocking and not ok)
    if blockers:
        print(f"{blockers} blocking item(s) — hooks or `--verify` stop on these until fixed ([TOOL] is not a pass).")
        return 1
    print("Nothing blocking.")
    return 0
