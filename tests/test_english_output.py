"""tests/test_english_output.py — 하네스 출력 영어 래칫(`harness_gates/english_output.py`)과 영어 출력 서식 파싱의 행동 테스트.

  래칫   한국어 리터럴은 위반 · docstring 은 무시 · `# ko-ok:` 가 같은 줄이나 바로 윗줄에 있으면 통과 ·
         훅 설정의 한국어 echo 는 위반 · run 은 제목 하나짜리 섹션을 돌려준다
  파싱   관찰 기록이 영어 `[FAIL] <제목> (<slug>) — N found` 머리에서 slug 와 위반 줄을 뽑는다

실행: `python -X utf8 -m pytest tests/test_english_output.py -q`
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness_gates import english_output       # noqa: E402  (경로 삽입 후에만 import 가능)
from kernel import trace                       # noqa: E402


class EnglishOutputGateTests(unittest.TestCase):
    def test_korean_literal_is_flagged(self) -> None:
        bad = english_output.check_source("kernel/x.py", 'MSG = "검사 불능"\nprint(f"{MSG} 위반")\n')
        self.assertEqual([line.split(":")[1] for line in bad], ["1", "2"], bad)
        self.assertIn("kernel/x.py:1: Korean text in output", bad[0])

    def test_docstring_is_ignored(self) -> None:
        text = '"""모듈 설명."""\n\n\ndef f() -> None:\n    """함수 설명."""\n    return None\n'
        self.assertEqual(english_output.check_source("kernel/x.py", text), [])

    def test_ko_ok_escape(self) -> None:
        same_line = 'KEY = "과업:"  # ko-ok: task-board format key\n'
        line_above = '# ko-ok: shows the board format\nTEXT = """- 과업:\n- 손대는 곳:\n"""\n'
        self.assertEqual(english_output.check_source("kernel/x.py", same_line + line_above), [])
        self.assertEqual(len(english_output.check_source("kernel/x.py", 'KEY = "과업:"\n')), 1)

    def test_hook_config_is_flagged(self) -> None:
        text = '{"hooks": [{"command": "echo \'[HARNESS] python 을 실행하지 못했다\'"}]}\n'
        bad = english_output.check_hook_config(".claude/settings.json", text)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn(".claude/settings.json:1: Korean text in a hook command", bad[0])
        self.assertEqual(english_output.check_hook_config("x.json", '{"command": "echo ok"}\n'), [])

    def test_run_returns_one_titled_section(self) -> None:
        results = english_output.run([], [])
        self.assertEqual([title for title, _bad in results], [english_output.TITLE])


class TraceReadsEnglishTests(unittest.TestCase):
    def test_trace_reads_english_fail_head(self) -> None:
        stdout = ("[OK]   Profile shape\n"
                  "\n[FAIL] File length limit (line_limit) — 2 found\n"
                  "   - utils/big.py: 450 lines (>400)\n"
                  "   - utils/huge.py: 900 lines (>400)\n"
                  "[SKIP] Abbreviated names — no banned abbreviations configured\n"
                  "\n[FAIL] Doc sync (doc_sync:DEVGUIDE.md) — 1 found\n"
                  "   - DEVGUIDE.md:9: BATCH_HOUR=5 but the doc says [0, 3]\n")
        with mock.patch.object(trace, "record") as record:
            trace.record_runner_output("check_coding_rules", "sid12345", stdout)
        calls = [(call.kwargs["gate"], call.kwargs["msg"]) for call in record.call_args_list]
        self.assertEqual(calls, [
            ("line_limit", "utils/big.py: 450 lines (>400)"),
            ("line_limit", "utils/huge.py: 900 lines (>400)"),
            ("doc_sync:DEVGUIDE.md", "DEVGUIDE.md:9: BATCH_HOUR=5 but the doc says [0, 3]"),
        ])


if __name__ == "__main__":
    unittest.main()
