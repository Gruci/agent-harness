"""SessionStart hook — 밀린 정비를 세션 시작에 알린다.

월간 감사류는 "한 달에 한 번 돌리세요"라고 문서에 적어 두면 아무도 돌리지 않는다. 사용자가 명령어를
외우고 때를 판단해야 하기 때문이다. 이 훅이 그 판단을 대신한다. 레포의 실제 상태(커밋 수, 바뀐 화면 파일, 남은 `debt:` 표시)로
임계치를 재고, 넘으면 무엇을 돌릴지 모델에게 알린다.

차단하지 않는다. 정비는 보고서만 내고 코드를 안 고치므로 흐름을 멈출 이유가 없다.
판정 정본은 kernel/maintenance.py 다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    if not (ROOT / "kernel" / "maintenance.py").exists():
        sys.exit(0)
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "kernel.maintenance"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        sys.exit(0)                     # 정비 알림 실패가 세션을 막을 이유는 없다

    body = result.stdout.strip()
    if not body or "No overdue maintenance" in body:
        sys.exit(0)

    print(body)
    print("[MAINTENANCE] Run the items above on your own after finishing the current request; do not ask the user. "
          "They only produce reports and change no code. When done, "
          "record it with `python -X utf8 -m kernel.maintenance --stamp <name>` and report only the results.")
    sys.exit(0)


if __name__ == "__main__":
    main()
