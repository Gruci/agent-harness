"""Syntax facts: the Python adapter keeps the old ast judgments; tree-sitter and pack_check paths."""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from kernel import facts, lang, pack_check, profile
from kernel.analyzers import python as python_analyzer, treesitter
from kernel.gates import core

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_test_support import TemporaryRootTestCase   # noqa: E402  (site-packages 의 `tests` 패키지가 tests.* 를 가린다)

HAS_TREE_SITTER = importlib.util.find_spec("tree_sitter") is not None
ADAPTER = python_analyzer.PythonAnalyzer()
GO_MODULE = "module example.com/app\n"


class PythonAdapterTests(unittest.TestCase):
    def test_nested_def_carries_enclosing_function(self):
        found = ADAPTER.analyze("def outer():\n    def inner():\n        return 1\n    return inner()\n", "utils/closure.py")
        self.assertEqual([(fn.name, fn.parent) for fn in found.functions], [("outer", None), ("inner", "outer")])
        self.assertEqual(core.nested_pairs(found), [(2, "outer > inner")])

    def test_class_is_not_an_enclosing_function(self):
        found = ADAPTER.analyze("class A:\n    def m(self):\n        pass\n", "a.py")
        self.assertEqual([(fn.name, fn.parent) for fn in found.functions], [("m", None)])

    def test_span_and_type_gaps_match_gate_wording(self):
        source = ("def agg(conn, other):\n    return 1\n\ndef _hidden(x):\n    pass\n\n"
                  "class K:\n    def go(self, n: int) -> None:\n        pass\n")
        found = ADAPTER.analyze(source, "db/conn.py")
        agg, hidden, go = found.functions
        self.assertEqual((agg.line, agg.end_line, agg.public), (1, 2, True))
        self.assertFalse(hidden.public)
        self.assertEqual((go.missing_types, go.missing_return), ((), False))
        self.assertEqual(core.untyped_functions(found), [(agg, ["conn", "other", "반환"])])

    def test_long_function_span(self):
        found = ADAPTER.analyze("def long_calc():\n" + "    x = 1\n" * 80 + "    return x\n", "utils/long.py")
        self.assertEqual([(fn.name, span) for fn, span in core.long_functions(found)], [("long_calc", 82)])

    def test_async_facts(self):
        found = ADAPTER.analyze("async def handler():\n    await work()\n\nasync def lazy():\n    return 1\n", "web/r.py")
        self.assertEqual([(fn.is_async, fn.awaits) for fn in found.functions], [(True, True), (True, False)])

    def test_relative_import_resolves_from_module_key(self):
        api = ADAPTER.analyze("from .internal import rule\nfrom . import sibling\nimport os.path\n", "orders/api.py")
        self.assertEqual([(item.module, item.symbol, item.line) for item in api.imports],
                         [("orders.internal", "rule", 1), ("orders", "sibling", 2), ("os.path", None, 3)])
        self.assertTrue(all(item.external is None for item in api.imports))   # 내부·외부는 게이트가 소스 목록으로 가른다
        package = ADAPTER.analyze("from .api import place\n", "orders/__init__.py")
        self.assertEqual((package.module, package.imports[0].module), ("orders", "orders.api"))
        deep = ADAPTER.analyze("from ..top import y\n", "orders/sub/mod.py")
        self.assertEqual(deep.imports[0].module, "orders.top")

    def test_top_symbols_and_python_only_extra(self):
        source = ("import payments.api as pay\nfrom typing import Protocol\nX: int = 1\nY = 2\n"
                  "def f(): pass\nclass C: pass\npay.secret()\nimportlib.import_module('x')\n")
        found = ADAPTER.analyze(source, "orders/api.py")
        self.assertEqual(found.top_symbols, frozenset({"pay", "Protocol", "X", "Y", "f", "C"}))
        self.assertIn(("payments.api.secret", 7), found.extra["attributes"])
        self.assertIn(("payments.api.secret", 7), found.extra["calls"])
        self.assertIn(("importlib.import_module", 8), found.extra["calls"])
        self.assertIsNotNone(found.extra["tree"])

    def test_syntax_error_is_a_fact_not_a_crash(self):
        found = ADAPTER.analyze("def broken(:\n", "x.py")
        self.assertTrue(found.error)
        self.assertEqual((found.functions, found.module), ((), "x"))


