"""PreToolUse(EnterWorktree|Bash|PowerShell) 훅 — 새 worktree 의 이름·자리 규약을 강제.

매처는 셸을 실행하는 툴을 전부 담는다 — `Bash` 만 걸면 같은 `git worktree add` 가 `PowerShell`
툴로 빠져나간다(원류 프로젝트 2026-08-06 실측).

판정과 설계 근거는 `kernel/worktree.py` 다 — Codex 진입점(`kernel/hook.py --event PreToolUse`)이
같은 판정을 돈다. 여기는 페이로드 → 판정 → stderr·trace·exit 만 맡는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, read_hook_payload  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 커널을 못 읽으면 판정 자체가 없다 — 하네스 오작동은 규칙 위반이 아니라 비차단 경고다.
try:
    from kernel.workboard import board_dir  # noqa: E402
    from kernel.worktree import (enter_worktree_violation, name_violation,  # noqa: E402
                                 session_id8, worktree_add_path)
except Exception as exc:
    print(f"[WORKTREE NAME] 커널을 못 읽어 이름 검사를 건너뛴다({exc.__class__.__name__}) — kernel/worktree.py 를 점검하라.",
          file=sys.stderr)
    sys.exit(1)


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception as exc:
        print(f"[WORKTREE NAME] 훅 페이로드 파싱 실패({exc.__class__.__name__}) — 이름 검사가 쉬고 있다.",
              file=sys.stderr)
        sys.exit(1)

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    sid8 = session_id8(payload)

    if tool_name == "EnterWorktree":
        # `path` 는 기존 worktree 진입이라 생성이 아니다 — 진입은 위치 무관으로 허용된다.
        if tool_input.get("path") or not tool_input.get("name"):
            sys.exit(0)
        emit(enter_worktree_violation(sid8), sid8 or "")
        sys.exit(2)

    token = worktree_add_path(tool_input.get("command") or "")
    if not token:
        sys.exit(0)
    if sid8 is None:
        print("[WORKTREE NAME] 세션 식별자를 못 구했다 — 이름 검사를 건너뛴다. 훅을 점검하라.",
              file=sys.stderr)
        sys.exit(1)

    found = name_violation(token, sid8, board_dir())
    if found is not None:
        emit(found, sid8)
        sys.exit(2)                     # 차단 — 직접 관측(만들려는 경로가 규약 밖이다)
    sys.exit(0)


if __name__ == "__main__":
    main()
