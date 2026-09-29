"""Generated maps preserve planned intent and read-only drift detection."""
import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path

from harness_test_support import TemporaryRootTestCase
from test_component_graph import example_graph


class FeatureMapTests(TemporaryRootTestCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        try:
            self.maps = importlib.import_module("kernel.feature_map")
        except ModuleNotFoundError:
            self.fail("feature map generation is not implemented")
        self.graph = example_graph()
        self.write("orders/api.py", "def place():\n    return 1\n")
        self.write("docs/architecture/components.json", json.dumps(self.graph))

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_missing_map_is_drift_without_writes(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        self.assertTrue(self.maps.check(self.root))
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_generation_detects_actual_source_changes(self):
        self.maps.generate(self.root)
        self.assertEqual([], self.maps.check(self.root))
        self.write("orders/api.py", "def place():\n    return 2\n")
        self.assertTrue(self.maps.check(self.root))

    def test_planned_node_has_no_fabricated_evidence(self):
        planned = copy.deepcopy(self.graph["components"][0])
        planned.update(id="payments", name="Payments", root="payments", public=[], state="planned")
        self.graph["components"].append(planned)
        self.write("docs/architecture/components.json", json.dumps(self.graph))
        self.maps.generate(self.root)
        result = json.loads((self.root / self.maps.JSON_PATH).read_text(encoding="utf-8"))
        node = next(item for item in result["components"] if item["id"] == "payments")
        self.assertEqual([], node["sources"])
        self.assertEqual("planned", node["state"])
        self.assertNotIn("commit", json.dumps(result))

    def test_untracked_unclassified_sources_are_visible(self):
        self.write("stray.py", "value = 1\n")
        self.maps.generate(self.root)
        result = json.loads((self.root / self.maps.JSON_PATH).read_text(encoding="utf-8"))
        self.assertEqual(["stray.py"], result["unclassified"])

    def test_excluded_files_do_not_affect_map(self):
        self.graph["technology"]["exclude"] = [{"path": "tests", "reason": "test code"}]
        self.write("docs/architecture/components.json", json.dumps(self.graph))
        self.maps.generate(self.root)
        self.write("tests/test_orders.py", "assert True\n")
        self.assertEqual([], self.maps.check(self.root))

    def test_cli_check_does_not_create_artifacts(self):
        result = subprocess.run([sys.executable, "-m", "kernel.feature_map", "--root", str(self.root), "--check"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse((self.root / self.maps.JSON_PATH).exists())

    def test_graph_edit_is_detected(self):
        self.maps.generate(self.root)
        self.graph["components"][0]["responsibility"] = "Place prepaid orders"
        self.write("docs/architecture/components.json", json.dumps(self.graph))
        self.assertTrue(self.maps.check(self.root))

    def test_gitignored_source_is_not_project_evidence(self):
        self.write(".gitignore", "ignored.py\n")
        self.maps.generate(self.root)
        self.write("ignored.py", "value = 9\n")
        self.assertEqual([], self.maps.check(self.root))

    def test_unsupported_language_stays_unverified_in_projection(self):
        self.graph["technology"]["syntax"] = "ruby"
        self.write("docs/architecture/components.json", json.dumps(self.graph))
        result = self.maps.project(self.root)
        self.assertEqual("unverified", result["dependency_observation"])
        self.assertTrue(result["unverified_dependencies"])

    def test_markdown_tampering_is_drift(self):
        self.maps.generate(self.root)
        self.write(self.maps.MARKDOWN_PATH, "# All approved\n")
        self.assertTrue(any(self.maps.MARKDOWN_PATH in error for error in self.maps.check(self.root)))

    def test_actual_import_does_not_add_declared_permission(self):
        target = copy.deepcopy(self.graph["components"][0])
        target.update(id="pricing", name="Pricing", root="pricing",
                      public=[{"id": "price-api", "module": "pricing.api", "symbols": ["price"]}])
        self.graph["components"].append(target)
        self.write("docs/architecture/components.json", json.dumps(self.graph))
        self.write("orders/api.py", "from pricing.api import price\ndef place():\n    return price()\n")
        self.write("pricing/api.py", "def price():\n    return 1\n")
        self.maps.generate(self.root)
        result = json.loads((self.root / self.maps.JSON_PATH).read_text(encoding="utf-8"))
        self.assertEqual([], result["declared_edges"])
        self.assertTrue(result.get("observed_edges"), "actual dependency evidence is missing")
        self.assertEqual("pricing", result["observed_edges"][0]["target"])
        self.assertTrue(result["dependency_violations"])

    def test_outside_symlink_source_is_rejected(self):
        outside = self.root.parent / (self.root.name + "-outside.py")
        outside.write_text("secret = 1", encoding="utf-8")
        self.addCleanup(outside.unlink)
        try:
            (self.root / "orders" / "escape.py").symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(ValueError):
            self.maps.generate(self.root)
