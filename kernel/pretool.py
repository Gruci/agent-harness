"""kernel/pretool.py — PreToolUse dispatch shared by Claude and Codex.

`kernel/hook.py --event PreToolUse` lands here. Edit tools run the isolation guard
(`kernel/isolation.py`: worktree ownership, board registration, main-checkout edits), shell tools run
the irreversible-command guard (`kernel/irreversible.py`), then the worktree naming contract (`kernel/worktree.py`)
and then the exit gate (`kernel/exit_gate.py`: `--verify` in the checkout whose work leaves, before push/PR/merge),
and Claude's `EnterWorktree(name)` is refused. Judgments come back as
`kernel.workspace.Finding`; this module only moves them to (exit, systemMessage). A block is
stderr + exit 2, a warning is exit 0 + `systemMessage` in both runtimes — exit 1 would show a
working warning as a "hook error" and the model would not read it either (dev/HARNESS.md 「단계」).
"""

from __future__ import annotations

import sys
from pathlib import Path

from kernel.hook import edited_paths


def emit_finding(root: Path, finding: object | None, sid8: str) -> tuple[int, str]:
    """Move one kernel Finding to (exit, systemMessage): a block → stderr + exit 2, a warning → systemMessage.
    Both runtimes warn the same way; exit 1 would show a working warning as a "hook error" (dev/HARNESS.md 「단계」)."""
    if finding is None:
        return 0, ""
    from kernel import trace

    trace.TRACE = root / "harness_trace.jsonl"
    level = "block" if finding.block else "warn"
    for msg in getattr(finding, "trace", ()):
        trace.record(finding.hook, finding.kind, sid=sid8, msg=msg, level=level)
    if finding.block:
        print(finding.message, file=sys.stderr)
        return 2, ""
    return 0, str(finding.message)


def pretool_gate(root: Path, payload: dict[str, object], sid: str, core_only: bool = False) -> tuple[int, str]:
    """Core guards first, then the project's own hooks (`kernel/local_hooks.py`) once the core passed.

    `core_only` is the plugin core: it keeps the irreversible guard and the exit gate but enforces no
    working procedure (board registration, worktree naming, main-checkout edits). Project hooks run in both
    modes — they are the project's rules, declared in its profile.
    """
    from kernel import local_hooks, worktree

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    cwd = Path(str(payload.get("cwd") or root))
    sid8 = worktree.session_id8(payload)
    code, warning = _core_gate(root, payload, sid, tool, tool_input, cwd, sid8, core_only)
    if code:
        return code, warning
    local_code, local_warning = emit_finding(root, local_hooks.run(tool, tool_input, cwd), sid8 or "")
    if local_code:
        return local_code, local_warning
    return 0, "\n".join(text for text in (warning, local_warning) if text)


def _core_gate(root: Path, payload: dict[str, object], sid: str, tool: str, tool_input: object, cwd: Path,
               sid8: str | None, core_only: bool) -> tuple[int, str]:
    """EnterWorktree(name) refusal, edit guard, shell irreversible guard + naming + exit gate — in that order."""
    from kernel import exit_gate, irreversible, isolation, worktree

    if not core_only:
        if tool == "EnterWorktree":
            if isinstance(tool_input, dict) and tool_input.get("name") and not tool_input.get("path"):
                return emit_finding(root, worktree.enter_worktree_violation(sid8), sid8 or "")
            return 0, ""
        if isolation.is_edit(tool, tool_input):
            try:
                paths = edited_paths(payload, cwd)
            except ValueError:
                return 0, ""                  # e.g. a patch that only deletes — nothing to guard
            found = isolation.edit_guard(paths, sid8, isolation.changed_lines(tool, tool_input))
            return emit_finding(root, found, sid8 or "")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return 0, ""
    danger = irreversible.guard(command, cwd, sid8)
    if danger is not None:
        return emit_finding(root, danger, sid8 or "")
    if not core_only:
        code, warning = worktree_gate(root, payload, sid)
        if code or warning:
            return code, warning
    return emit_finding(root, exit_gate.exit_gate(command, cwd), sid8 or "")


def worktree_gate(root: Path, payload: dict[str, object], sid: str) -> tuple[int, str]:
    """PreToolUse(shell): block a `git worktree add` outside the naming contract — (exit, systemMessage).

    Shared by both runtimes; EnterWorktree(name) is handled in `pretool_gate` because only
    Claude has that tool. An unknown session id degrades to a screen warning: if the harness
    cannot identify the session, it must not block worktree creation.
    """
    from kernel import trace, workboard, worktree
    from kernel.context import git_common_dir

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    found_add = worktree.worktree_add(command if isinstance(command, str) else "")
    if found_add is None:
        return 0, ""
    token, where = found_add
    sid8 = worktree.session_id8(payload)
    if sid8 is None:
        return 0, "[WORKTREE NAME] No session id — skipping the name check. Check the hook."
    cwd = payload.get("cwd")
    location = Path(cwd) if isinstance(cwd, str) and cwd else None
    if where is not None:                     # 명령 안의 `cd`·`git -C` 가 가리키는 곳에서 만든다
        location = (location / where) if location is not None else Path(where)
    if location is not None and git_common_dir(location) != git_common_dir(root):
        return 0, ""                          # 다른 저장소의 worktree 는 이 레포의 이름 규약 밖이다
    found = worktree.name_violation(token, sid8, workboard.board_dir(), location)
    if found is None:
        return 0, ""
    trace.TRACE = root / "harness_trace.jsonl"
    for msg in found.trace:
        trace.record(found.hook, found.kind, sid=sid8, msg=msg)
    print(found.message, file=sys.stderr)
    return 2, ""
