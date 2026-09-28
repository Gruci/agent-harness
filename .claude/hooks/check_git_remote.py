"""Stop hook — GitHub 원격(origin) 미설정 시 세션 종료 차단.

판정 로직과 설계 근거(fail-closed, gh 인증이 돼 있으면 묻지 않기, private 고정)는 `kernel/workspace.py` 에 있다.
Codex Stop(`kernel/hook.py`)도 같은 판정을 쓴다. 이 훅은 stderr·trace·exit 만 맡는다.
커널을 못 읽어도 통과시키지 않는다. 이 훅은 판정할 수 없을 때 차단한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, payload_sid  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import git_remote  # noqa: E402
except Exception as exc:
    print(f"[GIT REMOTE] 커널을 못 읽어 origin 이 있는지 판정할 수 없다({exc.__class__.__name__}) — fail-closed 라 종료를 막는다. "
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
