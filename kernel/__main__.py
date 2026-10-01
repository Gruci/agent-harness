"""kernel/__main__.py — 커널을 프로젝트 밖(플러그인 설치)에서 실행하는 진입점.

`python -X utf8 "<커널 홈>/kernel" [하위 명령] [인자]` 로 부른다. 검사 대상은 현재 폴더가 속한 git 체크아웃이다.

| 하위 명령 | 하는 일 |
|---|---|
| 없음 · `-` 로 시작 | `kernel.runner` — 예: `--verify` |
| `install` | `harness_install.py` |
| `session` | 세션 시작 알림. 플러그인 SessionStart 훅이 부른다 |
| 그 밖의 이름 | `kernel.<이름>` 모듈 — 예: `pack_check go`·`profile` |
"""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
# 폴더째 실행하면 kernel/ 자신이 경로 맨 앞에 온다. 그러면 kernel/trace.py·profile.py 가 같은 이름의 표준 모듈을 가린다.
sys.path[0] = str(HOME)


def _toplevel() -> Path | None:
    try:
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(done.stdout.strip()).resolve() if done.returncode == 0 else None


def session_notice(root: Path | None) -> str:
    """세션 시작 때 모델에게 줄 몇 줄. 하네스를 연결하지 않은 레포에는 연결 방법만 알린다."""
    if sys.version_info < (3, 10):
        return "[HARNESS] Python 3.10 or later is required — gates do not run on this version."
    if root is None:
        return ""                             # git 밖이거나 템플릿 설치 — 그 체크아웃의 훅이 맡는다
    if not (root / "harness_profile.py").is_file():
        return ("[HARNESS] This repo is not connected to agent-harness, so gates are off. "
                "Connect it with the harness-init skill only when the user asks.")
    from kernel import profile
    command = f'python -X utf8 "{HOME.as_posix()}/kernel"'
    lines = [f"[HARNESS] Gates are on. Done means exit 0 from `{command} --verify` — [SKIP] is not a pass.",
             f"[HARNESS] Harness commands: `{command} <subcommand>` — install · pack_check · profile."]
    notice = profile.outdated_notice()
    return "\n".join([*lines, notice] if notice else lines)


def main(argv: list[str]) -> int:
    root = _toplevel()
    template = root is not None and (root / "kernel" / "hook.py").is_file()
    if root is not None and not template:
        os.environ["HARNESS_ROOT"] = str(root)
        sys.path.insert(1, str(root))         # 프로젝트 쪽 게이트(`harness_gates/`)는 그 루트에서 import 한다
    if argv[:1] == ["session"]:
        print(session_notice(None if template else root))
        return 0
    if root is None or template:
        print("[HARNESS] Run this inside a git checkout. A template install uses that checkout's "
              "`python -X utf8 -m kernel.runner`.", file=sys.stderr)
        return 2
    name, rest = (argv[0], argv[1:]) if argv and not argv[0].startswith("-") else ("runner", argv)
    sys.argv = [name, *rest]
    if name == "install":
        runpy.run_path(str(HOME / "harness_install.py"), run_name="__main__")
    else:
        runpy.run_module(f"kernel.{name}", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
