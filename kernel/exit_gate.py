"""kernel/exit_gate.py — 나올 때 검사: 본체로 합치는 명령 직전에 나가는 트리를 골라 `--verify` 를 돌린다.

`kernel/pretool.py` 가 셸 명령마다 부르고, `kernel.task finish` 는 `verify_checkout` 만 직접 쓴다.
명령 읽기는 `kernel/shell.py` 다 — 한 명령줄의 합치는 명령을 전부 읽고, `cd`·`git -C` 가 가리키는 위치를 함께 받는다.

## 무엇이 나가는 명령인가

`git push`·`gh pr create`·`gh pr merge`·`git merge`. 명령은 단순 명령의 머리에서만 찾는다. `echo "git push"` 와
커밋 메시지 안의 문장은 명령이 아니다(`kernel/shell.py` 가 정본이다).

## 어느 체크아웃을 검사하나

| 명령 | 검사하는 체크아웃 |
|---|---|
| `git push`·`gh pr create` | 명령이 도는 체크아웃 |
| `git merge <과업 브랜치>` (공유 체크아웃에서) | 그 브랜치를 체크아웃한 worktree. 없으면 막고 `kernel.task finish` 를 안내한다 |
| `git merge` (worktree 안) · `git merge origin/…` | 검사하지 않는다 — 따라잡기와 동기화는 나가는 명령이 아니다 |
| `gh pr merge <n>` (공유 체크아웃에서) | 보드에서 `상태: PR#<n>` 인 과업의 worktree. 못 찾으면 명령이 도는 체크아웃 |

예전에는 명령을 실행한 체크아웃을 검사했다. 본체에서 `git merge --ff-only <브랜치>` 를 치면 합치기 전 본체를 검사하고
통과시켰다(결함 E). 반대로 worktree 안의 `git merge origin/main` 은 그 worktree 의 `[WIP]` 때문에 막혔다.

exit 0 이 아니면 막는다. `[TOOL]`·`[DECISION]` 도 통과가 아니다. 러너를 실행하지 못해도 **막는다**(fail-closed).
본체에 합친 것은 되돌리기 비싸기 때문이다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kernel import shell
from kernel.context import runner_command
from kernel.isolation import HOOK_NAME, checkout_of, shared_root
from kernel.workboard import board_dir, branch_of, field, task_files
from kernel.workspace import Finding
from kernel.worktree import worktree_of

VERIFY_TIMEOUT_SEC = 120                   # one runner run — save (⑨), Stop (⑬) and the exit gate (⑧-7) share it
MAX_VERDICT_LINES = 30
VERDICT_HEADS = ("[FAIL]", "[TOOL]", "[DECISION]")
GIT_EXITS = ("push", "merge")
GH_EXITS = (("pr", "create"), ("pr", "merge"))
MERGE_VALUE_OPTIONS = ("-m", "-F", "-s", "-X", "--file", "--strategy", "--strategy-option")


@dataclass(frozen=True)
class ExitCommand:
    """본체로 합치는 명령 하나. 어느 체크아웃을 검사할지는 `exit_gate` 가 정한다."""
    name: str                       # "git push" · "git merge" · "gh pr create" · "gh pr merge"
    workdir: str | None             # cd·pushd·Set-Location 과 git -C 를 반영한 위치. None = 페이로드 cwd
    args: tuple[str, ...]           # 하위 명령 뒤 인자. `git merge` 의 대상 브랜치는 여기서 읽는다


def exit_commands(command: str) -> list[ExitCommand]:
    """명령줄 안의 합치는 명령 전부. 단순 명령마다 머리만 본다(읽기 규칙은 `kernel/shell.py`)."""
    found: list[ExitCommand] = []
    for call in shell.commands(command):
        parsed = shell.git_args(call.argv)
        if parsed is not None:
            git_dir, rest = parsed
            if rest[:1] and rest[0] in GIT_EXITS:
                found.append(ExitCommand(f"git {rest[0]}", shell.join(call.workdir, git_dir), rest[1:]))
        elif shell.program(call.argv[0]) == "gh" and call.argv[1:3] in GH_EXITS:
            found.append(ExitCommand(" ".join(("gh", *call.argv[1:3])), call.workdir, call.argv[3:]))
    return found


def _merge_ref(rest: tuple[str, ...]) -> str | None:
    """`git merge` 의 대상 ref — 값을 받는 옵션을 건너뛴 첫 인자."""
    skip = False
    for token in rest:
        if skip:
            skip = False
        elif token in MERGE_VALUE_OPTIONS:
            skip = True
        elif not token.startswith("-"):
            return token
    return None


def _pr_worktree(rest: tuple[str, ...]) -> Path | None:
    """`gh pr merge <n>` 이 합칠 PR 을 보드에서 찾아 그 과업의 worktree 를 돌려준다. 못 찾으면 None."""
    number = next((token for token in rest if token.isdigit()), None)
    if number is None:
        return None
    for _path, text in task_files(board_dir()):
        if field(text, "상태") == f"PR#{number}":  # ko-ok: task-board key
            branch = branch_of(" | ".join(text.split()))
            return worktree_of(branch) if branch else None
    return None


def outgoing_checkout(name: str, rest: tuple[str, ...], here: Path) -> tuple[Path | None, str]:
    """본체로 나가는 트리가 있는 체크아웃과, 찾지 못해 막을 사유. (None, "") 이면 나가는 명령이 아니다.

    worktree 안의 `git merge` 는 기본 브랜치를 과업 쪽으로 들여오는 따라잡기이고, 원격 추적 브랜치를 합치는 것은
    동기화다. 공유 체크아웃에서 과업 브랜치를 합칠 때만 그 브랜치가 나가므로 그 브랜치의 worktree 를 검사한다.
    """
    shared = shared_root()
    if name == "gh pr merge":
        return (_pr_worktree(rest) if here == shared else None) or here, ""
    if name != "git merge":
        return here, ""
    ref = _merge_ref(rest)
    if here != shared or not ref or ref.startswith(("origin/", "refs/remotes/")):
        return None, ""
    tree = worktree_of(ref.removeprefix("refs/heads/"))
    if tree is None:
        return None, (f"no worktree has {ref} checked out, so the tree being merged cannot be verified — "
                      f"finish the task with `python -X utf8 -m kernel.task finish`.")
    return tree, ""


def verify_checkout(root: Path) -> tuple[int, list[str]] | None:
    """그 체크아웃의 `--verify` 결과 (exit, 사람이 볼 줄). 하네스가 연결되지 않은 체크아웃이면 None.

    나올 때 검사(⑧-7)와 `kernel.task finish` 가 같이 쓴다. 러너를 못 띄우면 exit 2 다(fail-closed).
    """
    command_line = runner_command(root, "--verify")
    if command_line is None:
        return None
    argv, env = command_line
    try:
        done = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=VERIFY_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, [f"runner could not start: {type(exc).__name__} (fail-closed)."]
    return done.returncode, verdict_lines(done.stdout) or done.stderr.splitlines()[-5:]


def verdict_lines(stdout: str, heads: tuple[str, ...] = VERDICT_HEADS) -> list[str]:
    """러너 출력 중 사람이 봐야 할 줄. `heads` 로 시작하는 머리줄과 그 아래 위반 항목만 남긴다.

    나올 때 검사와 종료 전량 검사는 세 머리를 다 본다. 작성 시점은 [TOOL] 을 뺀다 — 저장을 막지 않고, 합칠 때 다시 알린다.
    """
    kept: list[str] = []
    inside = False
    for line in stdout.splitlines():
        if line.startswith(heads):
            inside = True
        elif not line.startswith("   -"):
            inside = False
        if inside:
            kept.append(line)
    if len(kept) > MAX_VERDICT_LINES:
        kept = kept[:MAX_VERDICT_LINES] + [f"   … and {len(kept) - MAX_VERDICT_LINES} more lines — "
                                           "`python -X utf8 -m kernel.runner` prints them all"]
    return kept


def _blocked(name: str, reason: str, detail: list[str]) -> Finding:
    head = f"[EXIT GATE] check before `{name}` — {reason}"
    tail = "Do not merge until it passes. [TOOL] and [DECISION] are not a pass."
    return Finding(HOOK_NAME, "exit_gate", True, "\n".join([head, *detail, tail]), (f"{name} blocked: {reason}",))


def exit_gate(command: str, cwd: Path) -> Finding | None:
    """합치는 명령마다 나가는 트리를 골라 `--verify` 를 돌린다. 하나라도 exit 0 이 아니거나 러너를 실행하지 못하면 막는다."""
    checked: set[Path] = set()
    for found in exit_commands(command):
        here = checkout_of(cwd / found.workdir if found.workdir else cwd)
        if here is None:
            return _blocked(found.name, "git checkout not found (fail-closed).", [])
        root, why = outgoing_checkout(found.name, found.args, here)
        if why:
            return _blocked(found.name, why, [])
        if root is None or root in checked:
            continue
        checked.add(root)
        result = verify_checkout(root)
        if result is not None and result[0] != 0:
            reason = f"`python -X utf8 -m kernel.runner --verify` exited {result[0]} in {root}."
            return _blocked(found.name, reason, result[1])
    return None
