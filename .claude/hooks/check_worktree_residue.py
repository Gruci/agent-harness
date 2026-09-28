"""Stop hook — 일이 끝난 worktree 가 남아있으면 세션 종료를 막는다.

판정과 설계 근거(세 조건·살아있는 세션·경고 단계)는 `kernel/worktree.py` 다 — Codex Stop
(`kernel/hook.py`)이 같은 판정을 돈다. 여기는 stderr·trace·exit 만 맡는다.
커널을 못 읽으면 통과한다 — 경고 계열은 조용히 통과하는 쪽이 안전 방향이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, payload_sid  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.worktree import worktree_residue  # noqa: E402
except Exception:
    sys.exit(0)


def main() -> None:
    found = worktree_residue()
    if found is None:
        sys.exit(0)
    # 경고(exit 1)의 stderr 는 사용자 화면에만 뜬다 — 모델 컨텍스트에는 들어가지 않는다(훅 문서).
    emit(found, payload_sid())
    # 경고(1)지 차단(2)이 아니다 — 판정 근거가 git 상태 추론이라서다. dev/HARNESS.md 「단계」 참조.
    sys.exit(1)


if __name__ == "__main__":
    main()
