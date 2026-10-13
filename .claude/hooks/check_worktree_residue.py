"""Stop hook — 일이 끝난 worktree 가 남아있으면 정리 순서를 알린다.

판정 로직과 설계 근거(세 조건, 살아 있는 세션, 경고 단계)는 `kernel/worktree.py` 에 있다. Codex Stop
(`kernel/hook.py`)도 같은 판정을 쓴다. 이 훅은 systemMessage·trace·exit 만 맡는다.
커널을 못 읽으면 통과한다. 경고용 훅은 조용히 통과하는 쪽이 안전하다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import payload_sid, warn  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.worktree import worktree_residue  # noqa: E402
except Exception:
    sys.exit(0)


def main() -> None:
    found = worktree_residue()
    if found is None:
        sys.exit(0)
    # 차단(2)이 아니라 경고다. 판정이 git 상태에서 추론한 결과라서다. 경고는 exit 0 + systemMessage 로
    # 사용자 화면에만 뜬다 — exit 1 이면 "hook error" 와 첫 줄만 보여 정리 순서가 잘린다. dev/HARNESS.md 「단계」 참조.
    warn(found, payload_sid())
    sys.exit(0)


if __name__ == "__main__":
    main()
