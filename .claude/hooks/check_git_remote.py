"""Stop hook — GitHub 원격(origin) 미설정 시 세션 종료 차단.

판정과 설계 근거(fail-closed·gh 인증 시 묻지 않기·private 고정)는 `kernel/workspace.py` 다 —
Codex Stop(`kernel/hook.py`)이 같은 판정을 돈다. 여기는 stderr·trace·exit 만 맡는다.
커널을 못 읽어도 통과가 아니다 — 판정 불능은 이 훅에서 차단 방향이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, payload_sid  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import git_remote  # noqa: E402
except Exception as exc:
    print(f"[GIT REMOTE] 커널을 못 읽어 origin 판정 불능({exc.__class__.__name__}) — fail-closed 로 종료 차단. "
          "kernel/workspace.py 를 점검하라.", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    found = git_remote()
    if found is None:
        sys.exit(0)
    emit(found, payload_sid())
    sys.exit(2)                         # 차단 — 직접 관측(origin 이 실제로 없다)


if __name__ == "__main__":
    main()
