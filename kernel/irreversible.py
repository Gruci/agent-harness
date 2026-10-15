"""kernel/irreversible.py — 되돌릴 수 없는 셸 명령을 실행 전에 막는다.

Claude PreToolUse(`check_pretool.py`)와 Codex 진입점이 `kernel/pretool.py` 에서 같은 판정을 부른다.
나올 때 검사(⑧-7)와 같은 자리다. 셸 쓰기 판정(⑧-1·⑧-3)을 런타임별로 둔 것(`dev/REJECTED.md`)과 달리,
여기서 막는 것은 나중에 게이트가 다시 잡아 줄 수 없는 손실이다.

## 왜 — 승인 프롬프트가 꺼진 세션

이 하네스는 비코더가 승인 프롬프트 없이 쓰도록 프로젝트 설정(`.claude/settings.json`)이 `bypassPermissions` 다.
그 모드에서도 Claude Code 는 파일시스템 루트·홈·작업 폴더와 그 부모를 지우는 `rm` 은 사람에게 묻는다(critical path).
그 밖은 묻지 않는다. 남은 것 가운데 git 으로도 되돌릴 수 없는 것만 막는다.

경로에 값을 모르는 변수나 패턴 글롭(`*.tmp`)이 남거나 git 조회가 실패하면 막지 않는다. 추측으로 막으면 복구
명령까지 막힌다(`dev/HARNESS.md` 「단계」). 변수 아래 삭제는 Claude Code 의 critical path 검사가 따로 묻는다.
막힌 명령은 사람이 정한다. 안내문은 무엇을 왜 하려 했는지 사용자에게 보고하라고 한다.
git 조회는 위험한 모양의 명령에서만 한다. 나머지 셸 명령은 문자열만 읽고 지나간다.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from kernel import isolation, shell
from kernel.context import default_branch
from kernel.workboard import board_dir, branch_of, task_files
from kernel.workspace import Finding
from kernel.worktree import parse_worktrees

HOOK_NAME = "check_pretool"
_CLUSTER = r"-[A-Za-z]*{}[A-Za-z]*"
_PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--receive-pack", "--exec", "--repo"})
_DELETERS = frozenset({"rm", "rmdir", "rd", "remove-item", "ri", "del", "erase"})
_CMD_DELETERS = frozenset({"rmdir", "rd", "del", "erase"})
_PS_VALUE_PARAMS = frozenset({"-filter", "-include", "-exclude", "-stream", "-credential"})
_SHARED_DIRS = (".git", "workboard", "worktrees")
_ADVICE = {
    "push": "Push your own branch and merge it through the normal finish (`python -X utf8 -m kernel.task finish`). "
            "Rewriting or deleting the default branch is the user's call — explain why and leave it to them.",
    "reset": "Run it inside your own worktree. To bring the main checkout up to date use "
             "`git merge --ff-only origin/<default-branch>`. Other sessions' plans, mockups and board files live here.",
    "claim": "Do not delete another session's work. Report the task to the user and let them decide.",
    "delete": "git cannot bring it back. Tell the user what you wanted to delete and why, and leave the deletion to them. "
              "Scratch files belong in the temp folder, where deletion is allowed.",
}


def guard(command: str, cwd: Path, sid8: str | None, board: Path | None = None) -> Finding | None:
    """되돌릴 수 없는 명령이면 차단 finding 을 돌려준다. 판정할 수 없으면 None 이다."""
    for call in shell.commands(command):
        place = Path(shell.join(cwd.as_posix(), call.workdir) or cwd)
        parsed = shell.git_args(call.argv)
        found = _git_reason(parsed, place, sid8, board) if parsed else _delete_reason(call.argv, place, board)
        if found:
            kind, reason = found
            head = " ".join(call.argv[:5])
            return Finding(HOOK_NAME, "irreversible", True,
                           f"[IRREVERSIBLE] `{head}` {reason} — blocked.\n{_ADVICE[kind]}", (f"{kind}: {head}",))
    return None


def _board(board: Path | None) -> Path:
    return (board_dir() if board is None else board).resolve()


def _git_reason(parsed: tuple[str | None, tuple[str, ...]], place: Path, sid8: str | None,
                board: Path | None) -> tuple[str, str] | None:
    git_dir, rest = parsed
    where = place / git_dir if git_dir else place
    sub, args = (rest[0], rest[1:]) if rest else ("", ())
    if sub == "push":
        target = _overwritten_default(args, where)
        return ("push", f"rewrites or deletes the default branch `{target}` on the remote") if target else None
    if _discards(sub, args):
        on_main = isolation.locate(where, _board(board).parent) == "main"
        return ("reset", "discards uncommitted work in the shared main checkout") if on_main else None
    if sub == "branch" and _force_delete_branch(args):
        names = [token for token in args if not token.startswith("-")]
        owner = next((found for found in (_owner(name, sid8, _board(board)) for name in names) if found), None)
        return ("claim", f"force-deletes a branch claimed by workboard/{owner}.md") if owner else None
    if sub == "worktree" and args[:1] == ("remove",) and any(token in ("--force", "-f") for token in args[1:]):
        path = next((token for token in args[1:] if not token.startswith("-")), None)
        branch = _worktree_branch(where / shell.native(path), where) if path else None
        owner = _owner(branch, sid8, _board(board)) if branch else None
        return ("claim", f"force-removes a worktree claimed by workboard/{owner}.md") if owner else None
    return None


def _discards(sub: str, args: tuple[str, ...]) -> bool:
    """커밋 안 한 작업을 버리는 git 명령인가 — `reset --hard`·강제 `clean`·경로를 덮는 `checkout`·작업 트리 `restore`."""
    if sub == "reset":
        return "--hard" in args
    if sub == "clean":
        return _forced_clean(args)
    if sub == "checkout":
        return "--" in args or "." in args
    if sub == "restore":
        return not ({"--staged", "-S"} & set(args)) or bool({"--worktree", "-W"} & set(args))
    return False


def _flag(args: tuple[str, ...], long: str, short: str) -> bool:
    return long in args or any(re.fullmatch(_CLUSTER.format(short), token) for token in args)


def _overwritten_default(args: tuple[str, ...], where: Path) -> str | None:
    """강제·삭제 push 가 기본 브랜치를 겨누면 그 이름. 드라이런이면 None."""
    if _flag(args, "--dry-run", "n"):
        return None
    refspecs = _push_operands(args)[1:]
    forced = (_flag(args, "--force", "f") or "--mirror" in args
              or any(token.startswith("--force-with-lease") for token in args)
              or any(spec.startswith("+") for spec in refspecs))
    deleting = _flag(args, "--delete", "d") or any(spec.startswith(":") for spec in refspecs)
    if not (forced or deleting):
        return None
    protected = {"main", "master", *(name for name in (default_branch(),) if name)}
    if any(token in ("--all", "--branches", "--mirror") for token in args):
        return sorted(protected)[0]
    targets = [_destination(spec, where) for spec in refspecs] or [_current_branch(where)]
    return next((name for name in targets if name in protected), None)


def _push_operands(args: tuple[str, ...]) -> list[str]:
    operands: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
        elif token in _PUSH_VALUE_OPTIONS:
            skip = True
        elif not token.startswith("-"):
            operands.append(token)
    return operands


def _destination(refspec: str, where: Path) -> str | None:
    spec = refspec.lstrip("+")
    target = (spec.split(":", 1)[1] if ":" in spec else spec).removeprefix("refs/heads/")
    return _current_branch(where) if target in ("HEAD", "@") else target


def _current_branch(where: Path) -> str | None:
    name = _git(where, "rev-parse", "--abbrev-ref", "HEAD")
    return None if name in (None, "HEAD") else name


def _forced_clean(args: tuple[str, ...]) -> bool:
    return not _flag(args, "--dry-run", "n") and _flag(args, "--force", "f")


def _force_delete_branch(args: tuple[str, ...]) -> bool:
    if any(re.fullmatch(_CLUSTER.format("D"), token) for token in args):
        return True
    return _flag(args, "--delete", "d") and _flag(args, "--force", "f")


def _owner(branch: str, sid8: str | None, board: Path) -> str | None:
    """이 브랜치를 잡은 남의 과업 파일 이름. 내 `#sid` 가 든 파일이거나 아무도 안 잡았으면 None."""
    for path, text in task_files(board):
        if branch_of(text) == branch and not (sid8 and f"#sid:{sid8}" in text):
            return path.stem
    return None


def _worktree_branch(path: Path, where: Path) -> str | None:
    porcelain = _git(where, "worktree", "list", "--porcelain", strip=False)
    if porcelain is None:
        return None
    target = path.resolve()
    return next((tree["branch"] for tree in parse_worktrees(porcelain) if Path(tree["path"]).resolve() == target), None)


def _git(where: Path, *args: str, strip: bool = True) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() if strip else done.stdout


def _delete_reason(argv: tuple[str, ...], place: Path, board: Path | None) -> tuple[str, str] | None:
    name = shell.program(argv[0])
    if name not in _DELETERS or not _recursive(argv[1:]):
        return None
    shared = _board(board).parent
    for token in _delete_targets(name, argv[1:]):
        path = _resolve(token, place)
        where = _protected_place(path, shared) if path else None
        if where:
            return "delete", f"recursively deletes {where}"
    return None


def _recursive(args: tuple[str, ...]) -> bool:
    for token in args:
        low = token.lower()
        if low in ("--recursive", "/s") or low.startswith("-rec") or (re.fullmatch(r"-[a-z]{1,4}", low) and "r" in low):
            return True
    return False


def _delete_targets(name: str, args: tuple[str, ...]) -> list[str]:
    """삭제 대상 토큰. PowerShell 의 `-Filter` 류 값과 cmd 의 `/s` 류 스위치는 대상이 아니다."""
    targets: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
        elif token.lower() in _PS_VALUE_PARAMS:
            skip = True
        elif token.startswith("-") or (name in _CMD_DELETERS and re.fullmatch(r"/[A-Za-z]", token)):
            continue
        else:
            targets += [part for part in token.split(",") if part]
    return targets


def _resolve(token: str, place: Path) -> Path | None:
    """삭제 대상의 실제 경로. 끝이 `*` 하나면 그 폴더를 비우는 것으로 본다. 모르는 변수·패턴 글롭이면 None."""
    text = os.path.expandvars(re.sub(r"\$env:(\w+)", lambda found: os.environ.get(found.group(1), found.group(0)), token))
    if "$" in text or "%" in text:
        return None
    path = Path(shell.native(text))
    path = path if path.is_absolute() else place / path
    if path.name in ("*", "*.*"):
        path = path.parent
    if any(mark in part for part in path.parts for mark in "*?["):
        return None
    try:
        return path.resolve()
    except OSError:
        return None


def _protected_place(path: Path, shared: Path) -> str | None:
    if path == shared or path in shared.parents:
        return f"the repo root or a folder above it ({path.as_posix()})"
    for name in _SHARED_DIRS:
        anchor = shared / name
        if path == anchor or (name != "worktrees" and anchor in path.parents):
            return f"`{name}/` — shared state of every session"
        if name == "worktrees" and path.parent == anchor:
            return f"the worktree folder `{path.name}` — use `git worktree remove`"
    if shared in path.parents:
        return None
    if Path(tempfile.gettempdir()).resolve() in path.parents:
        return None
    return f"a folder outside the repo ({path.as_posix()})"
