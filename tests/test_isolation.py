"""tests/test_isolation.py — 격리 강제 판정(`kernel/isolation.py`)의 행동 테스트.

편집 전 가드와 나올 때 검사(push·PR·merge 직전 검사)는 Claude 와 Codex 가 같은 판정 함수를 쓴다.
오판은 어느 쪽으로 틀려도 비싸다. 너무 넓게 막으면 모든 편집이 막혀 세션이 멈추고,
너무 좁게 막으면 메인 체크아웃이 다시 작업 공간이 된다.

  편집 가드     메인 체크아웃 차단 · 1줄 예외 · 예외 경로 · 보드 미등록 · worktree 통과 · 세션 식별자 없음 경고
  줄 수 판정    Edit 문맥 속 1줄 교체 = 1 · Write 전 줄 · apply_patch 교체 = 1 · replace_all 배수
  합치는 명령   명령 조각의 맨 앞에 올 때만 명령으로 본다 — echo 인자나 커밋 메시지 안의 `git push` 는 명령이 아니다
  나올 때 검사  러너 exit 코드로 차단과 통과를 가른다. 러너가 실행되지 못해도 차단하고, 러너 없는 레포는 대상이 아니다

훅 수준 동작(PostToolUse·Stop 에서 차단을 [WIP] 알림으로 낮추는 것, push 차단)은 `tests/test_shared_harness.py` 가 잡는다.
실행: `python -X utf8 -m pytest tests/test_isolation.py -q`
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness_test_support import TASK_TEXT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SID = "abcd1234"                                   # TASK_TEXT 의 #sid
STRANGER = "ffffffff"                              # 보드에 없는 세션
PATCH_REPLACE = "*** Begin Patch\n*** Update File: kernel/x.py\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch"
PATCH_ADD = "*** Begin Patch\n*** Add File: kernel/y.py\n+A = 1\n+B = 2\n+C = 3\n*** End Patch"
FAILING_RUNNER = "import sys\nprint('[FAIL] 검사 (slug) — 1건')\nprint('   - kernel/x.py: 위반')\nsys.exit(1)\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=str(cwd), check=True, capture_output=True)


class IsolationTests(unittest.TestCase):
    """공유 체크아웃, 거기 연결된 worktree, workboard 를 실제 git 으로 한 세트 만든다."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.shared = (Path(temp.name) / "shared").resolve()
        (self.shared / "kernel").mkdir(parents=True)
        (self.shared / "kernel" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(self.shared, "init", "-q", "-b", "main")
        _git(self.shared, "add", "-A")
        _git(self.shared, "commit", "-qm", "init")
        self.work = self.shared / "worktrees" / "admin-report-viewers--abcd1234"
        _git(self.shared, "worktree", "add", "-q", str(self.work), "-b", "feat/report-viewers")
        self.board = self.shared / "workboard"
        self.board.mkdir()
        (self.board / "admin-report-viewers.md").write_text(TASK_TEXT, encoding="utf-8")
        self.outside = Path(temp.name) / "outside.py"
        self.outside.write_text("X = 1\n", encoding="utf-8")

    def guard(self, path: Path, sid8: str | None, lines: int) -> object | None:
        from kernel import isolation
        return isolation.edit_guard([path], sid8, lines, self.board)

    def test_main_checkout_edit_is_blocked_with_worktree_guidance(self) -> None:
        found = self.guard(self.shared / "kernel" / "x.py", SID, 3)
        self.assertIsNotNone(found)
        self.assertTrue(found.block, found)
        self.assertIn("[ISOLATION] Editing in the main checkout", found.message)
        self.assertIn("worktrees/admin-report-viewers--abcd1234", found.message)
        self.assertIn("EnterWorktree(path=", found.message)

    def test_one_line_edit_passes_everywhere(self) -> None:
        self.assertIsNone(self.guard(self.shared / "kernel" / "x.py", SID, 1))
        self.assertIsNone(self.guard(self.shared / "kernel" / "x.py", STRANGER, 1), "1줄 예외는 보드 등록도 면제다")
        self.assertIsNone(self.guard(self.shared / "kernel" / "x.py", None, 0))

    def test_exempt_paths_pass_without_board(self) -> None:
        for rel in ("workboard/new-task.md", "docs/tasks/plan_x.md", "docs/tasks/research_x.md"):
            with self.subTest(rel=rel):
                self.assertIsNone(self.guard(self.shared / rel, STRANGER, 12))
        self.assertIsNone(self.guard(self.work / "docs" / "tasks" / "plan_x.md", STRANGER, 12))

    def test_worktree_edit_without_my_board_file_is_blocked(self) -> None:
        found = self.guard(self.work / "kernel" / "x.py", STRANGER, 3)
        self.assertIsNotNone(found)
        self.assertTrue(found.block, found)
        self.assertIn("register first", found.message)
        self.assertIn(f"#sid:{STRANGER}", found.message)
        self.assertIn("- 상태: 진행", found.message)

    def test_worktree_edit_with_board_passes(self) -> None:
        self.assertIsNone(self.guard(self.work / "kernel" / "x.py", SID, 40))
        self.assertIsNone(self.guard(self.work / "kernel" / "new.py", SID, 40), "아직 없는 파일도 worktree 안 파일로 판정해야 한다")

    def test_locate_and_in_worktree(self) -> None:
        from kernel import isolation
        self.assertEqual(isolation.locate(self.shared / "kernel" / "x.py", self.shared), "main")
        self.assertEqual(isolation.locate(self.work / "kernel" / "x.py", self.shared), "worktree")
        self.assertEqual(isolation.locate(self.outside, self.shared), "outside")
        self.assertTrue(isolation.in_worktree(self.work, self.shared))
        self.assertFalse(isolation.in_worktree(self.shared, self.shared))
        self.assertEqual(isolation.checkout_of(self.work / "kernel" / "missing.py"), self.work)

    def test_outside_repo_and_missing_sid(self) -> None:
        self.assertIsNone(self.guard(self.outside, STRANGER, 50), "레포 밖 파일은 대상이 아니다")
        found = self.guard(self.shared / "kernel" / "x.py", None, 3)
        self.assertIsNotNone(found)
        self.assertFalse(found.block, "세션 식별자를 모르면 막지 않고 경고만 한다")
        self.assertIn("No session id", found.message)

    def test_changed_lines(self) -> None:
        from kernel.isolation import changed_lines
        one = {"file_path": "a.py", "old_string": "a\nb\nc", "new_string": "a\nB\nc"}
        self.assertEqual(changed_lines("Edit", one), 1, "3줄 문맥 속 1줄 교체는 1이다")
        self.assertEqual(changed_lines("Edit", {"old_string": "a", "new_string": "a\nb\nc"}), 2)
        self.assertEqual(changed_lines("Write", {"content": "1\n2\n3\n"}), 3)
        self.assertEqual(changed_lines("NotebookEdit", {"new_source": "x = 1\ny = 2"}), 2)
        self.assertEqual(changed_lines("MultiEdit", {"edits": [one, dict(one, new_string="a\nb\nC\nD")]}), 3)
        self.assertEqual(changed_lines("apply_patch", {"command": PATCH_REPLACE}), 1)
        self.assertEqual(changed_lines("apply_patch", PATCH_ADD), 3)
        target = self.shared / "kernel" / "x.py"
        target.write_text("foo\nfoo\nfoo\n", encoding="utf-8")
        many = {"file_path": str(target), "old_string": "foo", "new_string": "bar", "replace_all": True}
        self.assertEqual(changed_lines("Edit", many), 3, "replace_all 은 바뀌는 자리 수만큼 센다")
        self.assertEqual(changed_lines("Bash", {"command": "ls"}), 0)

    def test_exit_command_only_at_segment_head(self) -> None:
        from kernel.isolation import exit_command
        self.assertEqual(exit_command("git push origin HEAD"), ("git push", None))
        self.assertEqual(exit_command("gh pr create --fill"), ("gh pr create", None))
        self.assertEqual(exit_command("gh pr checks 1 && gh pr merge 1 --squash"), ("gh pr merge", None))
        self.assertEqual(exit_command("git merge origin/main"), ("git merge", None))
        self.assertEqual(exit_command("git -C worktrees/x--abcd1234 push -u origin feat/x"),
                         ("git push", Path("worktrees/x--abcd1234")))
        for prose in ('echo "git push"', 'git commit -m "git push 는 나중에"', "echo done && echo git push",
                      "git commit -q -F - <<'EOF'\nfix: git push 전 검사\nEOF", "git status"):
            with self.subTest(prose=prose):
                self.assertIsNone(exit_command(prose))

    def _stub_runner(self, body: str) -> None:
        (self.shared / "kernel" / "__init__.py").write_text("", encoding="utf-8")
        (self.shared / "kernel" / "runner.py").write_text(body, encoding="utf-8")

    def test_exit_gate_follows_verify_exit(self) -> None:
        from kernel import isolation
        self.assertIsNone(isolation.exit_gate("git push", self.shared), "러너 없는 체크아웃은 대상이 아니다")
        self._stub_runner("import sys\nsys.exit(0)\n")
        self.assertIsNone(isolation.exit_gate("git push origin HEAD", self.shared))
        self.assertIsNone(isolation.exit_gate("ls", self.shared))
        self._stub_runner(FAILING_RUNNER)
        found = isolation.exit_gate("git push origin HEAD", self.shared)
        self.assertIsNotNone(found)
        self.assertTrue(found.block, found)
        self.assertIn("[EXIT GATE] check before `git push`", found.message)
        self.assertIn("[FAIL] 검사 (slug)", found.message)
        self.assertIn("exited 1", found.message)
        self._stub_runner("raise RuntimeError('broken runner')\n")
        crashed = isolation.exit_gate("gh pr create", self.shared)
        self.assertIsNotNone(crashed)
        self.assertTrue(crashed.block, "러너 크래시도 통과가 아니다(fail-closed)")

    def test_exit_gate_uses_git_c_checkout(self) -> None:
        from kernel import isolation
        self._stub_runner(FAILING_RUNNER)
        self.assertIsNone(isolation.exit_gate("git -C worktrees/admin-report-viewers--abcd1234 push", self.shared),
                          "-C 가 가리키는 worktree 에는 러너가 없으니 대상이 아니다")
        (self.work / "kernel" / "__init__.py").write_text("", encoding="utf-8")
        (self.work / "kernel" / "runner.py").write_text(FAILING_RUNNER, encoding="utf-8")
        found = isolation.exit_gate("git -C worktrees/admin-report-viewers--abcd1234 push", self.shared)
        self.assertIsNotNone(found)
        self.assertIn(str(self.work), found.message)


if __name__ == "__main__":
    unittest.main()
