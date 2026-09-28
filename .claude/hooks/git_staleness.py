"""SessionStart hook — 열린 과업 주입 + 체크아웃 stale 감시.

## 열린 과업 주입

겹침 확인에 손이 많이 가면 작업을 시작하기 전에 건너뛰게 되고, 그러면 보드는 있으나 마나다. `workboard/`
를 세션이 직접 열지 않아도 되도록 세션 시작 시점에 과업마다 한 줄씩 보여 준다. **브랜치와 무관하게 실행한다.**
새 작업을 시작하는 쪽은 오히려 worktree 세션이기 때문이다.

## stale 감시

아무도 pull하지 않은 체크아웃은 origin보다 뒤처진다. 그 상태로 백로그를 읽으면
**이미 끝난 일을 다시 계획하게 된다** — 원본 프로젝트 실사고(2026-07-29).

기본 브랜치에 있고 origin보다 뒤처졌으면 ff-only로 자동 fast-forward 하고, 거부되면 몇 커밋 뒤졌는지만 알린다.
worktree 세션(다른 브랜치)에서는 이 검사만 조용히 건너뛴다.

SessionStart 중 startup 에서만 실행한다(/clear·compact마다 pull이 도는 것을 막는다). 작업 트리를
바꾸는 유일한 훅이라 실행 범위를 최소로 둔다.

기본 브랜치는 origin/HEAD에서 자동 감지한다 — main/master 하드코딩은 이식성을 깬다.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import default_branch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 보드는 공유 체크아웃 한 곳에만 있다 — 자기 트리 기준으로 잡으면 세션 수만큼 따로 생긴다
# (`kernel.workboard.board_dir`). 커널을 못 읽으면 열린 과업 출력만 생략하고 stale 감시는 계속한다.
try:
    from kernel.workboard import board_dir, task_files  # noqa: E402
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


def _field(text: str, name: str) -> str:
    """workboard 파일에서 `- <name>: <값>` 한 줄. 없으면 빈 문자열."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {name}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def print_open_tasks() -> None:
    """열린 과업을 한 줄씩 요약해 출력한다. 작업 시작 전 확인을 세션의 기억에 맡기지 않기 위해서다."""
    if BOARD_DIR is None:
        return
    rows = []
    for path, text in task_files(BOARD_DIR):
        state = _field(text, "상태") or "?"
        task = _field(text, "과업")
        rows.append(f"  {path.stem} [{state}] {task}")
    if not rows:
        return
    print(f"[WORKBOARD] 열린 과업 {len(rows)}건 — 같은 범위면 새 과업을 만들지 말고, 그 과업 파일에 항목을 추가해 같이 처리하거나 그 브랜치 위에서 이어 작업한다.")
    for row in rows:
        print(row)
    print("  서식과 작업 시작 절차: workboard/README.md")


def main() -> None:
    print_open_tasks()
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
        print(f"[GIT SYNC] 체크아웃이 {behind}커밋 뒤여서 origin/{branch}로 fast-forward 했다. "
              f"docs/BACKLOG.md 는 최신이다.")
        return

    print(f"[GIT STALE] 체크아웃이 origin/{branch}보다 {behind}커밋 뒤고 자동 fast-forward(ff-only)가 거부됐다. "
          f"로컬 변경이 새로 들어온 커밋과 겹친다.\n"
          f"  docs/BACKLOG.md·소스를 그대로 믿지 마라 — 이미 머지된 과업을 다시 계획하게 된다.\n"
          f"  작업을 시작하기 전에 `git log --oneline HEAD..origin/{branch}`로 그 사이 무엇이 들어왔는지 먼저 확인하라.")


if __name__ == "__main__":
    main()
    sys.exit(0)
