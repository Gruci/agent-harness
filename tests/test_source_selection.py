"""The on-save check, the full run and the completion check must select the same project source files."""

from __future__ import annotations

import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from harness_test_support import TemporaryRootTestCase
from kernel import context, hook, profile, runner


class SourceSelectionTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for module in (context, runner):
            stack.enter_context(patch.object(module, "ROOT", self.root))
        stack.enter_context(patch.object(profile, "SOURCE_EXT", ("*.go",)))
        stack.enter_context(patch.object(profile, "UI_EXT", ("*.tsx", "*.ts")))
        stack.enter_context(patch.object(profile, "SCOPE", {"exclude_all": (), "exclude_scratch": ()}))
        stack.enter_context(patch.object(profile, "CHECK_PATHS", {"ui": "frontend/src"}))

    def test_go_save_and_untracked_full_have_same_source(self) -> None:
        source = self.root / "new.go"
        source.write_text("package main\n", encoding="utf-8")
        self.assertEqual(runner._single_file_lists(str(source))[0], [source])
        self.assertEqual(runner.source_files()[0], [source])
        self.assertEqual(hook.untracked_paths(self.root), [source])

    def test_ignored_file_is_not_collected(self) -> None:
        (self.root / ".gitignore").write_text("generated/\n", encoding="utf-8")
        (self.root / "generated").mkdir()
        (self.root / "generated" / "out.go").write_text("package generated\n", encoding="utf-8")
        self.assertEqual(runner.source_files()[0], [])

    def test_typescript_server_is_checked_without_ui_root(self) -> None:
        source = self.root / "server.ts"
        source.write_text("const n = 1;\n", encoding="utf-8")
        with patch.object(profile, "SOURCE_EXT", ("*.ts",)):
            self.assertEqual(runner._single_file_lists(str(source))[0], [source])

    def test_ui_file_is_not_also_server_source(self) -> None:
        source = self.root / "frontend" / "src" / "page.ts"
        source.parent.mkdir(parents=True)
        source.write_text("export const n = 1;\n", encoding="utf-8")
        with patch.object(profile, "SOURCE_EXT", ("*.ts",)):
            self.assertEqual(runner.source_files(), ([], [source]))

    def test_verify_rejects_missing_required_tool(self) -> None:
        sections = [("syntax", "syntax", [], ("TOOL", "parser missing"))]
        with patch.object(runner, "_build_sections", return_value=sections), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--verify"]), 2)


if __name__ == "__main__":
    unittest.main()
