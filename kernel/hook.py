"""Shared Claude/Codex save and stop gates; stdin is one runtime JSON payload.

PostToolUse reports violations after writes. Stop checks the full checkout,
including untracked source files. Each runtime retains its own tool policy.

PreToolUse is shared by both runtimes and dispatched in kernel/pretool.py (isolation guard,
worktree naming, exit gate). Inside a linked worktree the save and stop gates still run
but only notify (`[WIP]`); blocking resumes at the exit gate before push/PR/merge.
This module runs the checks and folds them into one `kernel.channel.Verdict`; which exit
code and JSON field carries it to the model or the user is decided in kernel/channel.py.

`--plugin` is the Claude Code plugin install: the kernel lives in the plugin folder and checks
the checkout that owns the session cwd (`bind_plugin_target`). It steps aside in a checkout
without harness_profile.py and in a template checkout, whose own hooks run the same gates.

Codex also runs the workspace Stop judgments (board, origin, worktree, mockup, task
artifacts) and the post-save board overlap warning; those branches live in kernel/codex_hook.py
and never change a Claude verdict.
"""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.channel import Delivery, Verdict

DELEGATE_TIMEOUT_SEC = 300             # another checkout's hook: two runner runs plus interpreter and git start
PRETOOL_DELEGATE_SEC = 150             # PreToolUse delegation: one --verify plus start-up, inside the ⑧ hook timeout (180)
SAVE_HEADS = ("[FAIL]", "[DECISION]")  # [TOOL] does not fail a save; the merge check lists it


def checkable(path: Path) -> bool:
    """Use the same configured source patterns as full and save checks."""
    from kernel import profile

    return path.suffix in (".md", ".json") or any(
        fnmatch.fnmatchcase(path.as_posix(), pattern)
        for pattern in (*profile.SOURCE_EXT, *profile.UI_EXT)
    )


def read_payload() -> dict[str, object]:
    """Read one JSON object without waiting for the host to close its pipe."""
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8-sig")()
    text = ""
    while True:
        chunk = sys.stdin.buffer.read1(65536)
        text += utf8.decode(chunk, final=not chunk)
        try:
            value, _end = decoder.raw_decode(text.lstrip())
        except json.JSONDecodeError:
            if chunk:
                continue
            raise
        if not isinstance(value, dict):
            raise ValueError("hook payload must be an object")
        return value


def git_toplevel(cwd: Path) -> Path:
    """cwd 가 속한 git 체크아웃의 최상위. 외부 worktree 와 하위 폴더 cwd 도 맞게 잡는다."""
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=10)
    if result.returncode:
        raise ValueError("git checkout not found")
    return Path(result.stdout.strip()).resolve()


def checkout_root(cwd: Path) -> Path:
    """템플릿 설치의 체크아웃. 자기 커널이 없으면 예외다."""
    root = git_toplevel(cwd)
    if not (root / "kernel" / "runner.py").is_file():
        raise ValueError("checkout has no kernel/runner.py")
    return root


def bind_plugin_target(cwd: Path) -> Path | None:
    """플러그인 훅이 검사할 체크아웃을 정하고 커널에 알린다. 비켜야 하는 체크아웃이면 None 이다.

    사용자 범위로 켠 플러그인은 모든 레포에서 돈다. 프로파일이 없는 레포를 막으면 플러그인을 켠 것만으로 다른 레포가 잠긴다.
    템플릿으로 설치한 체크아웃은 자기 훅이 같은 검사를 돌므로 여기서 또 돌리지 않는다.
    """
    try:
        root = git_toplevel(cwd)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None
    if (root / "kernel" / "hook.py").is_file() or not (root / "harness_profile.py").is_file():
        return None
    os.environ["HARNESS_ROOT"] = str(root)
    return root


