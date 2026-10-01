"""tests/test_stack_words.py — 스택 단어 래칫(`harness_gates/stack_words.py`)과 그 짝인 조각 합성(`kernel/conventions.py`)의 행동 테스트.

두 모듈은 한 장치의 양면이다. 합성이 조각을 「스택 관례」 절에 넣고, 래칫은 절 밖 문서에 스택 이름이
되돌아오는 것을 막는다. 한쪽만 맞으면 문서가 스택을 추정하거나 조각을 넣을 자리가 없다.

  래칫   `dev/X.md` 의 React 는 위반 · `dev/LESSONS.md`·조각·픽스처·작업 산출물은 통과 · 허용 위치 경로의
         백틱 참조는 통과 · 생성 절 안은 통과 · 실물 조각 두 개가 게이트 대상에서 빠진다
  합성   두 조각이 표식 사이에 이름순으로 · 손으로 고친 절이 재생성으로 되돌아감 · 프로젝트 조각이 커널 조각을
         덮음 · 팩 없음이면 자리 표시 한 줄 · 없는 팩·표식 없는 문서는 오류

실행: `python -X utf8 -m pytest tests/test_stack_words.py -q`
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from harness_test_support import TemporaryRootTestCase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness_gates import stack_words          # noqa: E402  (경로 삽입 후에만 import 가능)
from kernel import conventions                 # noqa: E402

FRAGMENT = ("# 제목\n\n> 담는 것: A. 담지 않는 것: B. 읽는 시점: C.\n\n"
            "### Vue 화면 관례\n\n| # | 주제 |\n|---|---|\n| V1 | 훅 |\n")


class StackWordsTests(unittest.TestCase):
    def test_stack_word_in_doc_is_violation(self) -> None:
        bad = stack_words.scan("dev/X.md", "화면은 React 로 만든다.\n서버는 FastAPI.\n")
        self.assertEqual(len(bad), 2, bad)
        self.assertIn("dev/X.md:1: stack name 'React'", bad[0])
        self.assertIn("dev/X.md:2: stack name 'FastAPI'", bad[1])

    def test_all_five_words_are_caught_case_insensitively(self) -> None:
        text = "useApi tanstack colors.ts REACT fastapi\n"
        self.assertEqual(len(stack_words.scan("design/X.md", text)), 5)

    def test_allowed_locations_pass(self) -> None:
        for rel in ("dev/LESSONS.md", "kernel/frameworks/react.md", "tests/fixtures/x/README.md",
                    "docs/tasks/archive/2026-09-28-x/plan_x.md"):
            self.assertEqual(stack_words.scan(rel, "React FastAPI useApi\n"), [], rel)

    def test_backtick_reference_to_allowed_path_passes(self) -> None:
        text = "기본 탑재 조각은 `kernel/frameworks/react.md` 와 `kernel/frameworks/fastapi.md` 다.\n"
        self.assertEqual(stack_words.scan("dev/CONVENTIONS.md", text), [])
        self.assertEqual(len(stack_words.scan("dev/CONVENTIONS.md", text + "React 가 기본이다.\n")), 1)

    def test_generated_section_is_skipped(self) -> None:
        text = f"머리\n{conventions.BEGIN}\nReact 관례 표\n{conventions.END}\n꼬리 React\n"
        bad = stack_words.scan("dev/CONVENTIONS.md", text)
        self.assertEqual([line.split(":")[1] for line in bad], ["5"], bad)

    def test_word_boundary_does_not_match_prose(self) -> None:
        self.assertEqual(stack_words.scan("dev/X.md", "reaction 과 reactive 는 스택 이름이 아니다\n"), [])

    def test_shipped_fragments_are_not_targets(self) -> None:
        rels = {path.relative_to(ROOT).as_posix() for path in stack_words.targets()}
        self.assertNotIn("kernel/frameworks/react.md", rels)
        self.assertIn("dev/CONVENTIONS.md", rels)

    def test_run_returns_one_titled_section(self) -> None:
        results = stack_words.run([], [])
        self.assertEqual([title for title, _bad in results], [stack_words.TITLE])


class ConventionsTests(TemporaryRootTestCase):
    def test_render_is_deterministic_and_wrapped(self) -> None:
        first = conventions.render_conventions(("react", "fastapi"))
        second = conventions.render_conventions(("fastapi", "react", "react"))
        self.assertEqual(first, second)
        lines = first.splitlines()
        self.assertEqual(lines[0], conventions.BEGIN)
        self.assertEqual(lines[-1], conventions.END)
        self.assertLess(first.index("kernel/frameworks/fastapi.md"), first.index("kernel/frameworks/react.md"))
        self.assertIn("### React 화면 관례", first)
        self.assertIn("### FastAPI 서버 관례", first)
        self.assertNotIn("> 담는 것:", first, "조각의 역할 계약이 절에 딸려 들어갔다")

    def test_no_packs_renders_placeholder(self) -> None:
        self.assertEqual(conventions.render_conventions(()),
                         f"{conventions.BEGIN}\n{conventions.NONE_LINE}\n{conventions.END}")

    def test_unknown_pack_is_error(self) -> None:
        with self.assertRaises(ValueError):
            conventions.render_conventions(("nope",))
        with self.assertRaises(ValueError):
            conventions.render_conventions(("../x",))

    def test_project_fragment_overrides_shipped(self) -> None:
        project = self.root / conventions.PROJECT_DIR
        project.mkdir(parents=True)
        (project / "react.md").write_text(FRAGMENT, encoding="utf-8")
        rendered = conventions.render_conventions(("react",), root=self.root)
        self.assertIn("profiles/framework/react.md", rendered)
        self.assertIn("### Vue 화면 관례", rendered)
        self.assertNotIn("### React 화면 관례", rendered)

    def test_hand_edit_is_reverted_by_regeneration(self) -> None:
        doc = self.root / "CONVENTIONS.md"
        rendered = conventions.render_conventions(("fastapi",))
        doc.write_text(f"# 문서\n\n## 스택 관례\n\n{rendered}\n\n## 다음\n", encoding="utf-8")
        edited = doc.read_text(encoding="utf-8").replace("### FastAPI 서버 관례", "### 손으로 고침")
        doc.write_text(edited, encoding="utf-8")
        self.assertTrue(conventions.write(("fastapi",), doc=doc))
        self.assertIn("### FastAPI 서버 관례", doc.read_text(encoding="utf-8"))
        self.assertFalse(conventions.write(("fastapi",), doc=doc), "같은 내용인데 다시 썼다")
        self.assertTrue(doc.read_text(encoding="utf-8").endswith("## 다음\n"), "절 바깥이 바뀌었다")

    def test_missing_markers_is_error(self) -> None:
        with self.assertRaises(ValueError):
            conventions.replace_section("# 표식 없음\n", conventions.render_conventions(()))

    def test_repo_document_carries_markers(self) -> None:
        text = (ROOT / conventions.DOC).read_text(encoding="utf-8")
        self.assertEqual(text.count(conventions.BEGIN), 1)
        self.assertEqual(text.count(conventions.END), 1)


if __name__ == "__main__":
    unittest.main()
