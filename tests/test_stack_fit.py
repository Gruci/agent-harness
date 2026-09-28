"""Stack fit: an external analyzer command makes a toy language first-class; bad output and missing commands are never a pass; --doctor names missing tools."""

import io
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import harness_install
from kernel import facts, framework, lang, pack_check, profile, runner
from kernel.analyzers import command
from kernel.context import ROOT
from kernel.gates import context_api

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_test_support import TemporaryRootTestCase   # noqa: E402  (site-packages 의 `tests` 패키지가 tests.* 를 가린다)

# 장난감 언어: `import "a/b"` · `func Name {` … `}` (들여쓰기로 중첩) · `type Name`. 분석기는 이 언어의 "자기 도구"를 흉내 낸 스크립트다.
TOY_FACTS = '''import json
import sys


def parse(rel):
    functions, imports, symbols, stack = [], [], [], []
    with open(rel, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("import "):
            target = stripped.split('"')[1]
            internal = "/" in target
            imports.append({"module": target.replace("/", ".") if internal else None,
                            "external": None if internal else target, "symbol": None, "line": number})
        elif stripped.startswith("func ") and stripped.endswith("{"):
            name = stripped.split()[1]
            entry = {"name": name, "line": number, "end_line": number, "parent": stack[-1]["name"] if stack else None,
                     "public": name[:1].isupper(), "missing_types": None}
            functions.append(entry)
            stack.append(entry)
            if indent == 0:
                symbols.append(name)
        elif stripped == "}" and stack:
            stack.pop()["end_line"] = number
        elif stripped.startswith("type "):
            symbols.append(stripped.split()[1])
    return {"rel": rel, "module": rel.rsplit(".", 1)[0].replace("/", "."), "functions": functions,
            "imports": imports, "top_symbols": symbols, "error": None}


print(json.dumps([parse(rel) for rel in sys.argv[1:]]))
'''
BROKEN_FACTS = 'print("this is not json")\n'
TEMPLATE = ROOT / lang.PROJECT_DIR / "_template.py"
FRAMEWORK_TEMPLATE = ROOT / framework.PROJECT_DIR / "_template.py"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class ToyPackTestCase(TemporaryRootTestCase):
    """임시 레포에 장난감 언어팩과 외부 분석기 스크립트를 둔다. 팩은 템플릿을 복사해 채운 것이다."""

    def setUp(self):
        super().setUp()
        tools = self.root / "tools"
        tools.mkdir()
        self.script = tools / "toy_facts.py"
        self.script.write_text(TOY_FACTS, encoding="utf-8")
        self.broken = tools / "broken_facts.py"
        self.broken.write_text(BROKEN_FACTS, encoding="utf-8")
        self.pack_dir = self.root / lang.PROJECT_DIR
        self.pack_dir.mkdir(parents=True)
        self.write_pack((sys.executable, str(self.script)))

    def write_pack(self, analyzer_cmd, name="toy"):
        body = TEMPLATE.read_text(encoding="utf-8") + (
            f'\nEXT = ("*.toy",)\nSYNTAX = "toy"\nANALYZER_CMD = {tuple(analyzer_cmd)!r}\nREQUIRES = ()\nLINTERS = []\n')
        (self.pack_dir / f"{name}.py").write_text(body, encoding="utf-8")

    def load(self, name="toy"):
        with patch.object(lang, "ROOT", self.root):
            return lang.load(name)