def edited_paths(payload: dict[str, object], cwd: Path) -> list[Path]:
    """Normalize Claude paths and all add/update/move destinations in a patch."""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        direct = tool_input.get("file_path")
        if isinstance(direct, str) and direct:
            return [(cwd / direct).resolve()]
        patch = tool_input.get("command", tool_input.get("patch", tool_input.get("input", "")))
    else:
        patch = tool_input
    if not isinstance(patch, str) or "*** Begin Patch" not in patch:
        raise ValueError("file edit payload has no file_path or patch")
    if "*** End Patch" not in patch:
        raise ValueError("incomplete patch payload")
    paths: list[Path] = []
    for line in patch.splitlines():
        for prefix in ("*** Add File: ", "*** Update File: ", "*** Move to: "):
            if line.startswith(prefix):
                path = (cwd / line[len(prefix):]).resolve()
                if path not in paths:
                    paths.append(path)
    return paths


def untracked_paths(root: Path) -> list[Path]:
    """A new source file must not escape Stop because git add was omitted."""
    from kernel.context import is_harness_own

    result = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"],
                            cwd=root, capture_output=True, check=True, timeout=10)
    return [root / name for name in result.stdout.decode("utf-8").split("\0")
            if name and checkable(Path(name))
            and (Path(name).suffix == ".md" or not is_harness_own(name))]


def record_result(root: Path, event: str, sid: str, output: str, error: str = "", level: str = "block") -> None:
    """Observation failure cannot override a gate result. A check that could not run is a `warn` observation."""
    try:
        sys.path.insert(0, str(root))
        from kernel import trace
        trace.TRACE = root / "harness_trace.jsonl"
        name = "check_file_rules" if event == "PostToolUse" else "check_coding_rules"
        if error:
            trace.record(name, "gate_error", sid=sid, msg=error, level="warn")
        else:
            trace.record_runner_output(name, sid, output, level=level)
    except Exception:
        pass


def check_file(root: Path, path: Path) -> str:
    """Enforce the checkout boundary and the shared legacy-path policy."""
    path.relative_to(root)
    sys.path.insert(0, str(root))
    from kernel import profile
    rel = path.as_posix()
    for fragment, suffix in profile.LEGACY_PATHS:
        if fragment in rel and (suffix is None or path.suffix == suffix):
            return f"[FAIL] Legacy path edit (legacy_path) — 1 found\n   - {path}: use the current path."
    return ""


@dataclass(frozen=True)
class Job:
    """One runner run. code: 0 clean, 1 could not run, 2 a violation or a crash at Stop."""
    code: int = 0
    lines: tuple[str, ...] = ()        # what the model reads: verdict lines, or why the check could not run
    decisions: tuple[str, ...] = ()    # needs_decision items for kernel/graph_notifications.py
    stdout: str = ""                   # raw runner output — the trace parses its [FAIL] heads
    error: str = ""                    # trace message when the check itself failed


def run_job(root: Path, args: list[str], event: str) -> Job:
    """Run the runner once: no `args` is the Stop full run, `--file <path>` one file.
    A timeout is 'could not run' at both events; a crash still blocks a Stop (dev/HARNESS.md 「실패 시 방향」)."""
    from kernel.context import runner_command
    from kernel.exit_gate import VERDICT_HEADS, VERIFY_TIMEOUT_SEC, verdict_lines

    command_line = runner_command(root, *args)
    if command_line is None:
        return Job()                      # 하네스가 연결되지 않은 체크아웃 — 검사할 러너도 프로파일도 없다
    argv, env = command_line
    crash = 2 if event == "Stop" else 1
    try:
        result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=VERIFY_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        message = (f"Check could not finish within {VERIFY_TIMEOUT_SEC}s — not a violation; "
                   "the merge check runs it again.")
        return Job(1, (message,), error=message)
    except OSError as exc:
        message = f"Check could not run: {type(exc).__name__}"
        return Job(crash, (message,), error=message)
    decisions = tuple(line.strip().removeprefix("- ") for line in result.stdout.splitlines()
                      if "needs_decision" in line)
    if result.returncode in (0, 3):
        return Job(decisions=decisions)
    if "[FAIL]" in result.stdout:
        lines = ["Gate violation — fix and re-verify.",
                 *verdict_lines(result.stdout, SAVE_HEADS if args else VERDICT_HEADS)]
        return Job(2, tuple(lines), decisions, result.stdout)
    message = "Check could not run — inspect the checker itself."
    return Job(crash, (message, *result.stderr.strip().splitlines()[-5:]), decisions, result.stdout, message)


