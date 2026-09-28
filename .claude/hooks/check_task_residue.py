"""Stop hook — docs/tasks/ 루트에 plan·research 가 남아있으면 세션 종료를 막는다.

판정과 설계 근거(보드 busy 면 건너뜀·갓 만든 산출물 유예·`wip_` 예외)는 `kernel/workspace.py`
다 — Codex Stop(`kernel/hook.py`)이 같은 판정을 돈다. 여기는 stderr·trace·exit 만 맡는다.
커널을 못 읽으면 판정을 못 해 통과하되 stderr 로 고지한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, payload_sid  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import task_residue  # noqa: E402
except Exception as exc:
    print(f"[TASK RESIDUE] 커널을 못 읽어 판정을 건너뛴다({exc.__class__.__name__}) — kernel/workspace.py 를 점검하라.",
          file=sys.stderr)
    sys.exit(0)


def main() -> None:
    found = task_residue()
    if found is None:
        sys.exit(0)
    emit(found, payload_sid())
    sys.exit(2)                         # 차단 — 직접 관측(파일이 실제로 거기 있다)


if __name__ == "__main__":
    main()