class ToyPackFirstClassTests(ToyPackTestCase):
    def test_template_pack_with_command_analyzer_is_first_class(self):
        by_slug = {slug: (grade, reason) for grade, slug, reason in pack_check.assess(self.load())}
        self.assertEqual(by_slug["type_hints"][0], "N/A")
        for slug in ("closures", "func_limit", "imports", "top_symbols"):
            self.assertEqual(by_slug[slug][0], "1급", (slug, by_slug[slug]))
        self.assertIn("1급 팩", pack_check.report("toy", self.load(), list(map(tuple, pack_check.assess(self.load())))))

    def test_facts_come_from_the_command(self):
        engine, reason = facts.analyzer_for_pack(self.load(), self.root)
        self.assertEqual((reason, engine.label, engine.suffixes), ("", "외부 분석기", (".toy",)))
        found = engine.analyze('import "db/reads"\nimport "fmt"\n\nfunc Outer {\n  func inner {\n  }\n}\n', "orders/api.toy")
        self.assertIsNone(found.error)
        self.assertEqual(found.module, "orders.api")
        self.assertEqual([(item.module, item.external) for item in found.imports], [("db.reads", None), (None, "fmt")])
        self.assertEqual([(fn.name, fn.parent, fn.end_line) for fn in found.functions], [("Outer", None, 7), ("inner", "Outer", 6)])
        self.assertEqual(found.top_symbols, frozenset({"Outer"}))

    def test_broken_json_is_an_error_fact_and_unverified(self):
        self.write_pack((sys.executable, str(self.broken)))
        pack = self.load()
        engine, _reason = facts.analyzer_for_pack(pack, self.root)
        found = engine.analyze("func A {\n}\n", "a.toy")
        self.assertIn("분석기 출력 계약 위반", found.error)
        self.assertEqual((found.functions, found.module), ((), "a"))
        by_slug = {slug: (grade, reason) for grade, slug, reason in pack_check.assess(pack)}
        self.assertEqual(by_slug["func_limit"][0], "미검증")
        self.assertIn("예제 파싱 실패: 분석기 출력 계약 위반", by_slug["func_limit"][1])

    def test_missing_command_is_tool_not_pass(self):
        self.write_pack(("no-such-analyzer-xyz", "facts"))
        pack = self.load()
        analyzer, reason = facts.analyzer_for_pack(pack, self.root)
        self.assertIsNone(analyzer)
        self.assertTrue(reason.startswith("분석기 명령 no-such-analyzer-xyz 실행 불가"), reason)
        with patch.object(profile, "SYNTAX", "toy"), patch.object(profile, "PACK", pack), \
                patch.object(facts, "ROOT", self.root), patch.dict(facts._SELECTED, clear=True):
            self.assertEqual(facts.unavailable("functions"), reason)
            section = runner._syntax_section("func_limit", "함수 길이", lambda: ["never"], (), True, "", "functions")
        self.assertEqual((section[2], section[3]), ([], ("TOOL", reason)))
        self.assertEqual({grade for grade, slug, _reason in pack_check.assess(pack) if slug != "type_hints"}, {"미검증"})

    def test_reverse_import_is_detected_from_command_facts(self):
        graph = {
            "schema": 1, "revision": 1,
            "categories": [{"id": "business", "name": "Business", "description": "Rules", "roles": ["domain", "usecases"]}],
            "components": [
                {"id": "orders", "name": "Orders", "category": "business", "responsibility": "Place orders", "excludes": [],
                 "root": "orders", "roles": {"domain": ["*.toy", "**/*.toy"]},
                 "public": [{"id": "orders-api", "module": "orders.api", "symbols": ["Place"]}], "state": "implemented", "external": []},
                {"id": "payments", "name": "Payments", "category": "business", "responsibility": "Charge", "excludes": [],
                 "root": "payments", "roles": {"usecases": ["*.toy", "**/*.toy"]},
                 "public": [{"id": "pay", "module": "payments.api", "symbols": ["Charge"]}], "state": "implemented", "external": []},
            ],
            "edges": [], "technology": {"sources": ["**/*.toy"], "syntax": "toy", "exclude": []},
            "role_dependencies": {"domain": ["domain"], "usecases": ["domain", "usecases"]},
        }
        paths = [_write(self.root / "orders/api.toy", 'import "payments/api"\n\nfunc Place {\n}\n'),
                 _write(self.root / "payments/api.toy", "func Charge {\n}\n")]
        engine, _reason = facts.analyzer_for_pack(self.load(), self.root)
        with patch.object(facts, "select", lambda syntax: (engine, "")):
            violations, unverified, observed = context_api.check(graph, self.root, paths)
        # 포트 계약 검사는 Python 전용이라 다른 언어에서는 늘 미검증이다. 의존 분석 자체는 미검증이 없어야 한다.
        self.assertEqual([item for item in unverified if not item.startswith("port contracts")], [])
        self.assertTrue(any("forbidden role dependency domain -> usecases" in item for item in violations), violations)
        self.assertEqual([edge["source"] + "->" + edge["target"] for edge in observed], ["orders->payments"])


class ContractTests(unittest.TestCase):
    GOOD = {"rel": "a.toy", "module": "a", "functions": [{"name": "F", "line": 1, "end_line": 2, "parent": None,
                                                           "public": True, "missing_types": ["x"]}],
            "imports": [{"module": None, "external": "fmt", "symbol": None, "line": 1}], "top_symbols": ["F"], "error": None}

    def test_good_entry_becomes_facts(self):
        found = command.convert(self.GOOD, "a.toy", "a")
        self.assertIsNone(found.error)
        self.assertEqual((found.functions[0].missing_types, found.functions[0].awaits, found.imports[0].external), (("x",), False, "fmt"))

    def test_shape_errors_are_error_facts(self):
        for broken in ({**self.GOOD, "module": ""}, {**self.GOOD, "top_symbols": "F"}, {**self.GOOD, "functions": [{"name": "F"}]},
                       {**self.GOOD, "imports": [{"module": 1, "external": None, "symbol": None, "line": 1}]},
                       {**self.GOOD, "functions": [{**self.GOOD["functions"][0], "line": "1"}]}, "not an object"):
            with self.subTest(broken=broken):
                found = command.convert(broken, "a.toy", "a")
                self.assertTrue(found.error and found.error.startswith("분석기 출력 계약 위반"), found.error)
                self.assertEqual(found.functions, ())

    def test_reported_error_is_kept(self):
        found = command.convert({**self.GOOD, "error": "cannot read"}, "a.toy", "a")
        self.assertEqual((found.error, found.module), ("cannot read", "a"))


