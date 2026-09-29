"""SubagentStop hook — 서브에이전트 비만 반환 차단 (컨텍스트 가드 ②).

서브에이전트의 최종 반환문은 그대로 메인 루프 컨텍스트에 들어가 남은 세션 동안 매 턴 다시 전송된다.
반환이 MAX_RETURN_CHARS를 넘으면 exit 2로 종료를 막고, 에이전트가 stderr 피드백을 받아
"요약 + detail_path(파일)" 형태로 다시 쓰게 강제한다.

상한을 2만자로 둔 이유: 너무 많이 줄이면 빠진 내용을 다시 조사하느라 총비용이 오히려 커진다. 자세한 반환은
허용하되 파일 전체를 그대로 붙여 넣는 것은 막는 수준이다.

무한루프 방지: stop_hook_active면 통과시킨다. 페이로드에 last_assistant_message가 없으면
통과시키고 그 사실만 알린다(fail-open). 트랜스크립트에서 마지막 assistant 메시지를
추정하던 폴백은 삭제했다. SubagentStop이 넘겨주는 트랜스크립트가 서브에이전트 것인지 메인 것인지
확실하지 않아서, 메인 루프 응답을 서브에이전트 반환으로 잘못 보고 차단할 수 있었다.
모든 게이트에 공통으로 "확실한 위반만 잡고 오탐은 0건" 원칙이 우선한다.
"""
import sys

from _hookio import read_hook_payload, record

MAX_RETURN_CHARS = 20_000


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception:
        sys.exit(0)

    if payload.get("stop_hook_active"):
        sys.exit(0)

    sid = str(payload.get("session_id") or "")
    last_message = payload.get("last_assistant_message")
    if not isinstance(last_message, str) or not last_message:
        # 차단은 아니지만 게이트가 아무 알림 없이 동작하지 않는 상태다. dev/LESSONS.md §15(꺼진 게이트와 연결이 빠진 게이트가 겉보기에 같음)가 경계하는 경우라 기록을 남긴다
        # 값 본문은 대화 내용일 수 있어 남기지 않는다. 형식과 키 이름이면 원인을 가를 수 있다
        keys = ", ".join(sorted(str(key) for key in payload)) or "없음"
        record("check_agent_return", "gate_error", sid=sid,
               msg=f"페이로드에 last_assistant_message 없음 — 반환 검사가 안 돌고 있다 "
                   f"(값 형식 {type(last_message).__name__}, 받은 키: {keys})")
        print("[RETURN DIET] 페이로드에 last_assistant_message 가 없어 이번 반환은 검사하지 못했다. "
              "이 줄이 보이면 실제 payload 내용을 확인해 게이트가 다시 동작하게 고쳐라.", file=sys.stderr)
        sys.exit(0)

    return_length = len(last_message)
    if return_length <= MAX_RETURN_CHARS:
        sys.exit(0)

    record("check_agent_return", "return_diet", sid=sid,
           msg=f"반환 {return_length}자 — 상한 {MAX_RETURN_CHARS}자 초과")
    print(
        f"[RETURN DIET] 최종 반환이 {return_length:,}자로 상한 {MAX_RETURN_CHARS:,}자를 넘었다. "
        f"이 반환은 전부 메인 루프 컨텍스트에 들어가 남은 세션 동안 매 턴 다시 과금된다.\n"
        f"  상세는 파일로 저장하고 최종 반환은 다음 형식으로 다시 써라:\n"
        f"  · summary: 핵심 결론 1,500토큰 이하\n"
        f"  · 근거 포인터: file:line 형식\n"
        f"  · detail_path: 방금 저장한 상세 파일 경로\n"
        f"  (정본: CLAUDE.md 모델 라우팅 절의 에이전트 반환 규칙)",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
