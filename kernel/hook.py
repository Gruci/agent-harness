"""Shared Claude/Codex save and stop gates; stdin is one runtime JSON payload.

PostToolUse reports violations after writes. Stop checks the full checkout,
including untracked source files. Each runtime retains its own tool policy.

Codex also routes PreToolUse(Bash) here for the worktree naming contract and runs the
workspace Stop judgments (board, origin, worktree, mockup, task artifacts) from
kernel.workspace. Claude keeps one wrapper per judgment in .claude/hooks, so the
Codex-only branches below never change a Claude verdict.
"""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

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


def checkout_root(cwd: Path) -> Path:
    """Resolve the actual checkout, including external worktrees and nested cwd."""
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=10)
    if result.returncode:
        raise ValueError("git checkout not found")
    root = Path(result.stdout.strip()).resolve()
    if not (root / "kernel" / "runner.py").is_file():
        raise ValueError("checkout has no kernel/runner.py")
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


def record_result(root: Path, event: str, sid: str, output: str, error: str = "") -> None:
    """Observation failure cannot override a gate result."""
    try:
        sys.path.insert(0, str(root))
        from kernel import trace
        trace.TRACE = root / "harness_trace.jsonl"
        name = "check_file_rules" if event == "PostToolUse" else "check_coding_rules"
        if error:
            trace.record(name, "gate_error", sid=sid, msg=error)
        else:
            trace.record_runner_output(name, sid, output)
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
            return f"[FAIL] 레거시 경로 편집 금지 (legacy_path) — 1건\n   - {path}: 현행 경로를 사용하라."
    return ""


def board_overlaps(root: Path, paths: list[Path], sid: str) -> list[str]:
    """Warn when an edit lands inside another task's claimed globs; never block.

    Codex has no pre-edit hook event, so its overlap warning fires here after the save —
    the Claude side runs the same kernel.workboard judgment at PreToolUse. Failures fall
    open: a missing board reads as "no open tasks", which never stops a session.
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
        if hits:
            from kernel import trace
            trace.TRACE = root / "harness_trace.jsonl"
            trace.record("check_workboard_overlap", "workboard_overlap",
                         sid=sid[:8], msg=f"{len(hits)}건 (codex)")
        return hits
    except Exception:
        return []


def run_checks(root: Path, paths: list[Path], event: str, sid: str) -> int:
    """Run file checks plus the Stop full gate, preserving failure severity."""
    jobs: list[list[str]] = []
    code = 0
    decision_messages: list[str] = []
    for path in paths:
        legacy = check_file(root, path)
        if legacy:
            print(legacy, file=sys.stderr)
            record_result(root, event, sid, legacy)
            code = 2
        elif path.is_file() and checkable(path):
            jobs.append(["--file", str(path)])
    if event == "Stop":
        jobs.append([])
    for args in jobs:
        try:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "kernel.runner", *args],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60 if event == "Stop" else 30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            message = f"검사 불능: {type(exc).__name__}"
            print(message, file=sys.stderr)
            record_result(root, event, sid, "", message)
            code = max(code, 2 if event == "Stop" else 1)
            continue
        if result.returncode == 0:
            continue
        decisions = [line.strip().removeprefix("- ") for line in result.stdout.splitlines()
                     if "needs_decision" in line]
        decision_messages.extend(decisions)
        if result.returncode == 3:
            continue
        failure = "[FAIL]" in result.stdout
        message = "게이트 위반 — 수정 후 재검증하라." if failure else "검사 불능 — 검사기 자체를 점검하라."
        print(message, file=sys.stderr)
        print(result.stdout + result.stderr, file=sys.stderr)
        record_result(root, event, sid, result.stdout, "" if failure else message)
        code = max(code, 2 if failure or event == "Stop" else 1)
    from kernel import graph_notifications
    for notice in graph_notifications.report(root, decision_messages, sid):
        print("[DECISION] " + json.dumps(notice, ensure_ascii=False), file=sys.stderr)
    return code


def worktree_gate(root: Path, payload: dict[str, object], sid: str) -> int:
    """Codex PreToolUse(Bash): block a `git worktree add` outside the naming contract.

    Same judgment and wording as the Claude hook; only `git worktree add` is in scope
    because Codex has no EnterWorktree tool. Unknown session id degrades to a warning
    (exit 1): a harness that cannot identify itself must not stop isolation.
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


