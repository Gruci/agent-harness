"""tests/test_plugin_mode.py — 플러그인 설치의 판정·비키기·진입점 행동 테스트.

플러그인 설치는 커널이 프로젝트 밖(플러그인 폴더)에 있고, 훅 어댑터가 `--plugin` 으로 돈다.
템플릿 설치와 판정이 같아야 하고, 하네스를 연결하지 않은 레포와 템플릿 체크아웃에서는 비켜야 한다.

  골든 일치     밖에서 돌린 커널의 전 게이트 출력이 템플릿 정답지와 같다
  비키기        프로파일 없는 레포·템플릿 체크아웃에서 어댑터 넷이 exit 0, stderr 빈 값
  저장 검사     연결한 레포의 450줄 파일 저장이 exit 2 이고 관찰 기록이 그 레포에 남는다
  나올 때 검사  연결한 레포의 `git push` 가 `--verify` 실패로 exit 2
  코어 범위     보드 미등록 편집을 막지 않는다 — 작업 절차는 코어가 강제하지 않는다
  셸 쓰기       `> a.py` 가 연결한 레포에서는 2, 연결 안 한 레포에서는 0
  루트 전파     템플릿 체크아웃의 러너 명령은 물려받은 HARNESS_ROOT 를 지운다

실행: `python -X utf8 -m pytest tests/test_plugin_mode.py -q`
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
ADAPTERS = (("check_bash_write", "Bash"), ("check_pretool", "Bash"),
            ("check_file_rules", "Edit"), ("check_coding_rules", ""))
PROFILE = "PROFILE_SCHEMA = 1\nLANG = 'python'\nARCH = 'headless'\nLINTERS = ()\n"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _git_init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)


class PluginModeFixture(unittest.TestCase):
    """연결한 레포·연결 안 한 레포·템플릿 체크아웃 셋을 임시로 만든다."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.connected = base / "connected"
        self.unconnected = base / "unconnected"
        self.template = base / "template"
        for root in (self.connected, self.unconnected, self.template):
            _git_init(root)
        (self.connected / "harness_profile.py").write_text(PROFILE, encoding="utf-8")
        (self.template / "harness_profile.py").write_text(PROFILE, encoding="utf-8")
        shutil.copytree(REPO / "kernel", self.template / "kernel", ignore=shutil.ignore_patterns("__pycache__"))

    def hook(self, name: str, cwd: Path, payload: dict[str, object]) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", str(HOOKS / f"{name}.py"), "--plugin"],
                              cwd=cwd, input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)

    def payload(self, root: Path, tool: str) -> dict[str, object]:
        tool_input: dict[str, object] = {"command": "ls"} if tool == "Bash" else {"file_path": str(root / "x.py")}
        return {"cwd": str(root), "session_id": "abcdef1234", "tool_name": tool, "tool_input": tool_input}

    def big_file(self, root: Path) -> Path:
        path = root / "big.py"
        path.write_text('"""big.py"""\n' + "x = 1\n" * 450, encoding="utf-8")
        return path


class PluginModeTests(PluginModeFixture):
    def test_plugin_cli_matches_template_golden(self) -> None:
        import run_golden

        run_golden._ensure_fixtures()
        actual = run_golden.capture(REPO / "kernel", plugin=True)
        self.assertEqual(run_golden.GOLDEN.read_text(encoding="utf-8"), actual)

    def test_plugin_hooks_idle_without_profile(self) -> None:
        for name, tool in ADAPTERS:
            with self.subTest(hook=name):
                done = self.hook(name, self.unconnected, self.payload(self.unconnected, tool))
                self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)

    def test_plugin_hooks_idle_in_template_checkout(self) -> None:
        for name, tool in ADAPTERS:
            with self.subTest(hook=name):
                done = self.hook(name, self.template, self.payload(self.template, tool))
                self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)

    def test_plugin_save_gate_blocks_violation(self) -> None:
        big = self.big_file(self.connected)
        done = self.hook("check_file_rules", self.connected,
                         {"cwd": str(self.connected), "session_id": "abcdef1234",
                          "tool_name": "Write", "tool_input": {"file_path": str(big)}})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("line_limit", done.stderr)
        trace = (self.connected / "harness_trace.jsonl").read_text(encoding="utf-8")
        self.assertIn("check_file_rules", trace)
        own = REPO / "harness_trace.jsonl"                 # 관찰 기록은 플러그인 폴더가 아니라 프로젝트에 남는다
        self.assertFalse(own.exists() and str(big) in own.read_text(encoding="utf-8"))

    def test_plugin_exit_gate_blocks_failing_checkout(self) -> None:
        self.big_file(self.connected)
        payload = self.payload(self.connected, "Bash")
        payload["tool_input"] = {"command": "git push origin HEAD"}
        done = self.hook("check_pretool", self.connected, payload)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("[EXIT GATE]", done.stderr)

    def test_plugin_pretool_does_not_guard_edits(self) -> None:
        payload = {"cwd": str(self.connected), "session_id": "abcdef1234", "tool_name": "Write",
                   "tool_input": {"file_path": str(self.connected / "x.py"), "content": "a = 1\nb = 2\nc = 3\n"}}
        done = self.hook("check_pretool", self.connected, payload)
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)

    def test_plugin_bash_write_uses_project_root(self) -> None:
        for root, code in ((self.connected, 2), (self.unconnected, 0)):
            with self.subTest(root=root.name):
                payload = self.payload(root, "Bash")
                payload["tool_input"] = {"command": "echo x > a.py"}
                done = self.hook("check_bash_write", root, payload)
                self.assertEqual(done.returncode, code, done.stderr)
                self.assertEqual("[BASH GATE]" in done.stderr, code == 2)

    def test_runner_command_drops_inherited_root(self) -> None:
        from kernel.context import KERNEL_HOME, runner_command

        with mock.patch.dict("os.environ", {"HARNESS_ROOT": str(self.connected)}):
            template = runner_command(self.template, "--verify")
            plugin = runner_command(self.connected, "--verify")
            self.assertIsNone(runner_command(self.unconnected, "--verify"))
        self.assertIsNotNone(template)
        self.assertIsNotNone(plugin)
        argv, env = template
        self.assertEqual(argv[-3:], ["-m", "kernel.runner", "--verify"])
        self.assertNotIn("HARNESS_ROOT", env)
        argv, env = plugin
        self.assertEqual(argv[-2:], [str(KERNEL_HOME / "kernel"), "--verify"])
        self.assertEqual(env["HARNESS_ROOT"], str(self.connected))


if __name__ == "__main__":
    unittest.main()
