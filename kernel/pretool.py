"""kernel/pretool.py — PreToolUse dispatch shared by Claude and Codex.

`kernel/hook.py --event PreToolUse` lands here. Edit tools run the isolation guard
(`kernel/isolation.py`: board registration, main-checkout edits), shell tools run the
worktree naming contract (`kernel/worktree.py`) and then the exit gate (`--verify` before
push/PR/merge), and Claude's `EnterWorktree(name)` is refused. Judgments come back as
`kernel.workspace.Finding`; this module only moves them to exit codes and channels.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kernel.hook import edited_paths


def emit_finding(root: Path, finding: object | None, sid8: str, agent: str) -> tuple[int, str]:
    """Move one kernel Finding to (exit, Codex systemMessage): block → stderr + 2, warn → runtime channel."""
    if finding is None:
        return 0, ""
    from kernel import trace

    trace.TRACE = root / "harness_trace.jsonl"
    for msg in getattr(finding, "trace", ()):
        trace.record(finding.hook, finding.kind, sid=sid8, msg=msg)
    if finding.block:
        print(finding.message, file=sys.stderr)
        return 2, ""
    if agent == "claude":
        print(finding.message, file=sys.stderr)
        return 1, ""
    return 0, str(finding.message)


def pretool_gate(root: Path, payload: dict[str, object], sid: str, agent: str) -> tuple[int, str]:
    """EnterWorktree(name) refusal, edit guard, shell naming + exit gate — in that order."""
    from kernel import isolation, worktree

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    cwd = Path(str(payload.get("cwd") or root))
    sid8 = worktree.session_id8(payload)
    if tool == "EnterWorktree":
        if isinstance(tool_input, dict) and tool_input.get("name") and not tool_input.get("path"):
            return emit_finding(root, worktree.enter_worktree_violation(sid8), sid8 or "", agent)
        return 0, ""
    if isolation.is_edit(tool, tool_input):
        try:
            paths = edited_paths(payload, cwd)
        except ValueError:
            return 0, ""                      # e.g. a patch that only deletes — nothing to guard
        found = isolation.edit_guard(paths, sid8, isolation.changed_lines(tool, tool_input))
        return emit_finding(root, found, sid8 or "", agent)
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return 0, ""
    code = worktree_gate(root, payload, sid)
    if code:
        return code, ""
    return emit_finding(root, isolation.exit_gate(command, cwd), sid8 or "", agent)


def worktree_gate(root: Path, payload: dict[str, object], sid: str) -> int:
    """PreToolUse(shell): block a `git worktree add` outside the naming contract.

    Shared by both runtimes; EnterWorktree(name) is handled in `pretool_gate` because only
    Claude has that tool. An unknown session id degrades to a warning (exit 1): if the harness
    cannot identify the session, it must not block worktree creation.
    """
    from kernel import trace, workboard, worktree

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    token = worktree.worktree_add_path(command if isinstance(command, str) else "")
    if not token:
        return 0
    sid8 = worktree.session_id8(payload)
    if sid8 is None:
        print("[WORKTREE NAME] 세션 식별자를 못 구했다 — 이름 검사를 건너뛴다. 훅을 점검하라.",
              file=sys.stderr)
        return 1
    cwd = payload.get("cwd")
    found = worktree.name_violation(token, sid8, workboard.board_dir(),
                                    Path(cwd) if isinstance(cwd, str) and cwd else None)
    if found is None:
        return 0
    trace.TRACE = root / "harness_trace.jsonl"
    for msg in found.trace:
        trace.record(found.hook, found.kind, sid=sid8, msg=msg)
    print(found.message, file=sys.stderr)
    return 2
