"""Stop hook — `workboard/` 에 '끝난' 과업 파일이 남아있으면 알린다.

판정 로직과 설계 근거는 `kernel/workspace.py` 에 있다(과업 하나가 파일 하나, `#sid` 로 소유자 판정,
진행 중 과업은 통과, 경고 단계). Codex Stop(`kernel/hook.py`)도 같은 판정을 쓴다. 이 훅은 sid 파싱과 stderr·trace·exit 만
맡는다. 커널을 못 읽으면 통과한다. 경고용 훅은 조용히 통과하는 쪽이 안전하다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import emit, read_hook_payload  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import board_residue  # noqa: E402
except Exception:
    sys.exit(0)


def _my_sid8() -> str | None:
    """Stop 훅 stdin JSON의 session_id 앞 8자. 파싱 실패 시 None."""
    try:
        payload = read_hook_payload()
        session_id = str(payload.get("session_id") or "")
        return session_id[:8] if len(session_id) >= 8 else None
    except Exception:
        return None


def main() -> None:
    sid8 = _my_sid8()
    found = board_residue(sid8)
    if found is None:
        sys.exit(0)
    # 경고(exit 1)의 stderr 는 사용자 화면에만 뜬다 — 모델 컨텍스트에는 들어가지 않는다(훅 문서).
    emit(found, sid8 or "")
    # 차단(2)이 아니라 경고(1)다. 판정이 git 상태에서 추론한 결과라서다. dev/HARNESS.md 「단계」 참조.
    sys.exit(1)


if __name__ == "__main__":
    main()
