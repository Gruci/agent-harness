"""Behavior checks for the shared hook protocol, using real temporary repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kernel import feature_map, graph_workflow

REPO = Path(__file__).resolve().parents[1]
PROFILE = "PROFILE_SCHEMA = 1\nARCH = 'headless'\nLANG = 'python'\nLINTERS = ()\nCHECK_PATHS = {}\n"


class SharedHookFixture(unittest.TestCase):
    """A real temporary checkout with an approved graph, a bare origin, and hook helpers.

    Test modules subclass this; it declares no tests itself. `tests/test_isolation_hooks.py`
    reuses it for the PreToolUse guard and the worktree notice path.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "한글 project"
        self.root.mkdir()
        shutil.copytree(REPO / "kernel", self.root / "kernel",
                        ignore=shutil.ignore_patterns("__pycache__", "engine"))
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        architecture = self.root / "docs" / "architecture"
        architecture.mkdir(parents=True)
        shutil.copy2(REPO / "docs/architecture/components.schema.json", architecture)
        (self.root / "harness_profile.py").write_text(PROFILE, encoding="utf-8")
        graph = {
            "schema": 1, "revision": 1,
            "categories": [{"id": "fixture", "name": "Hook fixture", "description": "Test source edits",
                            "roles": ["usecases"]}],
            "components": [{"id": "fixture", "name": "Hook fixture", "category": "fixture",
                            "responsibility": "Exercise hook decisions", "excludes": ["Harness implementation"],
                            "root": ".", "roles": {"usecases": ["*.py", "**/*.py"]},
                            "public": [], "state": "planned", "external": []}],
            "edges": [], "technology": {"sources": ["**/*.py"], "syntax": "python",
                "exclude": [{"path": "kernel", "reason": "Copied checker implementation"},
                            {"path": "harness_profile.py", "reason": "Checker configuration"}]},
            "role_dependencies": {"usecases": ["usecases"]},
        }
        proposal = graph_workflow.propose(self.root, graph, "Classify all test application edits", "shared-hooks")
        graph_workflow.decide(self.root, proposal["id"], "approve", "Approve this fixture classification",
                              "fixture://shared-hook-tests/user-response")
        graph_workflow.apply(self.root, proposal["id"])
        self.graph = graph
        feature_map.generate(self.root)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)
        # The shared Stop gate now blocks a checkout without origin; a bare repo stands in.
        origin = Path(self.temp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=self.root, check=True,
                       capture_output=True)

    def shell_command(self, event: str) -> dict:
        return json.loads((REPO / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"][event][0]["hooks"][0]

    def bash_payload(self, command: str) -> dict[str, object]:
        return {"cwd": str(self.root), "session_id": "abcdef1234", "tool_name": "Bash",
                "tool_input": {"command": command}}

    def hook(self, event: str, payload: object, agent: str = "codex") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "kernel.hook",
             "--agent", agent, "--event", event], cwd=self.root,
            input=json.dumps(payload), capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )

    def write_code(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        feature_map.generate(self.root)
        return path

    def run_configured(self, event: str, cwd: Path, payload: object) -> subprocess.CompletedProcess:
        entry = self.shell_command(event)
        if sys.platform == "win32":
            command = ["powershell", "-NoProfile", "-Command", entry["commandWindows"]]
        else:
            command = ["sh", "-c", entry["command"]]
        return subprocess.run(command, cwd=cwd, input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)

    def linked_worktree(self) -> Path:
        subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
                        "commit", "-qm", "fixture"], cwd=self.root, check=True)
        work = Path(self.temp.name) / "external worktree"
        subprocess.run(["git", "worktree", "add", "--detach", str(work)],
                       cwd=self.root, check=True, capture_output=True)
        return work

    def register_task(self, sid8: str = "abcdef12") -> None:
        board = self.root / "workboard"
        board.mkdir(exist_ok=True)
        (board / "kernel-fixture.md").write_text(
            f"- 범위: kernel-fixture\n- 과업: feat/fixture #sid:{sid8}\n- 손대는 곳:\n  - kernel/*\n- 상태: 진행\n",
            encoding="utf-8")


