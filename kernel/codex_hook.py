"""Codex-only branches of the shared save and stop gates (`kernel/hook.py`).

Claude keeps one wrapper per workspace judgment in .claude/hooks and warns about board
overlaps at PreToolUse (⑧-5). Codex has neither, so its PostToolUse adds the overlap warning
after the save and its Stop runs the workspace judgments from kernel.workspace. Nothing here
changes a Claude verdict; `kernel/hook.py` calls these only when `--agent codex`.
"""

from __future__ import annotations

from pathlib import Path

OVERLAP_HEAD = ("[WORKBOARD] Another task claims this area — if the scope is the same, add a line to that task's items"
                " and leave it to that session (join), or branch a worktree from that task's branch (stack). If the lines do not overlap, go ahead (warning, not a block):")


def board_overlaps(root: Path, paths: list[Path], sid: str) -> str:
    """Warn when an edit lands inside another task's claimed globs; never block. Empty when nothing overlaps.

    Failures fall open: a missing board reads as "no open tasks", which never stops a session.
    """
    try:
        from kernel import workboard
        board = workboard.board_dir()
        hits: list[str] = []
        for path in paths:
            for hit in workboard.overlaps(path, sid[:8], board, root):
                line = f"{path.name}: {hit}"
                if line not in hits:
                    hits.append(line)
        if not hits:
            return ""
        from kernel import trace
        trace.TRACE = root / "harness_trace.jsonl"
        trace.record("check_workboard_overlap", "workboard_overlap",
                     sid=sid[:8], msg=f"{len(hits)} found (codex)", level="warn")
        return "\n".join([OVERLAP_HEAD, *(f"  {line}" for line in hits)])
    except Exception:
        return ""


def workspace_findings(root: Path, sid: str) -> list[object]:
    """Run the shared Stop judgments and record each one; observation never blocks."""
    from kernel import trace, workspace

    findings = workspace.stop_findings(sid)
    try:
        trace.TRACE = root / "harness_trace.jsonl"
        for finding in findings:
            for msg in finding.trace:
                trace.record(finding.hook, finding.kind, sid=sid, msg=msg,
                             level="block" if finding.block else "warn")
    except Exception:
        pass
    return list(findings)
