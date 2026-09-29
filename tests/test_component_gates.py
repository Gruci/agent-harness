"""Behavioral boundaries for graph classification and Python dependencies."""
import copy
import importlib
import unittest
from unittest.mock import patch

from harness_test_support import TemporaryRootTestCase
from test_component_graph import example_graph


class ComponentGateTests(TemporaryRootTestCase):
    def setUp(self):
        super().setUp()
        try:
            self.classification = importlib.import_module("kernel.gates.components")
            self.dependencies = importlib.import_module("kernel.gates.context_api")
        except ModuleNotFoundError:
            self.fail("component gates are not implemented")
        self.graph = example_graph()

    def source(self, relative, content=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def second_component(self):
        second = copy.deepcopy(self.graph["components"][0])
        second.update(id="payments", name="Payments", root="payments")
        second["public"] = [{"id": "pay", "module": "payments.api", "symbols": ["charge"]}]
        self.graph["components"].append(second)

    def test_missing_and_duplicate_ownership(self):
        path = self.source("missing.py")
        self.assertTrue(self.classification.check(self.graph, self.root, [path]))
        self.graph["components"][0]["roles"]["usecases"] = ["*.py"]
        path = self.source("orders/api.py")
        self.assertTrue(any("multiple" in e for e in self.classification.check(self.graph, self.root, [path])))

    def test_retired_source_and_empty_implemented(self):
        self.assertTrue(self.classification.check(self.graph, self.root, []))
        self.graph["components"][0]["state"] = "retired"
        path = self.source("orders/api.py")
        self.assertTrue(self.classification.check(self.graph, self.root, [path]))

    def test_public_contract_requires_edge(self):
        self.second_component()
        paths = [self.source("orders/api.py", "from payments.api import charge\ndef place(): pass\n"),
                 self.source("payments/api.py", "def charge(): pass\n")]
        bad, _, observed = self.dependencies.check(self.graph, self.root, paths)
        self.assertTrue(bad)
        self.assertTrue(observed)
        self.graph["edges"] = [{"source": "orders", "target": "payments", "contract": "pay", "kind": "import"}]
        self.assertEqual(([], []), self.dependencies.check(self.graph, self.root, paths)[:2])

    def test_private_symbol_bypass(self):
        self.second_component()
        self.graph["edges"] = [{"source": "orders", "target": "payments", "contract": "pay", "kind": "import"}]
        paths = [self.source("orders/api.py", "from payments.api import secret\n"),
                 self.source("payments/api.py", "def charge(): pass\ndef secret(): pass\n")]
        self.assertTrue(self.dependencies.check(self.graph, self.root, paths)[0])

    def test_public_declaration_requires_real_symbol(self):
        path = self.source("orders/api.py", "def wrong(): pass\n")
        self.assertTrue(any("public symbol" in error for error in self.dependencies.check(self.graph, self.root, [path])[0]))

    def test_attribute_private_bypass(self):
        self.second_component()
        self.graph["edges"] = [{"source": "orders", "target": "payments", "contract": "pay", "kind": "import"}]
        paths = [self.source("orders/api.py", "import payments.api as pay\npay.secret()\n"),
                 self.source("payments/api.py", "def charge(): pass\ndef secret(): pass\n")]
        self.assertTrue(any("private symbol" in error for error in self.dependencies.check(self.graph, self.root, paths)[0]))

    def test_unknown_language_and_dynamic_import_not_success(self):
        path = self.source("orders/api.py", "__import__('payments.api')\n")
        self.assertTrue(self.dependencies.check(self.graph, self.root, [path])[1])
        self.graph["technology"]["syntax"] = "ruby"
        self.assertTrue(self.dependencies.check(self.graph, self.root, [path])[1])

    def test_external_policy_not_blanket_allowed(self):
        path = self.source("orders/api.py", "import requests\ndef place(): pass\n")
        self.assertTrue(self.dependencies.check(self.graph, self.root, [path])[0])
        self.graph["components"][0]["external"] = ["requests"]
        self.assertFalse(self.dependencies.check(self.graph, self.root, [path])[0])

    def test_fake_name_does_not_prove_protocol(self):
        path = self.source("orders/api.py", "from typing import Protocol\nclass Store(Protocol):\n def get(self): ...\nclass FakeStore: pass\n")
        self.graph["components"][0]["external"] = ["typing"]
        self.assertTrue(self.dependencies.check(self.graph, self.root, [path])[0])

    def test_read_only_and_relative_import(self):
        paths = [self.source("orders/api.py", "from .internal import rule\ndef place(): pass\n"),
                 self.source("orders/internal.py", "def rule(): pass\n")]
        before = {path: path.read_bytes() for path in paths}
        self.assertEqual(([], []), self.dependencies.check(self.graph, self.root, paths)[:2])
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_diagram_coverage_uses_implemented_graph_components(self):
        import json
        from kernel.gates import arch_diagram
        planned = copy.deepcopy(self.graph["components"][0])
        planned.update(id="future", root="future", state="planned", public=[])
        self.graph["components"].append(planned)
        self.source("orders/api.py", "def place(): pass\n")
        self.source("docs/architecture/components.json", json.dumps(self.graph))
        with patch.object(arch_diagram, "ROOT", self.root), patch.object(arch_diagram.profile, "COMPONENT_GRAPH", "docs/architecture/components.json"):
            self.assertEqual(("orders/",), arch_diagram.expected_nodes())

    def test_feature_map_does_not_require_a_second_renderer_artifact(self):
        from kernel.gates import arch_diagram
        with patch.object(arch_diagram, "diagrams", return_value=[]), patch.object(arch_diagram, "expected_nodes", return_value=("orders/",)), patch.object(arch_diagram.profile, "STAGE", "growing"):
            self.assertEqual(([], []), arch_diagram.check_arch_diagram())


if __name__ == "__main__":
    unittest.main()
