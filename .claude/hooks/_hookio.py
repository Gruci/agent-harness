"""훅 stdin 리더와 git 조회 — EOF에 의존하지 않는다.

git 헬퍼가 여기 있는 이유는 두 Stop 훅이 같은 조회를 하기 때문이다. 훅마다 따로 두면
기본 브랜치 감지 같은 판정이 두 벌이 되고, 한쪽만 고치는 순간 두 훅의 판정이 갈린다.


json.load(sys.stdin)은 stdin을 EOF까지 읽는다: CC가 페이로드를 준 뒤 파이프를 닫아준다는
가정이다. macOS/Linux와 EOF를 보내는 이벤트(Stop·PreToolUse·PostToolUse·SubagentStop)에선
문제없지만, Windows CC의 UserPromptSubmit stdin엔 EOF가 안 온다 — 그 읽기가 매달리다 훅
타임아웃으로 강제종료된다(output discarded). read1은 데이터가 있으면 즉시 반환하므로, 완결된
JSON 객체가 파싱되는 즉시 멈춰 EOF를 기다리지 않는다. EOF를 보내는 이벤트에서도 동일 동작.

바이트를 utf-8로 명시 디코드한다 — json.load(sys.stdin)은 Windows에서 stdin을 cp949로 읽어
한글 페이로드(프롬프트·경로)를 깨뜨릴 수 있었다.

파싱 실패 시 예외를 던진다. 훅마다 fail-open(exit 0)과 fail-closed(exit 2) 정책이 달라
정책 판단은 호출자 몫이다 — 헬퍼가 실패를 삼키면 fail-closed 훅이 무력화된다.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_CHUNK = 65536
_ROOT = Path(__file__).resolve().parents[2]
_GIT_TIMEOUT_SEC = 10


def record(*args: object, **kwargs: object) -> None:
    """`kernel.trace.record` 위임. 관찰은 차단보다 덜 중요하다 — 커널이 없거나 기록이 실패해도 판정은 계속된다."""
    try:
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        from kernel.trace import record as _record
        _record(*args, **kwargs)
    except Exception:
        pass


def emit(finding: object, sid: str = "") -> None:
    """커널 판정(`kernel.workspace.Finding`)을 stderr 와 trace 로 옮긴다. exit 는 래퍼가 낸다 —
    단계(차단 2·경고 1)가 훅 파일에 글자로 남아야 규칙 지도(`kernel/diagram/rules.py`)가 읽는다."""
    for msg in getattr(finding, "trace", ()):
        record(finding.hook, finding.kind, sid=sid, msg=msg)
    # Stop·PreToolUse 훅의 사유는 stderr 로 내보내야 모델에게 전달된다(stdout 은 무시된다).
    print(finding.message, file=sys.stderr)


SEPARATORS = (";", "|", "||", "&&", "&")


def segments(tokens: list[str]) -> list[list[str]]:
    """셸 구분자로 끊은 명령 조각들. 조각의 머리만 봐야 `echo "git commit"` 처럼 인자로 들어간
    문자열을 명령으로 오독하지 않는다. 셸 훅 둘이 같은 판정을 쓴다.
    """
    found: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            found.append([])
        else:
            found[-1].append(token)
    return [segment for segment in found if segment]


def git_output(*args: str) -> str | None:
    """git 표준출력. 실패(비정상 종료·예외)면 None — 판정을 건너뛰라는 신호다."""
    try:
        done = subprocess.run(["git", *args], cwd=str(_ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=_GIT_TIMEOUT_SEC)
    except Exception:
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch() -> str | None:
    """원격 기본 브랜치 이름. `origin/HEAD` → 실패 시 main·master 실물 순 폴백.

    main 하드코딩은 이식성을 깬다 — master 레포에서 판정이 통째로 조용히 꺼진다.
    """
    head = git_output("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.strip():
        return head.strip().rsplit("/", 1)[-1]
    for name in ("main", "master"):
        if git_output("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{name}") is not None:
            return name
    return None


def read_hook_payload() -> dict[str, Any]:
    """stdin의 훅 페이로드(JSON 객체 1건)를 EOF 대기 없이 읽어 반환한다.

    비어 있거나 JSON 객체로 완결되지 않으면 예외(JSONDecodeError·ValueError)를 던진다.
    """
    decoder = json.JSONDecoder()
    buf = ""
    stream = sys.stdin.buffer
    while True:
        chunk = stream.read1(_CHUNK)
        if not chunk:  # 진짜 EOF — 아래에서 마지막으로 한 번 파싱 시도
            break
        buf += chunk.decode("utf-8", "replace")
        try:
            obj, _ = decoder.raw_decode(buf.lstrip())
        except json.JSONDecodeError:
            continue  # 객체가 아직 안 완성됨 — 더 읽는다
        return _as_object(obj)
    return _as_object(decoder.raw_decode(buf.lstrip())[0])


def payload_sid() -> str:
    """페이로드의 session_id. 판정에 페이로드가 필요 없는 훅이 관찰 기록용으로만 읽는다 — 실패하면 빈 문자열."""
    try:
        return str(read_hook_payload().get("session_id") or "")
    except Exception:
        return ""


def _as_object(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("hook payload is not a JSON object")
    return obj
