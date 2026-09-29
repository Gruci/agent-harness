"""Each declared port needs a fake that really implements it and a contract test that actually runs it."""
import importlib
import unittest
from harness_test_support import TemporaryRootTestCase
from test_component_graph import example_graph


class PortContractTests(TemporaryRootTestCase):
    def setUp(self):
        super().setUp()
        try:
            self.ports = importlib.import_module("kernel.port_contracts")
        except ModuleNotFoundError:
            self.fail("port contract verification is not implemented")
        self.graph = example_graph()
        self.graph["components"][0]["ports"] = [{"module": "orders.ports", "symbol": "Store",
            "fake_module": "tests.test_contract", "fake_symbol": "FakeStore", "test_module": "tests.test_contract"}]
        self.write("orders/__init__.py", "")
        self.write("tests/__init__.py", "")
        self.write("orders/ports.py", "from typing import Protocol\nclass Store(Protocol):\n def get(self, key: str) -> int: ...\n")
        self.write_test()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_test(self, body="self.assertEqual(store.get('item'), 7)", fake="def get(self, key): return 7"):
        self.write("tests/test_contract.py", "import unittest\nfrom orders.ports import Store\n"
            f"class FakeStore:\n {fake}\nclass Contract(unittest.TestCase):\n def test_get(self):\n"
            f"  store: Store = FakeStore()\n  {body}\n")

    def test_real_contract_passes(self):
        self.assertEqual(([], []), self.ports.check(self.root, self.graph))
        self.assertEqual(([], []), self.ports.run(self.root, self.graph))

    def test_name_only_fake_fails(self):
        self.write_test(fake="pass")
        self.assertTrue(self.ports.check(self.root, self.graph)[0])

    def test_wrong_method_signature_fails(self):
        self.write_test(fake="def get(self): return 7")
        self.assertTrue(self.ports.check(self.root, self.graph)[0])

    def test_test_without_fake_method_execution_fails(self):
        self.write_test(body="self.assertIsNotNone(store)")
        self.assertTrue(self.ports.run(self.root, self.graph)[0])

    def test_failing_contract_is_failure(self):
        self.write_test(body="self.assertEqual(store.get('item'), 8)")
        self.assertTrue(self.ports.run(self.root, self.graph)[0])

    def test_zero_tests_is_not_success(self):
        path = self.root / "tests/test_contract.py"
        path.write_text(path.read_text(encoding="utf-8").replace("test_get", "helper_get"), encoding="utf-8")
        self.assertTrue(self.ports.run(self.root, self.graph)[0])

    def test_unregistered_protocol_is_failure(self):
        self.graph["components"][0]["ports"] = []
        self.assertTrue(self.ports.check(self.root, self.graph)[0])

    def test_no_declared_port_has_no_requirements(self):
        self.graph["components"][0]["ports"] = []
        self.write("orders/ports.py", "def get(): return 7\n")
        self.assertEqual(([], []), self.ports.run(self.root, self.graph))

    def test_graph_mutation_from_tests_is_detected(self):
        self.write("docs/architecture/components.json", "{}")
        self.write_test(body="store.get('item'); __import__('pathlib').Path('docs/architecture/components.json').write_text('changed')")
        self.assertTrue(self.ports.run(self.root, self.graph)[0])


if __name__ == "__main__":
    unittest.main()