class SharedHookTests(SharedHookFixture):
    def test_patch_checks_every_file_including_untracked(self) -> None:
        self.write_code("good.py", "VALUE = 1\n")
        bad = self.write_code("한글 bad.py", "def outer():\n    def hidden():\n        return 1\n    return hidden()\n")
        result = self.hook("PostToolUse", {
            "cwd": str(self.root), "session_id": "test1234",
            "tool_name": "apply_patch", "tool_input": {"command":
                "*** Begin Patch\n*** Add File: good.py\n+VALUE = 1\n"
                "*** Add File: 한글 bad.py\n+def outer():\n*** End Patch"},
        })
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(bad.name, result.stderr)

    def test_claude_path_has_same_verdict(self) -> None:
        bad = self.write_code("bad.py", "def outer():\n    def hidden():\n        return 1\n")
        result = self.hook("PostToolUse", {
            "cwd": str(self.root), "tool_input": {"file_path": str(bad)}}, "claude")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_move_checks_destination_from_subdirectory(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        self.write_code("nested/new.py", "def outer():\n    def hidden():\n        return 1\n")
        result = self.hook("PostToolUse", {
            "cwd": str(nested), "tool_name": "apply_patch", "tool_input": {"command":
                "*** Begin Patch\n*** Update File: old.py\n*** Move to: new.py\n@@\n*** End Patch"},
        })
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("new.py", result.stderr)

    def test_deleted_file_is_not_a_failure(self) -> None:
        result = self.hook("PostToolUse", {
            "cwd": str(self.root), "tool_name": "apply_patch", "tool_input": {"command":
                "*** Begin Patch\n*** Delete File: gone.py\n*** End Patch"},
        })
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_success_is_json(self) -> None:
        result = self.hook("Stop", {"cwd": str(self.root)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_codex_stop_blocks_without_origin(self) -> None:
        subprocess.run(["git", "remote", "remove", "origin"], cwd=self.root, check=True, capture_output=True)
        result = self.hook("Stop", {"cwd": str(self.root), "session_id": "abcdef1234"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("[GIT REMOTE]", result.stderr)

    def test_codex_stop_blocks_stale_task_artifact(self) -> None:
        tasks = self.root / "docs" / "tasks"
        tasks.mkdir(parents=True)
        plan = tasks / "plan_x.md"
        plan.write_text("# plan\n", encoding="utf-8")
        os.utime(plan, (0, 0))
        result = self.hook("Stop", {"cwd": str(self.root), "session_id": "abcdef1234"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("[TASK RESIDUE]", result.stderr)
        self.assertIn("plan_x.md", result.stderr)

    def test_codex_stop_mockup_residue_respects_wip_prefix(self) -> None:
        mockup = self.root / "docs" / "tasks" / "mockup"
        mockup.mkdir(parents=True)
        (mockup / "a.html").write_text("<p>a</p>", encoding="utf-8")
        blocked = self.hook("Stop", {"cwd": str(self.root), "session_id": "abcdef1234"})
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("[MOCKUP RESIDUE]", blocked.stderr)
        (mockup / "a.html").rename(mockup / "wip_a.html")
        passed = self.hook("Stop", {"cwd": str(self.root), "session_id": "abcdef1234"})
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(json.loads(passed.stdout), {})

    def test_codex_pretooluse_blocks_worktree_outside_contract(self) -> None:
        cases = (
            ("git worktree add .claude/worktrees/x--abcdef12", 2, "worktrees/x--abcdef12"),
            ("git worktree add worktrees/x", 2, "x--abcdef12"),
            ("git worktree add worktrees/x--abcdef12 -b feat/x", 0, ""),
            ("ls worktrees", 0, ""),
        )
        for command, code, expected in cases:
            with self.subTest(command=command):
                result = self.hook("PreToolUse", self.bash_payload(command))
                self.assertEqual(result.returncode, code, result.stderr)
                if code == 0:
                    self.assertEqual(json.loads(result.stdout), {})
                else:
                    self.assertIn("[WORKTREE NAME]", result.stderr)
                    self.assertIn(expected, result.stderr)

    def test_codex_pretooluse_without_session_warns(self) -> None:
        payload = self.bash_payload("git worktree add worktrees/x")
        payload.pop("session_id")
        result = self.hook("PreToolUse", payload)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("세션 식별자", result.stderr)

    def test_approved_component_edit_refreshes_map_without_new_question(self) -> None:
        source = self.root / "approved-change.py"
        source.write_text("VALUE = 2\n", encoding="utf-8")
        self.assertTrue(feature_map.check(self.root))
        result = self.hook("PostToolUse", {"cwd": str(self.root), "tool_input": {"file_path": str(source)}})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("[DECISION]", result.stderr)
        self.assertEqual([], feature_map.check(self.root))

    def test_stop_detects_tracked_violation(self) -> None:
        self.write_code("bad.py", "def outer():\n    def hidden():\n        return 1\n")
        subprocess.run(["git", "add", "bad.py"], cwd=self.root, check=True)
        result = self.hook("Stop", {"cwd": str(self.root)})
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_stop_detects_untracked_violation(self) -> None:
        self.write_code("untracked.py", "def outer():\n    def hidden():\n        return 1\n")
        result = self.hook("Stop", {"cwd": str(self.root)})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("untracked.py", result.stderr)

    def test_new_component_notifies_once_and_waits_without_claiming_verified(self) -> None:
        self.graph["revision"] += 1
        self.graph["components"][0]["root"] = "approved"
        proposal = graph_workflow.propose(self.root, self.graph, "Only approved contains classified code", "new-component")
        graph_workflow.decide(self.root, proposal["id"], "approve", "Approve the narrower fixture boundary",
                              "fixture://new-component/user-response")
        graph_workflow.apply(self.root, proposal["id"])
        self.write_code("new-component.py", "VALUE = 1\n")
        first = self.hook("Stop", {"cwd": str(self.root), "session_id": "decision-fixture"})
        second = self.hook("Stop", {"cwd": str(self.root), "session_id": "decision-fixture"})
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertIn("[DECISION]", first.stderr)
        self.assertIn("new-component.py", first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotIn("[DECISION]", second.stderr)
        verification = subprocess.run([sys.executable, "-X", "utf8", "-m", "kernel.runner", "--verify"],
                                      cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(2, verification.returncode, verification.stdout + verification.stderr)
        self.assertIn("needs_decision", verification.stdout)
        self.assertIn("[TOOL]", verification.stdout)

    def test_code_violation_alongside_unclassified_source_still_blocks_stop(self) -> None:
        (self.root / "docs/architecture/components.json").unlink()
        (self.root / "bad.py").write_text("def outer():\n    def hidden():\n        return 1\n", encoding="utf-8")
        result = self.hook("Stop", {"cwd": str(self.root), "session_id": "bad-decision-fixture"})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("[DECISION]", result.stderr)
        self.assertIn("closures", result.stderr)

    def test_external_worktree_uses_its_profile_and_only_notifies(self) -> None:
        work = self.linked_worktree()
        (work / "harness_profile.py").write_text(
            PROFILE + "LEGACY_PATHS = (('/retired/', '.py'),)\n", encoding="utf-8")
        retired = work / "retired"
        retired.mkdir()
        (retired / "old.py").write_text("VALUE = 1\n", encoding="utf-8")
        payload = {"cwd": str(work), "tool_input": {"file_path": "retired/old.py"}}
        result = self.hook("PostToolUse", payload, "claude")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("[WIP]", result.stderr)
        self.assertIn("레거시", result.stderr)
        self.assertTrue((work / "harness_trace.jsonl").exists())
        self.assertFalse((self.root / "harness_trace.jsonl").exists())
        codex = self.hook("PostToolUse", payload)
        self.assertEqual(codex.returncode, 0, codex.stderr)
        message = json.loads(codex.stdout)["systemMessage"]
        self.assertTrue(message.startswith("[WIP]") and "레거시" in message, message)

    def test_outside_checkout_is_rejected(self) -> None:
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("VALUE = 1\n", encoding="utf-8")
        result = self.hook("PostToolUse", {
            "cwd": str(self.root), "tool_input": {"file_path": str(outside)}})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("검사 불능", result.stderr)

    def test_legacy_rule_blocks_existing_path(self) -> None:
        self.write_code("harness_profile.py", PROFILE + "LEGACY_PATHS = (('/retired/', '.py'),)\n")
        self.write_code("retired/old.py", "VALUE = 1\n")
        result = self.hook("PostToolUse", {
            "cwd": str(self.root), "tool_input": {"file_path": "retired/old.py"}})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("레거시", result.stderr)
        records = (self.root / "harness_trace.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(records[-1])["kind"], "gate")

    def test_missing_external_hook_blocks_stop(self) -> None:
        other = Path(self.temp.name) / "other"
        (other / "kernel").mkdir(parents=True)
        (other / "kernel" / "__init__.py").write_text("", encoding="utf-8")
        (other / "kernel" / "runner.py").write_text("", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        result = self.hook("Stop", {"cwd": str(other)})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("검사 불능", result.stderr)

    def test_profile_crash_warns_on_write_and_blocks_stop(self) -> None:
        self.write_code("harness_profile.py", "raise RuntimeError('broken profile')\n")
        self.write_code("good.py", "VALUE = 1\n")
        payload = {"cwd": str(self.root), "tool_input": {"file_path": "good.py"}}
        write = self.hook("PostToolUse", payload)
        stop = self.hook("Stop", payload)
        self.assertEqual(write.returncode, 1, write.stderr)
        self.assertEqual(stop.returncode, 2, stop.stderr)
        self.assertIn("검사 불능", write.stderr)
        self.assertNotIn("Traceback", write.stderr)

    def test_untracked_harness_sources_do_not_create_file_jobs(self) -> None:
        subprocess.run(["git", "rm", "-r", "--cached", "kernel"],
                       cwd=self.root, check=True, capture_output=True)
        code = self.write_code("new.py", "VALUE = 1\n")
        doc = self.write_code("kernel/guide.md", "# Guide\n")
        sys.path.insert(0, str(REPO))
        from kernel.hook import untracked_paths
        self.assertEqual(set(untracked_paths(self.root)), {code, doc})

    def test_broken_payload_warns_on_write_but_stop_still_checks(self) -> None:
        write = self.hook("PostToolUse", [])
        self.assertEqual(write.returncode, 1, write.stderr)
        stop = self.hook("Stop", [])
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertEqual(json.loads(stop.stdout), {})

    def test_runner_crash_is_not_a_code_violation(self) -> None:
        (self.root / "kernel" / "runner.py").write_text("raise RuntimeError('broken runner')\n", encoding="utf-8")
        self.write_code("good.py", "VALUE = 1\n")
        payload = {"cwd": str(self.root), "tool_input": {"file_path": "good.py"}}
        write = self.hook("PostToolUse", payload)
        stop = self.hook("Stop", payload)
        self.assertEqual(write.returncode, 1, write.stderr)
        self.assertEqual(stop.returncode, 2, stop.stderr)
        self.assertIn("검사 불능", stop.stderr)

    def test_configured_shell_commands_from_nested_cwd(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        bad = self.write_code("nested/bad.py", "VALUE = 1\n")
        payload = {"cwd": str(nested), "tool_input": {"file_path": str(bad)}}
        for broken in (False, True):
            if broken:
                bad.write_text("def outer():\n    def hidden():\n        return 1\n", encoding="utf-8")
            for event in ("PostToolUse", "Stop"):
                with self.subTest(event=event, broken=broken):
                    result = self.run_configured(event, nested, payload)
                    self.assertEqual(result.returncode, 2 if broken else 0, result.stderr)
                    if not broken:
                        self.assertEqual(json.loads(result.stdout), {})

    def test_configured_pretooluse_command_from_nested_cwd(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        for command, code in (("git worktree add .claude/worktrees/x--abcdef12", 2),
                              ("git worktree add worktrees/x--abcdef12", 0)):
            with self.subTest(command=command):
                payload = self.bash_payload(command)
                payload["cwd"] = str(nested)
                result = self.run_configured("PreToolUse", nested, payload)
                self.assertEqual(result.returncode, code, result.stderr)
                if code == 0:
                    self.assertEqual(json.loads(result.stdout), {})
                else:
                    self.assertIn("worktrees/x--abcdef12", result.stderr)


if __name__ == "__main__":
    unittest.main()
