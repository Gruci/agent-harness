"""Stop hook ⑭ — GitHub 원격(origin)이 없으면 사용자에게 한 줄로 알린다. 턴 종료는 막지 않는다.

판정 로직과 설계 근거(gh 인증이 돼 있으면 묻지 않기, private 고정)는 `kernel/workspace.py` 에 있다.
Codex Stop(`kernel/hook.py`)도 같은 판정을 쓴다. 이 훅은 `systemMessage`·trace·exit 만 맡는다.
막는 자리는 과업 끝내기(`python -X utf8 -m kernel.task finish`)다 — 원격이 없으면 거절한다.
모델에게 줄 완성된 명령은 세션 시작 알림 ②와 finish 의 거절 문구가 준다.
커널을 못 읽어도 막지 않는다. 예전에는 커널 고장까지 fail-closed 로 막아 고칠 수단이 없었다(`dev/LESSONS.md` §19).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import notify, payload_sid, record  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from kernel.workspace import git_remote  # noqa: E402
except Exception:
    git_remote = None


def main() -> None:
    sid = payload_sid()
    try:
        found = git_remote() if git_remote is not None else _raise_missing()
    except Exception as exc:
        notify(f"[GIT REMOTE] Could not check origin ({exc.__class__.__name__}) — inspect kernel/workspace.py. "
               "Finishing a task still needs a remote.")
        sys.exit(0)
    if found is None:
        sys.exit(0)
    for msg in found.trace:
        record(found.hook, found.kind, sid=sid, msg=msg, level="warn")
    notify(found.message.splitlines()[0])
    sys.exit(0)


def _raise_missing() -> None:
    raise RuntimeError("kernel could not be loaded")


if __name__ == "__main__":
    main()