def run_checks(root: Path, paths: list[Path], event: str, sid: str, level: str) -> Verdict:
    """Legacy-path check per file, `--file` jobs (at Stop only untracked MD — the full run sees untracked sources)
    and the Stop full run, folded into one Verdict. Violations are observed at `level`; a worktree 'could not run' is 1."""
    from kernel import channel, graph_notifications

    code, lines, decisions = 0, [], []
    jobs: list[list[str]] = []
    for path in paths:
        legacy = check_file(root, path)
        if legacy:
            lines.extend(legacy.splitlines())
            record_result(root, event, sid, legacy, level=level)
            code = 2
        elif path.is_file() and checkable(path) and (event != "Stop" or path.suffix == ".md"):
            jobs.append(["--file", str(path)])
    if event == "Stop":
        jobs.append([])
    for args in jobs:
        job = run_job(root, args, event)
        if job.error:
            record_result(root, event, sid, "", job.error)
            code = max(code, 1 if level == "wip" else job.code)
        elif job.code:
            record_result(root, event, sid, job.stdout, level=level)
            code = max(code, job.code)
        lines.extend(line for line in job.lines if line not in lines)
        decisions.extend(job.decisions)
    notices = tuple("[DECISION] " + json.dumps(notice, ensure_ascii=False)
                    for notice in graph_notifications.report(root, decisions, sid))
    return channel.Verdict(code, tuple(lines), notices)


def refresh_projection(root: Path) -> None:
    """The hook processor regenerates maps; validation gates remain read-only."""
    from kernel import component_graph, feature_map, graph_workflow

    if not (root / component_graph.GRAPH_PATH).exists():
        return
    try:
        graph = component_graph.load(root)
    except (OSError, ValueError):
        return  # The runner reports the malformed canonical document.
    if not graph_workflow.check_approval(root, graph):
        feature_map.generate(root)


def _outgoing(payload: dict[str, object]) -> bool:
    """Does this PreToolUse payload carry a command that leaves for the main line (push, PR, merge)?"""
    from kernel.exit_gate import exit_commands

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return bool(command) and bool(exit_commands(str(command)))


def _delegate(root: Path, agent: str, event: str, payload: dict[str, object]) -> int:
    """Re-run the hook with the target checkout's own kernel; an imported kernel package cannot be rebound.
    A timeout is 'could not run' (1), except an outgoing command at PreToolUse: the exit gate is fail-closed (2)."""
    if not (root / "kernel" / "hook.py").is_file():
        raise RuntimeError("target checkout has no kernel/hook.py")
    limit = PRETOOL_DELEGATE_SEC if event == "PreToolUse" else DELEGATE_TIMEOUT_SEC
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "kernel.hook", "--agent", agent, "--event", event],
            cwd=root, input=json.dumps(payload), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=limit,
        )
    except subprocess.TimeoutExpired:
        print(f"Check could not finish within {limit}s in {root} — not a violation; "
              "the merge check runs it again.", file=sys.stderr)
        return 2 if event == "PreToolUse" and _outgoing(payload) else 1
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode not in (0, 1, 2):
        raise RuntimeError("the target checkout's hook ended with an unexpected exit code")
    return result.returncode                  # 1 is 'could not run' — pass it through


