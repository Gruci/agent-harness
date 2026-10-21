"""Run declared product tests with fresh JUnit evidence and a stable Git checkout.

This module deliberately does not import kernel.profile: callers must test the
target checkout's original declaration, including before profile schema upgrades.
"""
from __future__ import annotations

import json
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

OUTER_TIMEOUT_SEC = 3600
_DEFAULT_TIMEOUT_SEC = 600
_RESULT_PREFIX = "HARNESS_TESTS_RESULT="


@dataclass(frozen=True)
class TestsResult:
    code: int
    declared: bool
    tests: int
    failures: int
    errors: int
    skipped: int
    head: str
    lines: tuple[str, ...]


def declaration_errors(value: object) -> list[str]:
    """The single owner of the TESTS declaration schema, without executing code."""
    if not isinstance(value, (tuple, list)):
        return ["TESTS must be a tuple/list of test declarations"]
    errors, total = [], 0
    for index, entry in enumerate(value):
        label = f"TESTS[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be a dict")
            continue
        if set(entry) - {"slug", "cmd", "timeout"}:
            errors.append(f"{label} has unknown keys; use slug, cmd, timeout")
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug.strip() or any(c in slug for c in "\r\n\0"):
            errors.append(f"{label}.slug must be a nonempty single-line string")
        cmd = entry.get("cmd")
        if (not isinstance(cmd, (tuple, list)) or not cmd
                or any(not isinstance(arg, str) or "\0" in arg for arg in cmd)):
            errors.append(f"{label}.cmd must be a nonempty tuple/list of strings without NUL bytes")
        elif not cmd[0].strip():
            errors.append(f"{label}.cmd executable must be nonempty")
        elif sum(arg.count("{report}") for arg in cmd) != 1:
            errors.append(f"{label}.cmd must contain exactly one {{report}} placeholder")
        timeout = entry.get("timeout", _DEFAULT_TIMEOUT_SEC)
        if type(timeout) is not int or timeout <= 0:
            errors.append(f"{label}.timeout must be a positive integer")
        else:
            total += timeout
    if total > OUTER_TIMEOUT_SEC - 60:
        errors.append(f"TESTS timeout sum must not exceed {OUTER_TIMEOUT_SEC - 60}s")
    return errors


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("HARNESS_ROOT", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _terminate(process: subprocess.Popen) -> None:
    """Stop descendants too, before returning a timeout or deleting the checkout."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()
        process.communicate(timeout=5)


def _run(cmd: list[str], tree: Path, timeout: float) -> subprocess.CompletedProcess:
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with subprocess.Popen(cmd, cwd=tree, env=_environment(), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **group) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            _terminate(process)
            raise
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def _snapshot(tree: Path) -> tuple[str, bytes]:
    results = [subprocess.run(["git", *args], cwd=tree, capture_output=True, check=True, timeout=10)
               for args in (("rev-parse", "HEAD"),
                            ("status", "--porcelain=v1", "-z", "--untracked-files=all"))]
    return results[0].stdout.decode("ascii").strip(), results[1].stdout


def _junit(report: Path, started_ns: int) -> tuple[int, int, int, int]:
    if report.stat().st_mtime_ns < started_ns:
        raise ValueError("JUnit report is older than this execution")
    root = ET.parse(report).getroot()
    tag = lambda node: node.tag.rsplit("}", 1)[-1]
    if tag(root) not in {"testsuite", "testsuites"}:
        raise ValueError("JUnit root must be testsuite or testsuites")
    cases = [node for node in root.iter() if tag(node) == "testcase"]
    counts = [sum(any(tag(child) == kind for child in case) for case in cases)
              for kind in ("failure", "error", "skipped")]
    return len(cases), *counts


def _run_entry(tree: Path, entry: dict) -> tuple[int, tuple[int, int, int, int], str]:
    slug = entry["slug"]
    empty = (0, 0, 0, 0)
    with tempfile.TemporaryDirectory(prefix="harness-junit-") as directory:
        report = Path(directory) / "report.xml"
        cmd = [arg.replace("{report}", str(report)) for arg in entry["cmd"]]
        executable = shutil.which(cmd[0])
        if not executable:
            return 2, empty, f"[TOOL] {slug}: executable not found: {cmd[0]}"
        started_ns = time.time_ns()
        try:
            done = _run([executable, *cmd[1:]], tree, entry.get("timeout", _DEFAULT_TIMEOUT_SEC))
        except (OSError, subprocess.TimeoutExpired) as error:
            return 2, empty, f"[TOOL] {slug}: {error}"
        output = "\n".join(part for part in (done.stdout, done.stderr) if part)
        if output:
            print(output, flush=True)
        try:
            counts = _junit(report, started_ns)
        except (OSError, ET.ParseError, ValueError) as error:
            tail = " | ".join(output.strip().splitlines())[-1500:]
            return 1, empty, f"[FAIL] {slug}: missing or invalid JUnit report: {error} — {tail}"
        tests, failures, errors, skipped = counts
        if done.returncode or failures or errors or tests - skipped <= 0:
            tail = " | ".join(output.strip().splitlines())[-1500:]
            return 1, counts, (f"[FAIL] {slug}: exit {done.returncode}; {tests - skipped} executed, "
                               f"{failures} failures, {errors} errors, {skipped} skipped — {tail}")
        return 0, counts, f"[OK] {slug}: {tests - skipped} executed, {skipped} skipped"


def _execute(tree: Path) -> TestsResult:
    head, declared, code = "", True, 0
    counts, lines = [0, 0, 0, 0], []
    try:
        head, dirty = _snapshot(tree)
        path = tree / "harness_profile.py"
        entries = runpy.run_path(str(path)).get("TESTS", ()) if path.exists() else ()
        errors = declaration_errors(entries)
        if errors:
            return TestsResult(1, True, *counts, head, tuple(f"[FAIL] {error}" for error in errors))
        declared = bool(entries)
        if not declared:
            return TestsResult(0, False, *counts, head, ("[SKIP] Product tests — TESTS not declared",))
        if dirty:
            return TestsResult(1, True, *counts, head, ("[FAIL] Product tests require a clean checkout",))
        for entry in entries:
            entry_code, entry_counts, line = _run_entry(tree, entry)
            code = max(code, entry_code)
            counts = [old + new for old, new in zip(counts, entry_counts)]
            lines.append(line)
    except (OSError, subprocess.SubprocessError) as error:
        code = 2
        lines.append(f"[TOOL] Product tests could not run: {error}")
    except Exception as error:
        code = 1
        lines.append(f"[FAIL] Product test configuration failed: {error}")
    if head:
        try:
            after_head, after_dirty = _snapshot(tree)
            if after_head != head or after_dirty:
                code = code or 1
                lines.append("[FAIL] Product tests changed HEAD or tracked/untracked files")
        except (OSError, subprocess.SubprocessError) as error:
            code = 2
            lines.append(f"[TOOL] Cannot recheck the tested checkout: {error}")
    return TestsResult(code, declared, *counts, head, tuple(lines))


def _decode(done: subprocess.CompletedProcess) -> TestsResult:
    last = done.stdout.splitlines()[-1] if done.stdout else ""
    if not last.startswith(_RESULT_PREFIX):
        raise ValueError("CLI did not finish with a product-test result")
    data = json.loads(last[len(_RESULT_PREFIX):])
    if not isinstance(data, dict) or set(data) != set(TestsResult.__dataclass_fields__):
        raise ValueError("CLI result fields do not match TestsResult")
    if type(data["code"]) is not int or data["code"] not in (0, 1, 2) or done.returncode != data["code"]:
        raise ValueError("CLI exit code does not match the result")
    if (type(data["declared"]) is not bool or not isinstance(data["head"], str)
            or not isinstance(data["lines"], list) or not data["lines"]
            or any(not isinstance(line, str) or not line.startswith(("[OK]", "[FAIL]", "[TOOL]", "[SKIP]"))
                   for line in data["lines"])):
        raise ValueError("CLI result has invalid metadata")
    counts = [data[key] for key in ("tests", "failures", "errors", "skipped")]
    if any(type(count) is not int or count < 0 for count in counts) or any(count > counts[0] for count in counts[1:]):
        raise ValueError("CLI result has invalid test counts")
    if not data["code"]:
        if data["declared"] and (not data["head"] or counts[0] <= counts[3] or counts[1] or counts[2]):
            raise ValueError("CLI claimed success without passing executed tests")
        if not data["declared"] and any(counts):
            raise ValueError("CLI claimed tests without a declaration")
    return TestsResult(**{**data, "lines": tuple(data["lines"])})


def run_tests(tree: Path, timeout: int = OUTER_TIMEOUT_SEC) -> TestsResult:
    """Run a fresh CLI in the target; parent execution/decoding errors are code 2."""
    tree = Path(tree).resolve()
    # Installed plugins can use this module while the target has no kernel copy.
    target_module = tree / "kernel/tests_run.py"
    command = (["-m", "kernel.tests_run"] if target_module.is_file() else [str(Path(__file__).resolve())])
    try:
        done = _run([sys.executable, "-B", "-X", "utf8", *command], tree, timeout)
        return _decode(done)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as error:
        return TestsResult(2, False, 0, 0, 0, 0, "", (f"[TOOL] Product test subprocess unverified: {error}",))


if __name__ == "__main__":
    if os.name != "nt":
        # Let a parent timeout unwind _run and stop the currently executing test group.
        signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    tree = Path.cwd()
    sys.path.insert(0, str(tree))  # Direct plugin execution must resolve project-local profile imports too.
    result = _execute(tree)
    print("\n".join(result.lines))
    print(_RESULT_PREFIX + json.dumps(asdict(result), ensure_ascii=True), flush=True)
    raise SystemExit(result.code)
