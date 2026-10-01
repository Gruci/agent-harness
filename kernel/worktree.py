"""kernel/worktree.py — worktree 이름·자리·범위 판정과 머지 끝난 worktree 판정.

Claude 훅(`.claude/hooks/check_pretool.py`·`check_worktree_residue.py`)과 Codex 진입점
(`kernel/hook.py` → `kernel/pretool.py`)이 같은 판정을 쓴다. 페이로드 파싱, exit 코드, 출력 JSON 은 어댑터가
맡고 이 모듈에는 판정과 문구만 둔다. 결과는 항상 `kernel.workspace.Finding` 으로 돌려준다.

## 이름·자리 규약 — 왜 생성 시점에 막나

`git worktree list` 로는 어느 세션이 어떤 worktree 를 쓰는지 알 수 없었다. worktree 이름이 브랜치
이름과 다르기까지 했다. 보드에는 `#sid:` 가 있는데 worktree 쪽에는 대응하는 값이 없어 둘을 맞춰 볼 수 없다.
그래서 "다들 쓰고 있나 보다"로 추측하게 된다.

서식은 `worktrees/<범위>--<sid8>` 다. 범위를 앞에 두는 이유는 사람이 목록에서 먼저 읽는 것이
"무엇"이고 "누구"는 보드와 맞춰 보는 키이기 때문이다. 위치를 레포 루트 `worktrees/` 로 둔 이유는
특정 에이전트에 묶이지 않게 하기 위해서다. 보드(`workboard/`)와 같은 원칙이고, `.claude/` 밑에 두면
Codex 가 Claude 전용 폴더에 체크아웃을 만들게 된다.

이미 만들어진 것을 뒤늦게 지적하면 이름을 바꿔야 하는데, 세션이 그 안에서 작업 중이면 디렉토리 이동이
실패한다. 다른 세션의 worktree 까지 문제 삼으면 세션 종료가 서로 막히는 데드락이 된다. 만들기 **전에**
막으면 이름을 바꿀 일 자체가 없고, 내 호출에서만 실행되므로 다른 세션에 영향이 없다. 기존 worktree 는 건드리지 않는다.

Claude 의 `EnterWorktree(name)` 생성은 차단한다 — 그 툴은 생성 위치가 `.claude/worktrees/` 로
고정이라(스키마 명세) 루트 규약과 항상 어긋난다. 생성은 `git worktree add` 로 하고, 진입만
`EnterWorktree(path=...)` 로 한다. Codex 에는 그 툴이 없어 `git worktree add` 만 대상이다.

세션 식별자를 못 구하면 어댑터가 비차단 경고를 낸다. 하네스가 자기 상태를 모르는 것은 규칙
위반이 아니라 오작동이고, 그것으로 worktree 생성을 막으면 격리 자체가 불가능해진다.

## 죽은 worktree 판정 — 세 조건을 모두 만족할 때만

"머지 후 worktree remove → branch -d" 규칙이 문서에만 있으면 세션이 길어지면서 지켜지지 않는다.
이 하네스가 나온 원래 프로젝트에서는 머지가 끝난 worktree 4개(가장 오래된 것은 4일)가 쌓여
`git worktree list` 로 "지금 누가 뭘 쓰고 있나"를 읽을 수 없었다. 이름 끝에 `--<sid8>` 을 강제한
이유가 보드와 맞춰 보기 위해서인데, 끝난 worktree 가 섞이면 그 의미가 없어진다.

방금 만든 worktree 와 머지 끝난 worktree 는 둘 다 기본 브랜치의 조상이고 자기 커밋이 0개라
그것만으로는 구별되지 않는다. 둘을 구별해 주는 것은 **push 이력**이다.

1. `branch.<브랜치>.merge` 가 **자기 이름**(`refs/heads/<브랜치>`)이다 = `push -u` 로 한 번이라도
   올렸다. **`.remote` 유무로 판단하면 안 된다** — `git worktree add -b X origin/<기본>` 은 시작점을
   upstream 으로 자동 등록해 `remote=origin, merge=refs/heads/<기본>` 을 남긴다. 그걸 push 이력으로
   읽으면 세 조건이 전부 참이 되어 **방금 만든 worktree 가 통째로 "머지 완료"** 로 판정된다. 실측으로
   확인했다. 만든 직후 `remote=origin` 이고, origin ref 는 없고, 기본 브랜치의 조상이다. 방금 만든 브랜치의
   `merge` 는 기본 브랜치를 가리키므로 여기서 걸러진다.
2. `refs/remotes/origin/<브랜치>` 가 없다 = 머지되어 원격에서 삭제됐다.
   PR 이 열려 있는 동안은 있으므로 작업 중엔 안 걸린다.
   **놓치는 경우**: 원격 자동삭제(deleteBranchOnMerge)가 없는 레포에서는 이 조건이 늘 거짓이라
   남은 worktree 를 잡지 못한다. 오탐(작업 중인 것을 지우라고 하는 것)을 막는 쪽을 우선한 선택이다.
3. 브랜치가 원격 기본 브랜치의 조상이다 = 실제로 머지됐다.
   push 후 머지 없이 버린 브랜치는 여기서 걸러진다 — 다른 사람이 머지하지 않은 작업을 지우라고 하면 안 된다.

`git worktree list --porcelain` 의 lock 줄에는 PID 가 있다. 그 프로세스가 살아 있으면 다른
세션이 그 안에서 작업 중이라는 뜻이라 건너뛴다. 반대로 PID 가 죽은 lock 은 건너뛰지 않는다.
크래시로 남은 worktree 를 살아 있는 것으로 치면, 이 게이트가 잡아야 할 바로 그 경우가 영원히 빠진다.

판정할 수 없으면(git 실패, 기본 브랜치를 모름) 통과시킨다. 하네스 오작동으로 종료를 막으면
복구 수단인 그 세션까지 잠긴다.

남은 worktree 판정은 전부 **git 상태 추론**이라 경고 단계다(`Finding.block=False`). 직접 관측이 아니라
틀릴 수 있고 실제로 틀렸다 — 차단이면 잘못된 지시를 따르거나 세션이 잠기거나 둘 중 하나다.
검출을 끄면 남은 worktree 가 안 보이므로 끄는 대신 단계를 낮춘다. 정본은 `dev/HARNESS.md` 「단계」다.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from kernel.context import default_branch, git_output
from kernel.workboard import task_files
from kernel.workspace import Finding

# 테스트가 가짜 git 으로 갈아끼우는 자리 — 판정 함수는 이 이름으로만 git 을 부른다.
_git = git_output

SID_LEN = 8
WORKTREE_ADD = re.compile(r"\bgit\b.*\bworktree\s+add\b")
SEPARATORS = (";", "|", "||", "&&", "&")
_LOCK_PID = re.compile(r"\(pid (\d+)\)")

HOOK_NAME = "check_pretool"
HOOK_RESIDUE = "check_worktree_residue"


def segments(tokens: list[str]) -> list[list[str]]:
    """셸 구분자로 끊은 명령 조각들. 조각의 머리만 봐야 `echo "git commit"` 처럼 인자로 들어간
    문자열을 명령으로 오독하지 않는다. `.claude/hooks/_hookio.segments` 와 같은 판정이다 —
    `check_bash_write.py` 가 커널 없이도 동작해야 해서 같은 구현을 따로 하나 더 둔다.
    """
    found: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            found.append([])
        else:
            found[-1].append(token)
    return [segment for segment in found if segment]


def session_id8(payload: dict) -> str | None:
    """`session_id` 우선, 없으면 transcript 파일명에서. 둘 다 없으면 None."""
    session_id = str(payload.get("session_id") or "")
    if len(session_id) >= SID_LEN:
        return session_id[:SID_LEN]
    stem = Path(str(payload.get("transcript_path") or "")).stem
    return stem[:SID_LEN] if len(stem) >= SID_LEN else None


def offending_name(name: str, sid8: str) -> str | None:
    """서식을 안 지킨 worktree 이름. 지켰으면 None."""
    if not name:
        return None
    return None if name.endswith(f"--{sid8}") else name


def my_scope(sid8: str, board: Path | None) -> str | None:
    """내 `#sid` 가 든 workboard 파일의 범위 이름(= 파일 stem). 보드가 없으면 None."""
    if board is None:
        return None
    return next((path.stem for path, text in task_files(board) if f"#sid:{sid8}" in text), None)


def scope_mismatch(name: str, sid8: str, board: Path | None) -> str | None:
    """worktree 이름 앞부분이 내 workboard 범위와 다른가 — 다르면 기대한 이름을 돌려준다.

    맞추면 `ls workboard/` 와 `git worktree list` 가 눈으로 바로 조인된다(`#sid` 를
    대조할 필요가 없다). 범위 이름은 보드에서 이미 정했으므로 새로 지을 것도 없다.

    **내 보드 파일이 없으면 검사하지 않는다.** 보드 등록이 프로토콜상 worktree 보다 먼저라
    정상 경로에서는 늘 있지만, 순서를 바꾼 예외 상황에서 막으면 손쓸 방법이 사라진다.
    """
    scope = my_scope(sid8, board)
    if scope is None or not name.endswith(f"--{sid8}"):
        return None
    return None if name[: -len(f"--{sid8}")] == scope else f"{scope}--{sid8}"


def wrong_location(token: str, cwd: Path | None = None, shared_root: Path | None = None) -> str | None:
    """자리가 공유 체크아웃 루트 기준 상대경로 `worktrees/<이름>` 이 아니면 기대 경로를 돌려준다.

    자리는 레포 루트 `worktrees/` 하나로 **상대경로 고정**이다. 보드(`workboard/`)와 같은 원칙이다.
    - 절대경로·외부 디스크·`~`·`..` 는 받지 않는다. 경로가 체크아웃 위치를 품으면 clone 을 옮기는
      순간 규약이 깨지고, 다른 디스크의 worktree 는 `git worktree list` 와 보드의 조인에서 빠진다.
    - `.claude/worktrees/` 도 받지 않는다(특정 에이전트 전용 폴더다).
    - 상대 토큰은 명령의 cwd 기준으로 풀리므로, cwd 가 공유 루트가 아니면 worktree 안에 worktree 가
      생긴다. cwd 와 공유 루트를 둘 다 알면 둘이 같아야 통과다. 하나라도 모르면 경로 토큰의 모양만 본다.
    """
    normalized = token.replace("\\", "/")
    name = PurePosixPath(normalized).name
    expected = f"worktrees/{name}"
    parts = [part for part in PurePosixPath(normalized).parts if part != "."]
    if normalized.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", normalized) or parts != ["worktrees", name]:
        return expected
    if cwd is not None and shared_root is not None and cwd.resolve() != shared_root.resolve():
        return expected
    return None


def worktree_add_path(command: str) -> str | None:
    """`git worktree add` 가 만들려는 경로 토큰. 생성 명령이 아니면 None.

    `list`·`remove`·`move` 는 생성이 아니라 통과다. 옵션과 `-b <브랜치>` 값을 걷어낸 첫 인자가
    경로다 — 브랜치명을 경로로 오독하면 정상 호출이 막힌다.

    **조각의 머리에서만 찾는다.** 문자열 전체를 훑으면 커밋 메시지 heredoc 안에 적힌
    `git worktree add ...` 같은 산문을 명령으로 오독한다 — 이 판정이 자기 커밋을 막았다.
    heredoc 본문은 따옴표가 아니라 shlex 가 그대로 낱말로 쪼개므로, `git`·`worktree`·`add` 가
    나란히 서 있는지만 봐서는 안 갈린다. 자리로 갈라야 한다.
    같은 부류를 `check_bash_write.py` 의 링크 판정도 앞 3토큰 제한으로 막는다.
    """
    if not WORKTREE_ADD.search(command):
        return None
    try:
        # posix 모드는 백슬래시를 이스케이프로 먹는다 — Windows 경로가 뭉개져 판정이
        # 통째로 틀린다. 쪼개기 전에 구분자를 정규화한다.
        tokens = shlex.split(command.replace("\\", "/"), posix=True)
    except ValueError:
        return None
    for segment in segments(tokens):
        # `git worktree add` 는 조각의 **머리 세 칸**이다. 뒤쪽에 나오면 인자거나 산문이다.
        head = segment[:3]
        if len(head) < 3 or head[1] != "worktree" or head[2] != "add":
            continue
        if Path(head[0]).name not in ("git", "git.exe"):
            continue                    # 백틱이 붙은 `` `git `` 같은 산문 조각을 배제한다
        return _first_path(segment[3:])
    return None


def _first_path(rest: list[str]) -> str | None:
    """옵션과 `-b <브랜치>` 값을 걷어낸 첫 인자."""
    skip_next = False
    for token in rest:
        if skip_next:
            skip_next = False
            continue
        if token in ("-b", "-B", "--reason"):
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


def enter_worktree_violation(sid8: str | None) -> Finding:
    """`EnterWorktree(name)` 생성 — 항상 규약 밖이라 조건 없이 차단 문구를 돌려준다."""
    suffix = f"--{sid8}" if sid8 else "--<sid8>"
    return Finding(HOOK_NAME, "worktree_name", True, (
        "[WORKTREE NAME] EnterWorktree creates under `.claude/worktrees/`, which breaks the root `worktrees/` rule.\n"
        "Create and enter separately:\n"
        f"  git worktree add worktrees/<scope>{suffix} -b <branch> origin/<default-branch>\n"
        f"  EnterWorktree(path=\"worktrees/<scope>{suffix}\")\n"
        "(Source of truth: workboard/README.md work isolation)"), ("EnterWorktree create",))


def name_violation(token: str, sid8: str, board: Path | None,
                   cwd: Path | None = None) -> Finding | None:
    """`git worktree add <token>` 이 규약 밖이면 차단 finding. 순서는 접미 → 범위 → 자리다.

    공유 루트는 보드의 부모다(`kernel.workboard.board_dir` 가 git common dir 로 계산한다).
    """
    name = Path(token).name
    if offending_name(name, sid8) is not None:
        return Finding(HOOK_NAME, "worktree_name", True, (
            f"[WORKTREE NAME] The worktree name has no session id — `{name}` → `{name}--{sid8}`.\n"
            "`git worktree list` alone must show who uses which worktree; the join key is the task board #sid.\n"
            "(Source of truth: workboard/README.md)"), (f"no sid suffix {name}",))
    expected = scope_mismatch(name, sid8, board)
    if expected is not None:
        return Finding(HOOK_NAME, "worktree_name", True, (
            f"[WORKTREE NAME] The name differs from my task scope — `{name}` → `{expected}`.\n"
            "Use the workboard scope name as the worktree name, so `ls workboard/` and\n"
            "`git worktree list` line up at a glance.\n"
            "(Source of truth: workboard/README.md)"), (f"scope mismatch {name}",))
    shared_root = board.parent if board is not None else None
    misplaced = wrong_location(token, cwd, shared_root)
    if misplaced is not None:
        return Finding(HOOK_NAME, "worktree_name", True, (
            f"[WORKTREE NAME] The worktree location breaks the rule — `{token}` → `{misplaced}`.\n"
            "The only allowed location is `worktrees/<name>`, relative to the main checkout root.\n"
            "No absolute paths, other disks, or paths inside another worktree. Run from the main checkout root:\n"
            f"  git worktree add {misplaced} -b <branch> origin/<default-branch>\n"
            "(Source of truth: workboard/README.md work isolation)"), (f"location outside the rule {token}",))
    return None


def _alive(pid: int) -> bool:
    """그 PID 가 살아 있나. 확인할 수 없으면 살아 있다고 본다(다른 세션을 함부로 죽은 것으로 취급하지 않는다)."""
    try:
        done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                              capture_output=True, text=True, errors="replace", timeout=15)
    except Exception:
        return True
    return str(pid) in done.stdout


def parse_worktrees(porcelain: str) -> list[dict]:
    """`git worktree list --porcelain` → [{path, branch, lock_pid}]. 메인 체크아웃은 뺀다.

    메인은 **첫 레코드**로 가른다(git 계약). 파일 경로로 가르면 안 된다 — 이 판정은 worktree
    안에서도 돌고 그때 ROOT 는 그 worktree 라, 자기 자신을 메인으로 빼고 진짜 메인을
    검사 대상에 넣는 역전이 난다.
    """
    trees: list[dict] = []
    cur: dict = {}
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[len("worktree "):], "branch": None, "lock_pid": None}
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/"):]
        elif line.startswith("locked"):
            found = _LOCK_PID.search(line)
            cur["lock_pid"] = int(found.group(1)) if found else None
    if cur:
        trees.append(cur)
    return [t for t in trees[1:] if t["branch"]]


def is_dead(branch: str, base: str) -> bool:
    """머지가 끝나 존재 이유가 사라진 브랜치인가. 판정 근거는 모듈 docstring 참조."""
    upstream = (_git("config", "--get", f"branch.{branch}.merge") or "").strip()
    if upstream != f"refs/heads/{branch}":
        return False                                    # push 이력 없음 = 작업 전이거나 작업 중
    if _git("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}") is not None:
        return False                                    # 원격에 살아있음 = PR 진행 중
    return _git("merge-base", "--is-ancestor", f"refs/heads/{branch}", f"origin/{base}") is not None


def dead_worktrees() -> list[dict]:
    """일이 끝난 worktree 목록. 판정할 수 없으면(git 실패, 기본 브랜치를 모름) 빈 목록을 돌려 통과시킨다."""
    porcelain = _git("worktree", "list", "--porcelain")
    if porcelain is None:
        return []
    base = default_branch()
    if base is None:
        return []
    residue = []
    for tree in parse_worktrees(porcelain):
        if tree["lock_pid"] is not None and _alive(tree["lock_pid"]):
            continue                                    # 남의 세션이 그 안에 서 있다
        if is_dead(tree["branch"], base):
            residue.append(tree)
    return residue


def worktree_residue() -> Finding | None:
    """Stop 판정 ⑮ — 머지 끝난 worktree 가 남아 있으면 경고 finding."""
    residue = dead_worktrees()
    if not residue:
        return None
    lines = [f"[WORKTREE RESIDUE] Finished worktrees remain — {len(residue)} found."]
    for tree in residue:
        lines.append(f"  {Path(tree['path']).name}  [{tree['branch']}] — merged, deleted on remote")
    lines.append("Clean up in this order before ending: `git worktree remove <path>` → `git branch -d <branch>` → remove the task board row.")
    lines.append("(Keep this order. git refuses to delete a local branch that a worktree has checked out)")
    return Finding(HOOK_RESIDUE, "worktree_residue", False, "\n".join(lines), (f"{len(residue)} found",))