def workspace_verdict(findings: list[object]) -> tuple[int, str]:
    """Fold workspace findings into a Codex Stop result: (exit code, systemMessage).

    A blocking finding goes to stderr with exit 2 and drags the warnings along, since a
    blocked turn continues and stderr is what the model reads. Warnings alone return
    exit 0 with the text for `{"systemMessage": ...}`, the only warning channel Codex has.
    """
    blocking = [f for f in findings if getattr(f, "block", False)]
    warnings = [f for f in findings if not getattr(f, "block", False)]
    if blocking:
        for finding in blocking + warnings:
            print(finding.message, file=sys.stderr)
        return 2, ""
    return 0, "\n".join(finding.message for finding in warnings)


def workspace_findings(root: Path, sid: str) -> list[object]:
    """Run the shared Stop judgments and record each one; observation never blocks."""
    from kernel import trace, workspace

    findings = workspace.stop_findings(sid)
    try:
        trace.TRACE = root / "harness_trace.jsonl"
        for finding in findings:
            for msg in finding.trace:
                trace.record(finding.hook, finding.kind, sid=sid, msg=msg)
    except Exception:
        pass
    return list(findings)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("claude", "codex"), required=True)
    parser.add_argument("--event", choices=("PreToolUse", "PostToolUse", "Stop"), required=True)
    args = parser.parse_args(argv)
    try:
        payload = read_payload()
    except (ValueError, UnicodeError) as exc:
        print(f"훅 입력 경고: {exc}", file=sys.stderr)
        if args.event != "Stop":
            return 1
        payload = {}
    cwd = Path(str(payload.get("cwd") or Path.cwd())).resolve()
    sid = str(payload.get("session_id") or "")
    system_message = ""
    try:
        root = checkout_root(cwd)
        if root != Path(__file__).resolve().parents[1]:
            # Inserting sys.path cannot rebind an already imported kernel package.
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "kernel.hook",
                 "--agent", args.agent, "--event", args.event], cwd=root,
                input=json.dumps(payload), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if result.returncode not in (0, 2):
                raise RuntimeError("대상 체크아웃의 훅 검사 불능")
            return result.returncode
        sys.path.insert(0, str(root))  # Direct script launch starts with kernel/ on sys.path.
        if args.event == "PreToolUse":
            code = worktree_gate(root, payload, sid)
            if code == 0 and args.agent == "codex":
                print("{}")
            return code
        paths = untracked_paths(root) if args.event == "Stop" else edited_paths(payload, cwd)
        refresh_projection(root)
        code = run_checks(root, paths, args.event, sid)
        if args.event == "Stop" and args.agent == "codex":
            verdict, system_message = workspace_verdict(workspace_findings(root, sid))
            code = max(code, verdict)
            if code and system_message:
                print(system_message, file=sys.stderr)  # A blocked turn reads stderr, not JSON.
        if args.event == "PostToolUse":
            warned = board_overlaps(root, paths, sid)
            if warned:
                print("[WORKBOARD] 다른 과업이 잡은 곳이다 — 같은 범위면 합류하거나 그 브랜치 위에"
                      " 쌓는다. 겹치는 줄이 아니면 그대로 진행해도 된다 (경고이지 차단이 아니다):",
                      file=sys.stderr)
                for line in warned:
                    print(f"  {line}", file=sys.stderr)
                code = max(code, 1)
    except Exception as exc:
        # A broken executable profile is an infrastructure error, not a violation.
        print(f"검사 불능: {exc}", file=sys.stderr)
        return 2 if args.event == "Stop" else 1
    if code == 0 and args.agent == "codex":
        print(json.dumps({"systemMessage": system_message}, ensure_ascii=False) if system_message else "{}")
    return code


if __name__ == "__main__":
    sys.exit(main())
