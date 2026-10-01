"""Read-only agent installation diagnostics against temporary project trees."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_test_support import TemporaryRootTestCase

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


class HarnessSetupTests(TemporaryRootTestCase):
    def write(self, rel: str, content: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def complete_install(self) -> None:
        for rel in ("AGENTS.md", "CLAUDE.md", "kernel/hook.py", "kernel/runner.py",
                    "dev/workflows/README.md", "kernel/component_graph.py", "kernel/graph_workflow.py",
                    "kernel/graph_checks.py", "kernel/graph_notifications.py", "kernel/port_contracts.py",
                    "docs/architecture/components.schema.json", "dev/COMPONENTS.md",
                    "dev/workflows/harness-assembly.md"):
            self.write(rel)
        self.write(".agents/skills/harness-assembly-cdx/SKILL.md",
                   "Read dev/workflows/harness-assembly.md")
        for name in ("feature-workflow", "full-feature", "code-audit",
                     "code-debt", "code-trim", "md-audit", "review-loop", "test"):
            self.write(f"dev/workflows/{name}.md")
            reference = f"Read `dev/workflows/{name}.md`."
            self.write(f".agents/skills/{name}-cdx/SKILL.md", reference)
            self.write(f".claude/skills/{name}/SKILL.md", reference)
        claude = {}
        codex = {}
        matchers = {"PostToolUse": "Edit|Write|MultiEdit", "Stop": "",
                    "PreToolUse": "Edit|Write|MultiEdit|NotebookEdit|EnterWorktree|Bash|PowerShell"}
        for event, filename in (("PostToolUse", "check_file_rules"), ("Stop", "check_coding_rules"),
                                ("PreToolUse", "check_pretool")):
            self.write(f".claude/hooks/{filename}.py", "from kernel.hook import main\n")
            claude[event] = [{"matcher": matchers[event],
                              "hooks": [{"type": "command", "command":
                                         f'python "$(git rev-parse --show-toplevel)/.claude/hooks/{filename}.py"'}]}]
            command = f'python "$(git rev-parse --show-toplevel)/kernel/hook.py" --agent codex --event {event}'
            codex_matcher = {"PostToolUse": "Edit|Write|MultiEdit|apply_patch", "Stop": "",
                             "PreToolUse": "Bash|apply_patch|Edit|Write"}[event]
            codex[event] = [{"matcher": codex_matcher, "hooks": [{"type": "command", "command": command,
                                                                  "commandWindows": command}]}]
        self.write(".claude/settings.json", json.dumps({"hooks": claude, "custom": "keep"}))
        self.write(".codex/hooks.json", json.dumps({"hooks": codex, "custom": "keep"}))

    def diagnose(self) -> tuple[int, str]:
        from kernel.harness_setup import check_agents

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_agents(self.root)
        return code, output.getvalue()

    def test_missing_install_fails_with_paths(self) -> None:
        self.assertTrue((REPO / "kernel/harness_setup.py").is_file(), "Shared diagnostics missing")
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn(".codex/hooks.json", output)
        self.assertIn(".claude/settings.json", output)

    def test_complete_install_is_read_only(self) -> None:
        self.complete_install()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        code, output = self.diagnose()
        self.assertEqual(code, 0, output)
        self.assertIn("runtime", output.lower())
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_event_fails(self) -> None:
        self.complete_install()
        self.write(".codex/hooks.json", '{"hooks": {"PostToolUse": []}}')
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("Stop", output)

    def test_codex_pretooluse_bash_wiring_required(self) -> None:
        self.complete_install()
        path = self.root / ".codex/hooks.json"
        config = json.loads(path.read_text())
        del config["hooks"]["PreToolUse"]
        self.write(".codex/hooks.json", json.dumps(config))
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("PreToolUse Bash", output)
        self.assertNotIn(".claude/settings.json: PreToolUse", output)

    def test_claude_pretooluse_wiring_required(self) -> None:
        self.complete_install()
        path = self.root / ".claude/settings.json"
        config = json.loads(path.read_text())
        del config["hooks"]["PreToolUse"]
        self.write(".claude/settings.json", json.dumps(config))
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn(".claude/settings.json: PreToolUse Edit", output)
        self.assertNotIn(".codex/hooks.json: PreToolUse", output)

    def test_codex_pretooluse_edit_wiring_required(self) -> None:
        self.complete_install()
        path = self.root / ".codex/hooks.json"
        self.write(".codex/hooks.json", path.read_text().replace("Bash|apply_patch|Edit|Write", "Bash"))
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn(".codex/hooks.json: PreToolUse apply_patch", output)
        self.assertIn(".codex/hooks.json: PreToolUse Edit", output)
        self.assertNotIn(".codex/hooks.json: PreToolUse Bash", output)

    def test_missing_graph_contract_or_processor_fails(self) -> None:
        self.complete_install()
        for rel in ("docs/architecture/components.schema.json", "kernel/graph_workflow.py"):
            with self.subTest(rel=rel):
                path = self.root / rel
                content = path.read_bytes()
                path.unlink()
                code, output = self.diagnose()
                path.write_bytes(content)
                self.assertNotEqual(code, 0)
                self.assertIn(rel, output)

    def test_codex_assembly_does_not_require_claude_counterpart(self) -> None:
        self.complete_install()
        self.assertEqual(self.diagnose()[0], 0)
        (self.root / ".agents/skills/harness-assembly-cdx/SKILL.md").unlink()
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("harness-assembly-cdx", output)

    def test_assembly_must_link_shared_workflow(self) -> None:
        self.complete_install()
        self.write(".agents/skills/harness-assembly-cdx/SKILL.md", "Unrelated text")
        self.assertNotEqual(self.diagnose()[0], 0)

    def test_irrelevant_matcher_does_not_count_as_wiring(self) -> None:
        self.complete_install()
        path = self.root / ".claude/settings.json"
        self.write(".claude/settings.json", path.read_text().replace("Edit|Write|MultiEdit", "Read"))
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("PostToolUse", output)

    def test_disabled_hooks_fail(self) -> None:
        self.complete_install()
        path = self.root / ".claude/settings.json"
        config = json.loads(path.read_text())
        config["disableAllHooks"] = True
        self.write(".claude/settings.json", json.dumps(config))
        self.assertNotEqual(self.diagnose()[0], 0)

    def test_broken_shared_reference_fails(self) -> None:
        self.complete_install()
        self.write(".agents/skills/test-cdx/SKILL.md", "Read `dev/workflows/missing.md`.")
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("missing.md", output)

    def test_malformed_config_is_reported_without_traceback(self) -> None:
        self.complete_install()
        self.write(".codex/hooks.json", "{")
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn(".codex/hooks.json", output)

    def test_codex_windows_command_is_required(self) -> None:
        self.complete_install()
        path = self.root / ".codex/hooks.json"
        self.write(".codex/hooks.json", path.read_text().replace("commandWindows", "unused"))
        code, output = self.diagnose()
        self.assertNotEqual(code, 0)
        self.assertIn("commandWindows", output)

    def test_upgrade_preserves_custom_files_and_reports_missing_wiring(self) -> None:
        import harness_install

        self.complete_install()
        self.write(".claude/hooks/custom.py", "# project custom hook\n")
        self.write("kernel/custom.py", "# project custom module\n")
        self.write(".codex/hooks.json", '{"custom": "preserve missing wiring"}')
        self.write("profiles/custom.py", "# project preset\n")
        preserved = {rel: (self.root / rel).read_bytes() for rel in
                     (".claude/hooks/custom.py", "kernel/custom.py", ".codex/hooks.json",
                      ".claude/settings.json", "AGENTS.md", "profiles/custom.py")}
        with tempfile.TemporaryDirectory() as upstream_tmp:
            upstream = Path(upstream_tmp)
            for rel, content in {
                "kernel/__init__.py": 'KERNEL_VERSION = "99.0"\n',
                "kernel/harness_setup.py": (REPO / "kernel/harness_setup.py").read_text(encoding="utf-8"),
                ".claude/hooks/new.py": "# upstream hook\n",
                "profiles/_template.py": "# upstream preset\n",
            }.items():
                target = upstream / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            for directory in (self.root, upstream):
                for args in (("init", "-q", "-b", "main"), ("add", "."), ("commit", "-qm", "fixture")):
                    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                                   cwd=directory, capture_output=True, check=True)
            output = io.StringIO()
            with patch.object(harness_install, "ROOT", self.root), \
                    patch.object(harness_install, "UPSTREAM", str(upstream)), \
                    patch.object(harness_install, "UPSTREAM_BRANCH", "main"), \
                    contextlib.redirect_stdout(output):
                result = harness_install.upgrade()
        self.assertEqual(result, 1, output.getvalue())
        self.assertTrue((self.root / ".claude/hooks/new.py").is_file())
        for rel, content in preserved.items():
            self.assertEqual((self.root / rel).read_bytes(), content, rel)

    def test_cli_flag_dispatches_diagnostics(self) -> None:
        result = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "harness_install.py"),
                                 "--check-agents"], cwd=REPO, capture_output=True, text=True,
                                encoding="utf-8", timeout=30)
        self.assertIn("[AGENTS]", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