class PackKeyTests(TemporaryRootTestCase):
    def write_odd(self, body):
        _write(self.root / lang.PROJECT_DIR / "odd.py", "EXT = ('*.odd',)\nSYNTAX = 'odd'\n" + body)

    def test_analyzer_keys_are_validated(self):
        for body in ("ANALYZER = 'magic'\n", "ANALYZER = 'command'\n", "ANALYZER = 'treesitter'\n", "ANALYZER = 'python'\n",
                     "ANALYZER_CMD = 'go run x'\n", "GRAMMAR = 3\n", "REQUIRES = [{'name': 'go'}]\n",
                     "REQUIRES = [{'name': 'go', 'check': 'go version', 'install': ''}]\n"):
            self.write_odd(body)
            with self.subTest(body=body), patch.object(lang, "ROOT", self.root), self.assertRaises(ValueError):
                lang.load("odd")

    def test_analyzer_keys_default_and_infer(self):
        self.write_odd("")
        with patch.object(lang, "ROOT", self.root):
            odd = lang.load("odd")
        self.assertEqual((odd["ANALYZER"], odd["ANALYZER_CMD"], odd["GRAMMAR"], odd["REQUIRES"]), (None, (), None, ()))
        self.assertIsNone(lang.analyzer_kind(odd))
        self.assertEqual(lang.analyzer_kind(lang.load("python")), "python")
        go = lang.load("go")
        self.assertEqual((lang.analyzer_kind(go), lang.grammar_module(go)), ("treesitter", "tree_sitter_go"))
        self.assertEqual(lang.grammar_module({**go, "GRAMMAR": "tree_sitter_golang"}), "tree_sitter_golang")
        self.assertIsNone(lang.grammar_module(lang.load("python")))
        self.assertEqual(facts.analyzer_for_pack(odd, self.root), (None, "odd 구문 분석기가 없어 검사 못 함"))

    def test_framework_template_loads_for_both_roles(self):
        folder = self.root / framework.PROJECT_DIR
        folder.mkdir(parents=True)
        target = folder / "tpl.py"
        shutil.copy2(FRAMEWORK_TEMPLATE, target)
        with patch.object(framework, "ROOT", self.root):
            server = framework.load_one("tpl")
            target.write_text(target.read_text(encoding="utf-8") + '\nROLE = "ui"\n', encoding="utf-8")
            ui = framework.load_one("tpl")
        self.assertEqual((server["ROLE"], server["ASYNC_HANDLER"]), ("server", None))
        self.assertIn("orphan_api", server["FIXTURES"])
        self.assertEqual((ui["ROLE"], ui["UI_EXT"]), ("ui", ("*.vue", "*.ts")))


class DoctorTests(unittest.TestCase):
    def report(self, pack):
        out = io.StringIO()
        with redirect_stdout(out):
            missing = harness_install.print_stack_report(pack)
        return missing, out.getvalue()

    def test_missing_requirement_names_tool_and_install(self):
        pack = {**lang.load("python"), "REQUIRES": (
            {"name": "toolx", "check": ["no-such-tool-xyz", "version"], "install": "https://example.com/toolx"},
            {"name": "python", "check": [sys.executable, "--version"], "install": "python.org"})}
        missing, text = self.report(pack)
        self.assertEqual(missing, 1)
        self.assertIn("[없음] toolx", text)
        self.assertIn("https://example.com/toolx", text)
        self.assertIn("[있음] python", text)
        self.assertIn("설치 요구 1건", text)

    def test_framework_pack_requirements_are_reported_too(self):
        server = {"NAME": "srv", "REQUIRES": (
            {"name": "toolz", "check": ["no-such-tool-xyz"], "install": "npm i toolz"},)}
        out = io.StringIO()
        with redirect_stdout(out):
            missing = harness_install.print_stack_report(lang.load("python"), [server])
        self.assertEqual(missing, 1)
        self.assertIn("[없음] toolz", out.getvalue())

    def test_harness_itself_requires_nothing(self):
        missing, text = self.report(profile.PACK)
        self.assertEqual(missing, 0)
        self.assertIn("설치 요구 0건", text)
        self.assertIn("표준 ast", text)
        out = io.StringIO()
        with redirect_stdout(out):
            harness_install.print_language_report()
        self.assertIn("설치 요구 0건", out.getvalue())

    def test_analyzer_status_follows_the_pack(self):
        self.assertEqual(harness_install.analyzer_status(lang.load("go"))[0], "tree-sitter")
        self.assertIn("tree_sitter_go", harness_install.analyzer_status(lang.load("go"))[1])
        name, status = harness_install.analyzer_status({**lang.load("go"), "ANALYZER": "command", "ANALYZER_CMD": ("no-such-analyzer-xyz",)})
        self.assertEqual((name, status.endswith("없음")), ("외부 분석기", True))
        self.assertEqual(harness_install.analyzer_status(lang.unselected())[0], "없음")


if __name__ == "__main__":
    unittest.main()
