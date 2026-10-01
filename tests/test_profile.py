"""Profile shape: current schema only, no default app language, unknown keys rejected."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kernel import context
import harness_install


class ProfileTests(unittest.TestCase):
    def load_profile(self, source):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        if source is not None:
            (root / "harness_profile.py").write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("migration_profile", context.ROOT / "kernel/profile.py")
        module = importlib.util.module_from_spec(spec)
        with patch.object(context, "ROOT", root):
            spec.loader.exec_module(module)
        return module

    def test_only_current_schema_is_accepted(self):
        for source in (None, "", "PROFILE_SCHEMA = 0", "PROFILE_SCHEMA = 2", "PROFILE_SCHEMA = True"):
            with self.subTest(source=source):
                self.assertTrue(self.load_profile(source).PROFILE_ERRORS)

    def test_unselected_stack_has_no_python_defaults(self):
        profile = self.load_profile("PROFILE_SCHEMA = 1\nLANG = None\n")
        self.assertEqual(profile.PROFILE_ERRORS, [])
        self.assertEqual(profile.SOURCE_EXT, ())
        self.assertIsNone(profile.SYNTAX)
        self.assertEqual(profile.pattern("env_read"), "")

    def test_unknown_check_path_key_is_rejected(self):
        profile = self.load_profile("PROFILE_SCHEMA = 1\nCHECK_PATHS = {'read': 'db/reads'}\n")
        self.assertTrue(profile.PROFILE_ERRORS)

    def test_technical_paths_and_graph_are_exported(self):
        profile = self.load_profile("PROFILE_SCHEMA = 1\nCHECK_PATHS = {'ui': 'client/src'}\n")
        self.assertEqual(profile.PROFILE_ERRORS, [])
        self.assertEqual(profile.layer("ui"), "client/src/")
        self.assertEqual(profile.layer_raw("ui"), "client/src")
        self.assertEqual(profile.COMPONENT_GRAPH, "docs/architecture/components.json")
        self.assertFalse(hasattr(profile, "LAYERS"))

    def test_reset_preserves_architecture_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "docs/architecture"
            target.mkdir(parents=True)
            for name in ("components.schema.json", "components.json"):
                (target / name).write_text("{}", encoding="utf-8")
            with patch.object(harness_install, "ROOT", root):
                harness_install.reset_shipped_state()
            self.assertEqual(len(list(target.glob("*.json"))), 2)

    def test_only_unselected_template_is_shipped(self):
        self.assertEqual(harness_install.presets(), ["_template"])
        template = (context.ROOT / "profiles/_template.py").read_text(encoding="utf-8")
        profile = self.load_profile(template)
        self.assertEqual(profile.PROFILE_ERRORS, [])
        self.assertIsNone(profile.LANG)


if __name__ == "__main__":
    unittest.main()
