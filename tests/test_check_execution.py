"""Regression coverage for failed checks and invalid capability packs."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kernel import arch, framework, lang, linters


class CheckExecutionTests(unittest.TestCase):
    def test_eslint_nonzero_empty_json_is_not_clean(self):
        done = subprocess.CompletedProcess(["eslint"], 2, "[]", "invalid configuration")
        with patch("kernel.linters.ui_eslint_bin", return_value=Path("eslint")), \
                patch("kernel.linters.subprocess.run", return_value=done):
            found = linters.eslint_report(Path.cwd(), [], {}, "", framework.load_one("react"))
        self.assertTrue(all(found[slug] for slug in linters.UI_SLUGS))

    def test_nonzero_without_diagnostics_is_unverified(self):
        found, reason = linters.run_one({"cmd": [sys.executable, "-c", "raise SystemExit(2)"]})
        self.assertEqual(found, [])
        self.assertIn("2", reason)

    def test_timeout_is_unverified(self):
        with patch("kernel.linters.subprocess.run", side_effect=subprocess.TimeoutExpired("tool", 90)):
            found, reason = linters.run_one({"cmd": [sys.executable]})
        self.assertEqual(found, [])
        self.assertTrue(reason)

    def test_unknown_parser_is_unverified(self):
        found, reason = linters.run_one({"cmd": [sys.executable, "-c", "pass"], "parse": "typo"})
        self.assertEqual(found, [])
        self.assertIn("typo", reason)

    def test_windows_gcc_diagnostic(self):
        self.assertEqual(linters._parse_gcc(r"C:\work\main.go:12:4: bad call", "vet"),
                         ["C:/work/main.go:12: bad call (vet)"])

    def test_typescript_diagnostic(self):
        self.assertEqual(linters._parse_gcc("src/main.ts(8,3): error TS2322: wrong type", "tsc"),
                         ["src/main.ts:8: error TS2322: wrong type (tsc)"])

    def test_nonzero_with_diagnostics_retains_violations(self):
        found, reason = linters.run_one({"slug": "compiler", "cmd": [sys.executable, "-c",
            "print('main.py:4: bad type'); raise SystemExit(1)"]})
        self.assertEqual(found, ["main.py:4: bad type (compiler)"])
        self.assertEqual(reason, "")

    def test_success_without_diagnostics_is_clean(self):
        self.assertEqual(linters.run_one({"cmd": [sys.executable, "-c", "pass"]}), ([], ""))

    def test_unknown_pack_is_rejected(self):
        for loader in (lang, arch):
            with self.subTest(loader=loader.__name__), self.assertRaises(ValueError):
                loader.load("does_not_exist")

    def test_pack_name_cannot_traverse(self):
        for loader in (lang, arch):
            for name in ("../python", "..\\python", "C:/python", "", 123):
                with self.subTest(loader=loader.__name__, name=name), self.assertRaises(ValueError):
                    loader.load(name)

    def test_broken_project_pack_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for loader in (lang, arch):
                folder = root / loader.PROJECT_DIR
                folder.mkdir(parents=True)
                (folder / "broken.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
                with self.subTest(loader=loader.__name__), patch.object(loader, "ROOT", root):
                    with self.assertRaises(ValueError):
                        loader.load("broken")

    def test_invalid_pack_declaration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for loader in (lang, arch):
                folder = root / loader.PROJECT_DIR
                folder.mkdir(parents=True)
                (folder / "broken.py").write_text("NOT_APPLICABLE = ['invalid']\n", encoding="utf-8")
                with self.subTest(loader=loader.__name__), patch.object(loader, "ROOT", root):
                    with self.assertRaises(ValueError):
                        loader.load("broken")

    def test_shipped_packs_load(self):
        for loader in (lang, arch):
            for name in loader.available():
                with self.subTest(loader=loader.__name__, name=name):
                    self.assertIsInstance(loader.load(name), dict)


if __name__ == "__main__":
    unittest.main()
