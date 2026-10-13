"""훅 stdin 리더와 git 조회 — EOF에 의존하지 않는다.

git 헬퍼를 여기 두는 이유는 커널 없이도 동작해야 하는 훅(`check_ui_copy`·`git_staleness`)이
기본 브랜치를 같은 방식으로 감지하게 하기 위해서다. 커널이 쓰는 같은 기능은 `kernel/context.py` 에 있다.


json.load(sys.stdin)은 stdin을 EOF까지 읽는다. Claude Code(CC)가 페이로드를 보낸 뒤 파이프를
닫아 준다고 가정하는 방식이다. macOS/Linux와, EOF를 보내는 이벤트(Stop·PreToolUse·PostToolUse·SubagentStop)에서는
문제가 없다. 하지만 Windows CC의 UserPromptSubmit stdin에는 EOF가 오지 않아서, 읽기가 멈춘 채 기다리다
훅 타임아웃으로 강제 종료되고 출력도 버려진다(output discarded). read1은 데이터가 있으면 바로 반환하므로,
완결된 JSON 객체가 파싱되는 즉시 읽기를 멈추고 EOF를 기다리지 않는다. EOF를 보내는 이벤트에서도 똑같이 동작한다.

바이트를 utf-8로 명시 디코드한다 — json.load(sys.stdin)은 Windows에서 stdin을 cp949로 읽어
한글 페이로드(프롬프트·경로)를 깨뜨릴 수 있었다.

파싱에 실패하면 예외를 던진다. 훅마다 fail-open(exit 0)과 fail-closed(exit 2) 정책이 달라서
어느 쪽으로 처리할지는 호출자가 정한다. 헬퍼가 실패를 삼키면 fail-closed 훅이 제 역할을 못 한다.
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
    """`kernel.trace.record` 에 위임한다. 기록은 차단보다 덜 중요하므로 커널이 없거나 기록이 실패해도 판정은 계속된다."""
    try:
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        from kernel.trace import record as _record
        _record(*args, **kwargs)
    except Exception:
        pass


def emit(finding: object, sid: str = "") -> None:
    """차단 판정(`kernel.workspace.Finding`, `block=True`)을 stderr 와 trace 로 내보낸다. 훅 파일이 이어서 exit 2 로 끝낸다.
    경고는 `warn` 으로 낸다 — exit 2 의 stderr 만 모델에게 닿는다."""
    for msg in getattr(finding, "trace", ()):
        record(finding.hook, finding.kind, sid=sid, msg=msg)
    # Stop·PreToolUse 훅의 사유는 stderr 로 내보내야 모델에게 전달된다(stdout 은 무시된다).
    print(finding.message, file=sys.stderr)


def notify(message: str) -> None:
    """사용자 화면에 띄운다 — exit 0 + `systemMessage`. 모델은 읽지 않는다.

    exit 1 은 정상 동작한 경고를 "hook error" 로 보이고 첫 줄만 남긴다. exit 0 의 stderr 는 모델이 읽지 않는다(훅 문서).
    """
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))


def warn(finding: object, sid: str = "") -> None:
    """추론 판정(`block=False`)을 경고로 낸다. trace 에는 warn 단계로 남긴다. 훅은 이어서 exit 0 으로 끝낸다."""
    for msg in getattr(finding, "trace", ()):
        record(finding.hook, finding.kind, sid=sid, msg=msg, level="warn")
    notify(str(getattr(finding, "message", "")))


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
    """원격 기본 브랜치 이름. `origin/HEAD` 를 먼저 보고, 실패하면 원격에 실제로 있는 main, master 순으로 찾는다.

    main 을 하드코딩하면 다른 레포로 옮길 때 깨진다. master 를 쓰는 레포에서는 판정 전체가 아무 알림 없이 꺼진다.
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
    """페이로드의 session_id. 판정에는 페이로드가 필요 없는 훅이 trace 기록용으로만 읽는다. 실패하면 빈 문자열을 돌려준다."""
    try:
        return str(read_hook_payload().get("session_id") or "")
    except Exception:
        return ""


def _as_object(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("hook payload is not a JSON object")
    return obj
