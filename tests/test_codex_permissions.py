"""Global autonomy installation in temporary homes, including preservation and refusal paths."""

from __future__ import annotations

import os
import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_test_support import TemporaryRootTestCase

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


class CodexPermissionsTests(TemporaryRootTestCase):
    def test_empty_home_install_is_idempotent(self) -> None:
        from kernel.codex_permissions import configure_codex

        self.assertEqual(configure_codex(self.root), 0)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(configure_codex(self.root), 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(configure_codex(self.root, check=True), 0)

    def test_provider_config_and_existing_instructions_are_preserved(self) -> None:
        from kernel.codex_permissions import configure_codex, parse_toml

        original = '# private config\nmodel = "test"\napproval_policy = "on-request"\n[model_providers.local]\nbase_url = "http://localhost"\n'
        (self.root / "config.toml").write_text(original, encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# Existing instructions\nKeep these.\n", encoding="utf-8")
        self.assertEqual(configure_codex(self.root), 0)
        updated = (self.root / "config.toml").read_text(encoding="utf-8")
        self.assertIn('# private config\nmodel = "test"', updated)
        self.assertEqual(parse_toml(updated)["model_providers"], parse_toml(original)["model_providers"])
        self.assertTrue((self.root / "AGENTS.md").read_text().startswith("# Existing instructions\nKeep these.\n"))
        self.assertEqual((self.root / "config.toml.pre-harness-autonomy.bak").read_text(), original)
        self.assertEqual(configure_codex(self.root), 0)
        self.assertEqual((self.root / "config.toml.pre-harness-autonomy.bak").read_text(), original)

    def test_override_instructions_take_precedence(self) -> None:
        from kernel.codex_permissions import configure_codex

        (self.root / "AGENTS.override.md").write_text("Override policy.\n")
        (self.root / "AGENTS.md").write_text("Fallback.\n")
        self.assertEqual(configure_codex(self.root), 0)
        self.assertEqual((self.root / "AGENTS.md").read_text(), "Fallback.\n")
        self.assertIn("harness-autonomy", (self.root / "AGENTS.override.md").read_text())

    def test_named_permissions_scheme_preserves_definitions(self) -> None:
        from kernel.codex_permissions import configure_codex, parse_toml

        original = 'default_permissions = "custom"\nsandbox_mode = "workspace-write"\n[sandbox_workspace_write]\nnetwork_access = false\n[permissions.custom]\nvalue = "preserve"\n'
        (self.root / "config.toml").write_text(original)
        self.assertEqual(configure_codex(self.root), 0)
        result = parse_toml((self.root / "config.toml").read_text())
        self.assertEqual(result["default_permissions"], ":danger-full-access")
        self.assertNotIn("sandbox_mode", result)
        self.assertNotIn("sandbox_workspace_write", result)
        self.assertEqual(result["permissions"], parse_toml(original)["permissions"])

    def test_invalid_toml_is_not_modified(self) -> None:
        from kernel.codex_permissions import configure_codex

        original = b'[bad config\nsecret = "do-not-print"\n'
        (self.root / "config.toml").write_bytes(original)
        self.assertEqual(configure_codex(self.root), 2)
        self.assertEqual((self.root / "config.toml").read_bytes(), original)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_broken_instruction_markers_leave_config_unchanged(self) -> None:
        from kernel.codex_permissions import configure_codex

        (self.root / "config.toml").write_text('model = "keep"\n')
        (self.root / "AGENTS.md").write_text("<!-- harness-autonomy:start -->\n")
        self.assertEqual(configure_codex(self.root), 2)
        self.assertEqual((self.root / "config.toml").read_text(), 'model = "keep"\n')

    def test_read_only_check_does_not_create_home(self) -> None:
        from kernel.codex_permissions import configure_codex

        target = self.root / "missing"
        self.assertEqual(configure_codex(target, check=True), 1)
        self.assertFalse(target.exists())

    def test_codex_home_environment_wins(self) -> None:
        from kernel.codex_permissions import codex_home

        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            self.assertEqual(codex_home(), self.root)

    def test_cli_installs_and_checks_only_selected_codex_home(self) -> None:
        environment = dict(os.environ, CODEX_HOME=str(self.root))
        command = [sys.executable, "-X", "utf8", str(REPO / "setup_global_permissions.py"), "--agent", "codex"]
        for flags in ([], ["--check"]):
            result = subprocess.run(command + flags, cwd=REPO, env=environment,
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("approval_policy", (self.root / "config.toml").read_text())

    def test_default_claude_and_both_keep_custom_settings(self) -> None:
        import setup_global_permissions

        claude = self.root / ".claude/settings.json"
        claude.parent.mkdir()
        original = '{"custom": "keep", "permissions": {"allow": ["MyTool(*)"]}}'
        claude.write_text(original)
        with patch.object(Path, "home", return_value=self.root), \
                patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex"),
                                        "CLAUDE_CONFIG_DIR": str(claude.parent)}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup_global_permissions.main([]), 0)
            self.assertFalse((self.root / "codex").exists())
            self.assertEqual(setup_global_permissions.main(["--agent", "both"]), 0)
            self.assertEqual(setup_global_permissions.main(["--agent", "both", "--check"]), 0)
        self.assertEqual(json.loads(claude.read_text())["custom"], "keep")
        self.assertIn("MyTool(*)", json.loads(claude.read_text())["permissions"]["allow"])
        self.assertEqual(claude.with_name(claude.name + ".pre-harness-autonomy.bak").read_text(), original)

    def test_ambiguous_multiline_toml_is_refused_without_secret_output(self) -> None:
        from kernel.codex_permissions import configure_codex

        original = 'private_note = """\napproval_policy = "secret-do-not-print"\n"""\n'
        (self.root / "config.toml").write_text(original)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(configure_codex(self.root), 2)
        self.assertNotIn("secret-do-not-print", output.getvalue())
        self.assertEqual((self.root / "config.toml").read_text(), original)

    def test_quoted_keys_and_crlf_preserve_provider_section(self) -> None:
        from kernel.codex_permissions import update_config, parse_toml

        original = '"approval_policy" = "on-request"\r\n\'sandbox_mode\' = "read-only"\r\n[model_providers.local]\r\nname = "custom"\r\n'
        updated = update_config(original)
        self.assertEqual(parse_toml(updated)["approval_policy"], "never")
        self.assertIn('[model_providers.local]\r\nname = "custom"\r\n', updated)
        self.assertNotIn("\n", updated.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()
