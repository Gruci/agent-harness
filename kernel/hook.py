"""Shared Claude/Codex save and stop gates; stdin is one runtime JSON payload.

PostToolUse reports violations after writes. Stop checks the full checkout,
including untracked source files. Each runtime retains its own tool policy.

PreToolUse is shared by both runtimes and dispatched in kernel/pretool.py (isolation guard,
worktree naming, exit gate). Inside a linked worktree the save and stop gates still run
but only notify (`[WIP]`); blocking resumes at the exit gate before push/PR/merge.

`--plugin` is the Claude Code plugin install: the kernel lives in the plugin folder and checks
the checkout that owns the session cwd (`bind_plugin_target`). It steps aside in a checkout
without harness_profile.py and in a template checkout, whose own hooks run the same gates.

Codex also runs the workspace Stop judgments (board, origin, worktree, mockup, task
artifacts) from kernel.workspace. Claude keeps one wrapper per judgment in .claude/hooks,
so the Codex-only branches below never change a Claude verdict.
"""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TextIO

WIP_HEAD = ("[WIP] 합칠 때 막힐 항목 — worktree 안에서는 막지 않는다. "
            "push·PR 전 `python -X utf8 -m kernel.runner --verify` 가 exit 0 이어야 나간다.")

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


def run_checks(root: Path, paths: list[Path], event: str, sid: str, out: TextIO | None = None) -> int:
    """Run file checks plus the Stop full gate, preserving failure severity.

    `out` receives every message (stderr by default); a worktree caller passes a buffer so
    the same verdict can be re-emitted as a `[WIP]` notice instead of a block.
    """
    from kernel.context import runner_command

    out = sys.stderr if out is None else out
    jobs: list[list[str]] = []
    code = 0
    decision_messages: list[str] = []
    for path in paths:
        legacy = check_file(root, path)
        if legacy:
            print(legacy, file=out)
            record_result(root, event, sid, legacy)
            code = 2
        elif path.is_file() and checkable(path):
            jobs.append(["--file", str(path)])
    if event == "Stop":
        jobs.append([])
    for args in jobs:
        command_line = runner_command(root, *args)
        if command_line is None:
            continue                          # 하네스가 연결되지 않은 체크아웃 — 검사할 러너도 프로파일도 없다
        argv, env = command_line
        try:
            result = subprocess.run(
                argv, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60 if event == "Stop" else 30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            message = f"검사 불능: {type(exc).__name__}"
            print(message, file=out)
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
        print(message, file=out)
        print(result.stdout + result.stderr, file=out)
        record_result(root, event, sid, result.stdout, "" if failure else message)
        code = max(code, 2 if failure or event == "Stop" else 1)
    from kernel import graph_notifications
    for notice in graph_notifications.report(root, decision_messages, sid):
        print("[DECISION] " + json.dumps(notice, ensure_ascii=False), file=out)
    return code


def wip_checks(root: Path, paths: list[Path], event: str, sid: str, agent: str) -> tuple[int, str]:
    """Inside a worktree the gates judge but do not block: (exit, Codex systemMessage).

    Claude reads exit 1 + stderr as a user-facing notice; Codex has only the systemMessage
    channel for a non-blocking message. Trace records still land, so the retro sees them.
    """
    buffer = io.StringIO()
    code = run_checks(root, paths, event, sid, buffer)
    if code == 0:
        return 0, ""
    text = WIP_HEAD + "\n" + buffer.getvalue().rstrip()
    if agent == "claude":
        print(text, file=sys.stderr)
        return 1, ""
    return 0, text


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


def _delegate(root: Path, agent: str, event: str, payload: dict[str, object]) -> int:
    """Re-run the hook with the target checkout's own kernel; an imported kernel package cannot be rebound."""
    if not (root / "kernel" / "hook.py").is_file():
        raise RuntimeError("대상 체크아웃에 kernel/hook.py 가 없다")
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kernel.hook", "--agent", agent, "--event", event],
        cwd=root, input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode not in (0, 1, 2):
        raise RuntimeError("대상 체크아웃의 훅이 예상 밖의 종료 코드로 끝났다")
    return result.returncode                  # 1 is a notice ([WIP], overlap) — pass it through


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("claude", "codex"), required=True)
    parser.add_argument("--event", choices=("PreToolUse", "PostToolUse", "Stop"), required=True)
    parser.add_argument("--plugin", action="store_true")
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
        if args.plugin:
            root = bind_plugin_target(cwd)
            if root is None:
                return 0                      # 하네스가 연결되지 않았거나 템플릿 체크아웃 — 비킨다
        else:
            root = checkout_root(cwd)
            if root != Path(__file__).resolve().parents[1]:
                return _delegate(root, args.agent, args.event, payload)
            sys.path.insert(0, str(root))  # Direct script launch starts with kernel/ on sys.path.
        if args.event == "PreToolUse":
            from kernel import pretool
            code, system_message = pretool.pretool_gate(root, payload, sid, args.agent, core_only=args.plugin)
            if code == 0 and args.agent == "codex":
                print(json.dumps({"systemMessage": system_message}, ensure_ascii=False) if system_message else "{}")
            return code
        paths = untracked_paths(root) if args.event == "Stop" else edited_paths(payload, cwd)
        refresh_projection(root)
        from kernel import isolation
        if isolation.in_worktree(root) or (paths and all(isolation.in_worktree(p) for p in paths)):
            code, system_message = wip_checks(root, paths, args.event, sid, args.agent)
        else:
            code = run_checks(root, paths, args.event, sid)
        if args.event == "Stop" and args.agent == "codex":
            verdict, stop_message = workspace_verdict(workspace_findings(root, sid))
            code = max(code, verdict)
            system_message = "\n".join(part for part in (system_message, stop_message) if part)
        if args.event == "PostToolUse":
            warned = board_overlaps(root, paths, sid)
            if warned:
                print("[WORKBOARD] 다른 과업이 잡은 곳이다 — 같은 범위면 그 과업 파일의 항목에 줄을 추가해"
                      " 그 세션에 맡기거나(합류), 그 과업 브랜치에서 worktree 를 따서 이어 작업한다(쌓기)."
                      " 겹치는 줄이 아니면 그대로 진행해도 된다 (경고이지 차단이 아니다):",
                      file=sys.stderr)
                for line in warned:
                    print(f"  {line}", file=sys.stderr)
                code = max(code, 1)
        if code and system_message:
            print(system_message, file=sys.stderr)  # A blocked turn reads stderr, not JSON.
    except Exception as exc:
        # A broken executable profile is an infrastructure error, not a violation.
        print(f"검사 불능: {exc}", file=sys.stderr)
        return 2 if args.event == "Stop" else 1
    if code == 0 and args.agent == "codex":
        print(json.dumps({"systemMessage": system_message}, ensure_ascii=False) if system_message else "{}")
    return code


if __name__ == "__main__":
    sys.exit(main())
