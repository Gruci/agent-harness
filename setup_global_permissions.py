"""setup_global_permissions.py — 선택한 에이전트의 글로벌 자율 실행 설정을 병합한다.

  python -X utf8 setup_global_permissions.py
  python -X utf8 setup_global_permissions.py --agent codex
  python -X utf8 setup_global_permissions.py --agent both
  python -X utf8 setup_global_permissions.py --agent codex --check

clone 직후 1회. 기존 설정(훅·플러그인 등)은 보존하고 permissions 만 병합한다.
기본 에이전트는 claude다. Claude는 CLAUDE_CONFIG_DIR 또는 ~/.claude를, Codex는 CODEX_HOME 또는 ~/.codex를 사용한다.
Codex는 config.toml과 글로벌 지침의 표시된 블록만 수정하고 기존 파일을 한 번 백업한다.
--check는 파일을 쓰지 않으며 런타임이 강제한 정책이나 세션 옵션을 변경하지 않는다.

⚠️ 이 스크립트는 **이 머신의 모든 프로젝트**에 대해 도구 승인 프롬프트를 끈다
   (`defaultMode: bypassPermissions`). 하네스의 차단은 훅과 게이트가 하고 승인 프롬프트는
   흐름만 끊는다는 판단이 근거다 — 그 판단에 동의할 때만 돌려라. 프로젝트 단위로만 켜려면
   이 파일 대신 그 프로젝트의 `.claude/settings.local.json` 에 같은 내용을 넣는다.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ALLOW = [
    "Bash(*)", "PowerShell(*)", "Edit(*)", "Write(*)", "Read(*)",
    "Glob(*)", "Grep(*)", "WebFetch(*)", "WebSearch(*)",
    "Agent(*)", "Skill(*)", "NotebookEdit(*)",
    "TaskCreate(*)", "TaskUpdate(*)", "TaskGet(*)", "TaskList(*)",
    "TaskStop(*)", "TaskOutput(*)",
]


def configure_claude(check: bool = False) -> int:
    # 계정을 여러 개 쓰는 환경은 CLAUDE_CONFIG_DIR 로 설정 디렉터리를 바꾼다
    path = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    settings: dict[str, object] = {}
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or not isinstance(settings.get("permissions", {}), dict):
        raise ValueError("Expected object-valued Claude settings and permissions")

    if check:
        perm = settings.get("permissions", {})
        ready = (isinstance(perm, dict) and perm.get("defaultMode") == "bypassPermissions"
                 and settings.get("skipDangerousModePermissionPrompt") is True
                 and set(ALLOW) <= set(perm.get("allow", [])))
        print(f"[CLAUDE] {'OK' if ready else 'MISSING'} global permissions: {path}")
        return 0 if ready else 1

    path.parent.mkdir(parents=True, exist_ok=True)

    perm = settings.setdefault("permissions", {})
    if isinstance(perm, dict):
        perm["allow"] = sorted(set(perm.get("allow", [])) | set(ALLOW))
        perm["defaultMode"] = "bypassPermissions"
    settings["skipDangerousModePermissionPrompt"] = True

    updated = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != updated:
        from kernel.codex_permissions import _write_backed_up   # 한 번만 백업하고 쓴다 — Codex 쪽과 같은 계약

        _write_backed_up(path, updated)
    print(f"Global permissions configured: {path}")
    print("From the next claude session, commands run without approval prompts.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("claude", "codex", "both"), default="claude")
    parser.add_argument("--check", action="store_true", help="Read-only configuration check")
    args = parser.parse_args(argv)
    codes = []
    if args.agent in ("claude", "both"):
        try:
            codes.append(configure_claude(check=args.check))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            print(f"[CLAUDE] ERROR settings could not be updated: {exc.__class__.__name__}")
            codes.append(2)
    if args.agent in ("codex", "both"):
        from kernel.codex_permissions import codex_home, configure_codex

        codes.append(configure_codex(codex_home(), check=args.check))
    return max(codes)


if __name__ == "__main__":
    raise SystemExit(main())