class FactsSelectionTests(TemporaryRootTestCase):
    def test_python_is_always_available(self):
        analyzer, reason = facts.select("python")
        self.assertEqual((reason, analyzer.label), ("", "Python"))

    def test_unknown_syntax_is_unverified_not_silent(self):
        self.assertEqual(facts.select("ruby"), (None, "ruby 구문 분석기가 없어 검사 못 함"))
        self.assertEqual(facts.select(None)[1], "미선언 구문 분석기가 없어 검사 못 함")

    def test_profile_kinds_follow_the_selected_pack(self):
        self.assertEqual(profile.SYNTAX, "python")     # 이 레포의 프로파일 — 사실 종류 전부를 낸다
        for kind in ("functions", "nesting", "types", "imports", "top_symbols", "python"):
            self.assertEqual(facts.unavailable(kind), "")
        self.assertEqual(facts.unavailable("routes"), "python 구문 분석기가 없어 검사 못 함")

    def test_pack_without_engine_keeps_python_only_reason(self):
        go = lang.load("go")
        self.assertEqual(facts.query_kinds(go["QUERIES"]), frozenset({"functions", "nesting", "imports", "top_symbols"}))
        with patch.object(profile, "SYNTAX", "go"), patch.object(profile, "PACK", go), patch.dict(facts._SELECTED, clear=True):
            self.assertEqual(facts.unavailable("python"), "go 구문 분석기가 없어 검사 못 함")
            functions = facts.unavailable("functions")
        self.assertTrue(functions == "" or functions.startswith("tree-sitter"))

    def test_facts_for_caches_until_the_file_changes(self):
        path = self.root / "m.py"
        path.write_text("def a(): pass\n", encoding="utf-8")
        first = facts.facts_for(path, "m.py", ADAPTER)
        self.assertIs(first, facts.facts_for(path, "m.py", ADAPTER))
        path.write_text("def a(): pass\n\ndef b(): pass\n", encoding="utf-8")
        self.assertEqual([fn.name for fn in facts.facts_for(path, "m.py", ADAPTER).functions], ["a", "b"])

    def test_unreadable_file_is_an_error_fact(self):
        found = facts.facts_for(self.root / "missing.py", "missing.py", ADAPTER)
        self.assertTrue(found.error)
        self.assertEqual(found.module, "missing")


class PackKeyTests(TemporaryRootTestCase):
    def write_pack(self, body):
        folder = self.root / lang.PROJECT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "odd.py").write_text("EXT = ('*.odd',)\nSYNTAX = 'odd'\n" + body, encoding="utf-8")

    def test_new_pack_keys_are_validated(self):
        for body in ("MODULE_RULE = 'nope'\n", "PUBLIC_RULE = 'nope'\n", "QUERIES = {'functions': 1}\n", "FIXTURES = []\n"):
            self.write_pack(body)
            with self.subTest(body=body), patch.object(lang, "ROOT", self.root), self.assertRaises(ValueError):
                lang.load("odd")

    def test_new_pack_keys_default_to_empty(self):
        self.write_pack("")
        with patch.object(lang, "ROOT", self.root):
            pack = lang.load("odd")
        self.assertEqual((pack["QUERIES"], pack["MODULE_RULE"], pack["PUBLIC_RULE"], pack["FIXTURES"]), ({}, None, None, {}))
        self.assertEqual(facts.analyzer_for_pack(pack, self.root), (None, "odd 구문 분석기가 없어 검사 못 함"))


