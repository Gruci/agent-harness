"""SessionStart hook — 세션 식별자와 열린 과업 주입 + 체크아웃 stale 감시.

## 세션 식별자와 열린 과업 주입

겹침 확인에 손이 많이 가면 작업을 시작하기 전에 건너뛰게 되고, 그러면 보드는 있으나 마나다. `workboard/`
를 세션이 직접 열지 않아도 되도록 세션 시작 시점에 과업마다 한 줄씩 보여 준다. **브랜치와 무관하게 실행한다.**
새 작업을 시작하는 쪽은 오히려 worktree 세션이기 때문이다.

세션 식별자는 훅 페이로드에만 온다. `kernel.task` 명령은 `--sid` 를 받으므로 여기서 그 값을 채운 안내를 준다.
시작·`/clear`·compact·resume 모두에서 돈다 — `/clear` 뒤에 열린 과업과 자기 sid 를 다시 받지 못하면
다음 세션이 자기 과업을 이어받을 수 없다(결함 H). 남의 과업에는 그 세션이 끝났을 때의 인계 명령을, worktree 가 없는
과업에는 그 사실을 붙인다.

## stale 감시

아무도 pull하지 않은 체크아웃은 origin보다 뒤처진다. 그 상태로 백로그를 읽으면
**이미 끝난 일을 다시 계획하게 된다** — 원본 프로젝트 실사고(2026-07-29).

기본 브랜치에 있고 origin보다 뒤처졌으면 ff-only로 자동 fast-forward 하고, 거부되면 몇 커밋 뒤졌는지만 알린다.
worktree 세션(다른 브랜치)에서는 이 검사만 조용히 건너뛴다.

동기화는 `startup` 에서만 실행한다(/clear·compact마다 pull이 도는 것을 막는다). 작업 트리를
바꾸는 유일한 훅이라 실행 범위를 최소로 둔다.

기본 브랜치는 origin/HEAD에서 자동 감지한다 — main/master 하드코딩은 이식성을 깬다.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import default_branch, read_hook_payload  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 보드는 공유 체크아웃 한 곳에만 있다 — 자기 트리 기준으로 잡으면 세션 수만큼 따로 생긴다
# (`kernel.workboard.board_dir`). 커널을 못 읽으면 열린 과업 출력만 생략하고 stale 감시는 계속한다.
try:
    from kernel.workboard import board_dir, branch_of, field, sid_of, task_files  # noqa: E402
    from kernel.worktree import worktree_of  # noqa: E402
    BOARD_DIR: Path | None = board_dir()
except Exception:
    BOARD_DIR = None

_FETCH_TIMEOUT_SEC = 15


def _git(*args: str, timeout: int = 5) -> str | None:
    """git 실행 → stdout strip. 실패·타임아웃이면 None (훅은 조용히 통과)."""
    try:
        done = subprocess.run(
            ("git", *args), capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _payload() -> dict:
    """SessionStart 페이로드. 못 읽으면 {} — 시작 때처럼 동작한다."""
    try:
        return read_hook_payload()
    except Exception:
        return {}


def _task_note(text: str, sid8: str) -> str:
    """과업 한 줄 뒤에 붙는 안내 — 남의 과업이면 인계 명령, worktree 가 없으면 그 사실."""
    owner = sid_of(text)
    scope = field(text, "범위")  # ko-ok: reads the Korean task-board format
    branch = branch_of(" | ".join(text.split()))
    notes = []
    if sid8 and owner and owner != sid8:
        notes.append(f"another session's — if it has ended: python -X utf8 -m kernel.task resume {scope} --sid {sid8}")
    if branch and worktree_of(branch) is None:
        notes.append("no worktree — resume recreates it")
    return f"  ({'; '.join(notes)})" if notes else ""


def print_open_tasks(sid8: str) -> None:
    """열린 과업을 한 줄씩 요약해 출력한다. 작업 시작 전 확인을 세션의 기억에 맡기지 않기 위해서다."""
    if BOARD_DIR is None:
        return
    rows = []
    for path, text in task_files(BOARD_DIR):
        state = field(text, "상태") or "?"  # ko-ok: reads the Korean task-board format
        task = field(text, "과업")  # ko-ok: reads the Korean task-board format
        rows.append(f"  {path.stem} [{state}] {task}{_task_note(text, sid8)}")
    if not rows:
        return
    print(f"[WORKBOARD] Open tasks: {len(rows)} found — for the same scope, do not create a new task; add an item to that task file or build on that branch.")
    for row in rows:
        print(row)
    print("  Start, finish, hand over: workboard/README.md")


def main() -> None:
    payload = _payload()
    sid8 = str(payload.get("session_id") or "")[:8]
    if sid8:
        print(f"[SESSION] This session's id is {sid8} — use it for the workboard #sid and "
              f"`python -X utf8 -m kernel.task` commands.")
    print_open_tasks(sid8)
    if payload.get("source", "startup") != "startup":
        return   # /clear·compact·resume 마다 fetch·pull 이 돌지 않게 동기화는 시작 때만 한다
    branch = default_branch()
    if branch is None or _git("rev-parse", "--abbrev-ref", "HEAD") != branch:
        return   # 원격 미설정이거나 worktree 세션 — 자기 브랜치가 정본이라 검사 대상이 아니다
    if _git("fetch", "origin", "--quiet", timeout=_FETCH_TIMEOUT_SEC) is None:
        return   # 오프라인·인증 실패 — 세션 시작을 막을 이유가 없다
    behind = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    if not behind or behind == "0":
        return

    # 자동 fast-forward 는 ff-only라 커밋을 잃을 수 없다. 로컬 변경과 충돌하는지는 git이 판정한다.
    # 직접 dirty 검사를 했을 때는 늘 바뀌어 있는 tracked 파일 하나 때문에 동기화가 한 번도 실행되지 않은 적이 있다.
    if _git("pull", "--ff-only", "origin", branch, timeout=_FETCH_TIMEOUT_SEC) is not None:
        print(f"[GIT SYNC] The checkout was {behind} commits behind, so it fast-forwarded to origin/{branch}. "
              f"docs/BACKLOG.md is current.")
        return

    print(f"[GIT STALE] The checkout is {behind} commits behind origin/{branch} and the automatic fast-forward (ff-only) was refused. "
          f"Local changes overlap the incoming commits.\n"
          f"  Do not trust docs/BACKLOG.md or the source as is — you would re-plan tasks that are already merged.\n"
          f"  Before starting work, check what came in with `git log --oneline HEAD..origin/{branch}`.")


if __name__ == "__main__":
    main()
    sys.exit(0)
