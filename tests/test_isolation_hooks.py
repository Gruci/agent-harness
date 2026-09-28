"""tests/test_isolation_hooks.py — 격리 강제의 훅 수준 행동: 실제 체크아웃에서 kernel.hook 을 돌린다.

`tests/test_isolation.py` 가 판정 함수를 잡고, 여기는 두 런타임의 채널까지 본다 — Claude 는
exit 와 stderr, Codex 는 exit 와 `{"systemMessage": …}` 다.

  worktree 안 Stop     차단(2) 대신 [WIP] 알림 — Claude exit 1, Codex exit 0 + systemMessage
  나올 때 검사         --verify 통과면 push 가 나가고, 위반이 생기면 push·PR·merge 가 막힌다
  편집 가드            apply_patch 와 Edit 가 같은 문구로 막히고 1줄·예외 경로는 통과한다
  보드 등록            내 #sid 파일이 없으면 막히고 등록 자체(workboard/)는 막지 않는다

실행: `python -X utf8 -m pytest tests/test_isolation_hooks.py -q`
"""

from __future__ import annotations

import json
import unittest

from test_shared_harness import SharedHookFixture

THREE_LINE_EDIT = {"file_path": "kernel/x.py", "old_string": "a\nb\nc", "new_string": "x\ny\nz"}
PATCH = ("*** Begin Patch\n*** Update File: kernel/x.py\n@@\n-a\n-b\n-c\n+x\n+y\n+z\n*** End Patch")


class IsolationHookTests(SharedHookFixture):
    def edit_payload(self, session_id: str = "abcdef1234", **tool_input: object) -> dict[str, object]:
        return {"cwd": str(self.root), "session_id": session_id, "tool_name": "Edit",
                "tool_input": dict(THREE_LINE_EDIT, **tool_input)}

    def test_worktree_stop_notifies_instead_of_blocking(self) -> None:
        work = self.linked_worktree()
        (work / "bad.py").write_text("def outer():\n    def hidden():\n        return 1\n", encoding="utf-8")
        result = self.hook("Stop", {"cwd": str(work), "session_id": "abcdef1234"}, "claude")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("[WIP]", result.stderr)
        self.assertIn("bad.py", result.stderr)
        codex = self.hook("Stop", {"cwd": str(work), "session_id": "abcdef1234"})
        self.assertEqual(codex.returncode, 0, codex.stderr)
        self.assertIn("[WIP]", json.loads(codex.stdout)["systemMessage"])
        main = self.hook("Stop", {"cwd": str(self.root), "session_id": "abcdef1234"})
        self.assertEqual(main.returncode, 0, "메인 체크아웃은 그 worktree 의 미추적 파일을 모른다")

    def test_exit_gate_blocks_push_until_verify_passes(self) -> None:
        passed = self.hook("PreToolUse", self.bash_payload("git push origin HEAD"))
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(json.loads(passed.stdout), {})
        self.write_code("bad.py", "def outer():\n    def hidden():\n        return 1\n")
        for command in ("git push origin HEAD", "gh pr create --fill", "git merge origin/main"):
            with self.subTest(command=command):
                blocked = self.hook("PreToolUse", self.bash_payload(command), "claude")
                self.assertEqual(blocked.returncode, 2, blocked.stderr)
                self.assertIn("[EXIT GATE]", blocked.stderr)
                self.assertIn("bad.py", blocked.stderr)
        prose = self.hook("PreToolUse", self.bash_payload('echo "git push" && git commit -m "git push 전"'))
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(json.loads(prose.stdout), {})

    def test_edit_guard_blocks_main_checkout_for_both_runtimes(self) -> None:
        self.register_task()
        patch = {"cwd": str(self.root), "session_id": "abcdef1234", "tool_name": "apply_patch",
                 "tool_input": {"command": PATCH}}
        codex = self.hook("PreToolUse", patch)
        self.assertEqual(codex.returncode, 2, codex.stderr)
        self.assertIn("[ISOLATION] 메인 체크아웃", codex.stderr)
        self.assertIn("worktrees/kernel-fixture--abcdef12", codex.stderr)
        claude = self.hook("PreToolUse", self.edit_payload(), "claude")
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertIn("worktrees/kernel-fixture--abcdef12", claude.stderr)
        one_line = self.hook("PreToolUse", self.edit_payload(new_string="a\nB\nc"), "claude")
        self.assertEqual(one_line.returncode, 0, one_line.stderr)
        exempt = self.edit_payload(file_path="docs/tasks/plan_x.md", content="1\n2\n3\n")
        exempt["tool_name"] = "Write"
        self.assertEqual(self.hook("PreToolUse", exempt, "claude").returncode, 0)

    def test_edit_guard_requires_board_file(self) -> None:
        result = self.hook("PreToolUse", self.edit_payload("ffffffff0000"), "claude")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("등록부터", result.stderr)
        self.assertIn("#sid:ffffffff", result.stderr)
        board = self.edit_payload("ffffffff0000", file_path="workboard/a.md", content="1\n2\n3\n")
        board["tool_name"] = "Write"
        self.assertEqual(self.hook("PreToolUse", board, "claude").returncode, 0, "등록 자체는 막지 않는다")


if __name__ == "__main__":
    unittest.main()