@unittest.skipUnless(HAS_TREE_SITTER, treesitter.MISSING)
class TreeSitterGoTests(TemporaryRootTestCase):
    def engine(self):
        (self.root / "go.mod").write_text(GO_MODULE, encoding="utf-8")
        engine, reason = treesitter.build(lang.load("go"), self.root)
        if engine is None:
            self.skipTest(reason)
        return engine

    def test_function_span_drives_func_limit(self):
        engine = self.engine()
        long = engine.analyze("package a\n\nfunc F() {\n" + "\t_ = 1\n" * 81 + "}\n", "a/a.go")
        self.assertEqual([(fn.name, span) for fn, span in core.long_functions(long)], [("F", 83)])
        short = engine.analyze("package a\n\nfunc F() {}\n", "a/a.go")
        self.assertEqual(core.long_functions(short), [])
        self.assertIsNone(short.functions[0].missing_types)     # 언어가 타입을 강제한다
        self.assertTrue(short.functions[0].public)

    def test_internal_import_resolves_to_module_key(self):
        engine = self.engine()
        found = engine.analyze('package a\n\nimport (\n\t"fmt"\n\t"example.com/app/db/reads"\n)\n', "batches/job.go")
        self.assertEqual(found.module, "batches")
        self.assertEqual([(item.module, item.external) for item in found.imports], [(None, "fmt"), ("db.reads", None)])
        self.assertEqual(engine.module_key("main.go"), "app")

    def test_top_symbols_and_methods(self):
        engine = self.engine()
        found = engine.analyze("package a\n\ntype Thing struct{}\n\nfunc (t Thing) Do() {}\n\nfunc helper() {}\n", "a/a.go")
        self.assertEqual(found.top_symbols, frozenset({"Thing", "helper"}))
        self.assertEqual([(fn.name, fn.public) for fn in found.functions], [("Do", True), ("helper", False)])

    def test_syntax_error_is_reported_not_partial(self):
        self.assertTrue(self.engine().analyze("package a\n\nfunc (\n", "a/a.go").error)


@unittest.skipIf(HAS_TREE_SITTER, "tree-sitter 가 설치돼 있어 미설치 경로를 볼 수 없다")
class TreeSitterMissingTests(TemporaryRootTestCase):
    def test_missing_engine_names_the_install_step(self):
        self.assertEqual(treesitter.build(lang.load("go"), self.root), (None, treesitter.MISSING))
        self.assertEqual(facts.analyzer_for_pack(lang.load("go"), self.root)[1], treesitter.MISSING)


class PackCheckTests(unittest.TestCase):
    def test_python_pack_is_first_class(self):
        verdicts = pack_check.assess(lang.load("python"))
        self.assertEqual({grade for grade, _slug, _reason in verdicts}, {"1급"})
        self.assertEqual([slug for _grade, slug, _reason in verdicts], list(pack_check.GATE_SLUGS + pack_check.FACT_KINDS))

    def test_missing_fixture_is_unverified(self):
        pack = dict(lang.load("python"))
        pack["FIXTURES"] = {}
        self.assertEqual({(grade, reason) for grade, _slug, reason in pack_check.assess(pack)}, {("미검증", "예제 없음")})

    def test_mismatched_examples_are_unverified(self):
        pack = dict(lang.load("python"))
        fixtures = dict(pack["FIXTURES"])
        fixtures["func_limit"] = {"violating": fixtures["func_limit"]["passing"], "passing": fixtures["func_limit"]["passing"]}
        fixtures["closures"] = {"violating": fixtures["closures"]["violating"], "passing": fixtures["closures"]["violating"]}
        fixtures["imports"] = {"source": "import os\n", "expect": ["db.reads"]}
        pack["FIXTURES"] = fixtures
        by_slug = {slug: (grade, reason) for grade, slug, reason in pack_check.assess(pack)}
        self.assertEqual(by_slug["func_limit"], ("미검증", "위반 예제가 안 잡힘"))
        self.assertEqual(by_slug["closures"], ("미검증", "통과 예제가 잡힘"))
        self.assertEqual(by_slug["imports"], ("미검증", "기대한 값이 안 나옴: db.reads"))

    def test_not_applicable_is_not_a_loss(self):
        by_slug = {slug: (grade, reason) for grade, slug, reason in pack_check.assess(lang.load("go"))}
        self.assertEqual((by_slug["closures"][0], by_slug["type_hints"][0]), ("N/A", "N/A"))
        grade, reason = by_slug["func_limit"]
        if HAS_TREE_SITTER:
            self.assertTrue(grade == "1급" or reason.startswith("tree-sitter-go 문법 미설치"), reason)
        else:
            self.assertEqual((grade, reason), ("미검증", treesitter.MISSING))

    def test_main_reports_and_exits_nonzero_on_unverified(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pack_check.main(["python"]), 0)
        self.assertIn("[1급] func_limit", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(pack_check.main(["typescript"]), 1)     # 예제 없음 — 선언만으로 1급이 아니다
            self.assertEqual(pack_check.main(["no-such-pack"]), 2)


if __name__ == "__main__":
    unittest.main()
