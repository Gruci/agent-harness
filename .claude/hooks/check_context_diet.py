"""PreToolUse(Read) hook — 대용량 파일 통읽기 기계 차단 (컨텍스트 가드 ①).

배경(원본 프로젝트 사고): 메인 루프가 95KB 워크플로우 결과와 60KB 다이제스트를 통째로 Read 했고,
그 뒤 모든 턴에서 그 내용이 다시 전송·과금됐다. "요약만 받는다"는 문서 규칙은 시간이 지나면 지켜지지 않으므로 훅으로 강제한다.

크기는 바이트가 아니라 추정 토큰 수로 잰다. 한글은 UTF-8 에서 한 글자가 3바이트라 바이트로 재면 3배 크게 잡히고,
그러면 라우팅표가 "읽어라"라고 지시하는 정본 MD를 훅이 막는 모순이 생긴다.

판정 (메인 루프와 서브에이전트를 구분하지 않는다 — 훅은 서브에이전트의 툴 호출에도 실행된다):
  - 추정 토큰이 LIMIT_TOKENS 를 넘고 분할 파라미터(limit ≤ CHUNK_LIMIT_LINES)가 없으면 exit 2 로 차단
  - 이미지·바이너리는 예외 (비전 에이전트가 통째로 읽어야 한다 — 기계로 가려낼 수 없다)
  - PDF는 Read 자체가 pages 분할을 강제하므로 예외
"""
import sys
from pathlib import Path

from _hookio import read_hook_payload, record

LIMIT_TOKENS = 16_000
CHUNK_LIMIT_LINES = 500
EXEMPT_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".pdf"}


def _estimate_tokens(path: Path) -> int:
    """ASCII 4자당 1토큰, 비ASCII(한글 등) 1자당 1토큰 — ±20% 근사면 차단 판정에 충분."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return ascii_count // 4 + (len(text) - ascii_count)


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception:
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        sys.exit(0)

    path = Path(file_path)
    if not path.is_file() or path.suffix.lower() in EXEMPT_SUFFIXES:
        sys.exit(0)

    estimated = _estimate_tokens(path)
    if estimated <= LIMIT_TOKENS:
        sys.exit(0)

    limit_lines = tool_input.get("limit")
    if isinstance(limit_lines, (int, float)) and limit_lines <= CHUNK_LIMIT_LINES:
        sys.exit(0)

    record("check_context_diet", "context_diet",
           sid=str(payload.get("session_id") or ""), file=str(path),
           msg=f"통읽기 차단 — 약 {estimated}토큰 (상한 {LIMIT_TOKENS})")
    print(
        f"[CONTEXT GUARD] {path.name} 약 {estimated:,}토큰 — 통읽기 차단 (상한 {LIMIT_TOKENS:,}).\n"
        f"  · offset/limit({CHUNK_LIMIT_LINES}줄 이하)으로 필요한 부분만 나눠 읽어라.\n"
        f"  · 수십 개 파일을 각각 훑어야 하면 Sonnet 에이전트 여러 개에 나눠 맡겨라.\n"
        f"  (정본: CLAUDE.md 모델 라우팅 — 한 번 읽은 대용량 파일은 남은 세션 동안 매 턴 다시 전송된다)",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
