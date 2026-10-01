"""Stop hook — docs/tasks/mockup/ 에 목업이 남아있으면 세션 종료를 막는다.

판정 로직과 설계 근거(채택한 목업을 옮길 곳, 디렉토리 직접 스캔, `wip_` 예외)는 `kernel/workspace.py` 에 있다. Codex Stop
(`kernel/hook.py`)도 같은 판정을 쓴다. 이 훅은 stderr·trace·exit 만 맡는다.
커널을 못 읽으면 판정할 수 없어 통과시키되 stderr 로 알린다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, payload_sid  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import mockup_residue  # noqa: E402
except Exception as exc:
    print(f"[MOCKUP RESIDUE] Could not load the kernel, so the check is skipped ({exc.__class__.__name__}) — inspect kernel/workspace.py.",
          file=sys.stderr)
    sys.exit(0)


def main() -> None:
    found = mockup_residue()
    if found is None:
        sys.exit(0)
    emit(found, payload_sid())
    sys.exit(2)                         # 차단 — 직접 관측(파일이 실제로 거기 있다)


if __name__ == "__main__":
    main()
