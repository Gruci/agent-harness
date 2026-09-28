"""UserPromptSubmit hook — 세션 히스토리 비대 경고 (컨텍스트 가드 ③).

세션에 쌓인 히스토리는 매 턴 전체가 다시 전송된다. 캐시가 적중해도 비용은 든다.
transcript 파일 크기로 컨텍스트 크기를 가늠해, 임계값을 넘으면 사용자에게 경고를 띄우고 모델
컨텍스트에 /clear 권고를 넣는다. 차단하지는 않는다. 세션을 나눌지는 사용자가 정한다.

15MB로 둔 이유: transcript 크기는 실제 컨텍스트의 3~5배 정도라 15MB는 30~50만 토큰, 즉 1M의 3분의 1 지점이다.

# debt:파일 크기는 실제 컨텍스트 토큰을 대략 짐작하는 값일 뿐이다(컴팩션 후에는 크게 잡힌다). 정확히 재려면
# 컨텍스트 크기를 알려 주는 API가 필요하지만, 경고 용도로는 이 정도로 충분하다.
"""
import json
import sys
from pathlib import Path

from _hookio import read_hook_payload

WARN_BYTES = 15_000_000


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception:
        sys.exit(0)

    transcript_path = payload.get("transcript_path") or ""
    path = Path(transcript_path)
    if not transcript_path or not path.is_file():
        sys.exit(0)

    size_bytes = path.stat().st_size
    if size_bytes < WARN_BYTES:
        sys.exit(0)

    size_mb = size_bytes / 1_000_000
    warning = (
        f"세션 히스토리가 {size_mb:.0f}MB 쌓였다 — 매 턴 전체가 다시 전송되고 있다. "
        f"진행 중인 태스크가 끝났다면 /clear로 세션을 나눠라 (CLAUDE.md 모델 라우팅)."
    )
    print(
        json.dumps(
            {
                "systemMessage": f"⚠️ {warning}",
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"[CONTEXT GROWTH] {warning}",
                },
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