def save_or_stop(root: Path, payload: dict[str, object], cwd: Path, event: str, agent: str,
                 sid: str) -> Delivery:
    """PostToolUse and Stop: run the checks, then let kernel/channel.py route the verdict.
    A subagent's save (`agent_id` in the payload) does not take what the main conversation's Stop held."""
    from kernel import channel, codex_hook, isolation

    paths = untracked_paths(root) if event == "Stop" else edited_paths(payload, cwd)
    refresh_projection(root)
    wip = isolation.in_worktree(root) or bool(paths and all(isolation.in_worktree(p) for p in paths))
    verdict = run_checks(root, paths, event, sid, "wip" if wip else "block")
    small = _small_warning(paths, sid) if event == "PostToolUse" and wip else ""
    if agent == "codex":
        if event == "Stop":
            return channel.for_codex(verdict, wip, codex_hook.workspace_findings(root, sid))
        overlap = "\n".join(part for part in (codex_hook.board_overlaps(root, paths, sid), small) if part)
        return channel.for_codex(verdict, wip, overlap=overlap)
    if event == "Stop":
        channel.hold(root, sid[:8], channel.held_text(verdict, wip))
        return channel.for_claude(verdict, event, wip)
    main_conversation = "agent_id" not in payload
    held = channel.take(root, sid[:8]) if main_conversation and verdict.code != 1 else ""
    return channel.for_claude(verdict, event, wip, held, small)


def _small_warning(paths: list[Path], sid: str) -> str:
    """소규모 과업의 조기 알림(`kernel/finish_checks.py`). 저장한 파일의 worktree 를 잰다. 알림이 실패해도 저장 판정은 그대로다."""
    from kernel import finish_checks, isolation

    try:
        tree = isolation.checkout_of(paths[0]) if paths else None
        return finish_checks.small_warning(tree, sid) if tree is not None else ""
    except Exception:                 # 관찰보다 덜 중요한 안내다 — 실패를 저장 결과에 섞지 않는다
        return ""


def _crash_code(event: str, root: Path | None) -> int:
    """A broken profile or kernel is an infrastructure error, not a violation: 1 at a save; at a Stop 2 in the shared
    checkout but 1 inside a linked worktree, where a mid-edit crash must not block every turn (dev/LESSONS.md §25)."""
    if event != "Stop":
        return 1
    if root is None:
        return 2
    try:
        from kernel import channel
        return 1 if channel.linked_worktree(root) else 2
    except Exception:
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("claude", "codex"), required=True)
    parser.add_argument("--event", choices=("PreToolUse", "PostToolUse", "Stop"), required=True)
    parser.add_argument("--plugin", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = read_payload()
    except (ValueError, UnicodeError) as exc:
        print(f"Hook input warning: {exc}", file=sys.stderr)
        if args.event != "Stop":
            return 1
        payload = {}
    cwd = Path(str(payload.get("cwd") or Path.cwd())).resolve()
    sid = str(payload.get("session_id") or "")
    root: Path | None = None
    try:
        if args.plugin:
            root = bind_plugin_target(cwd)
            if root is None:
                return 0                      # 하네스가 연결되지 않았거나 템플릿 체크아웃 — 비킨다
        else:
            root = checkout_root(cwd)
            if root != Path(__file__).resolve().parents[1]:
                return _delegate(root, args.agent, args.event, payload)
            sys.path.insert(0, str(root))  # Direct script launch starts with kernel/ on sys.path.
        from kernel import channel
        if args.event == "PreToolUse":
            from kernel import pretool
            code, warning = pretool.pretool_gate(root, payload, sid, core_only=args.plugin)
            delivery = channel.Delivery(code, "", {"systemMessage": warning} if warning else {})
        else:
            delivery = save_or_stop(root, payload, cwd, args.event, args.agent, sid)
    except Exception as exc:
        print(f"Check could not run: {exc}", file=sys.stderr)
        return _crash_code(args.event, root)
    return channel.emit(delivery, args.agent)


if __name__ == "__main__":
    sys.exit(main())
