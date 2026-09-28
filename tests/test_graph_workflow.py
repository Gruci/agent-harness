"""Decision state must survive sessions without trusting a local approved flag."""

from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from harness_test_support import TemporaryRootTestCase
from test_component_graph import example_graph


class GraphWorkflowTests(TemporaryRootTestCase):
    def workflow(self):
        self.assertIsNotNone(importlib.util.find_spec("kernel.graph_workflow"), "workflow missing")
        from kernel import graph_workflow
        return graph_workflow

    def test_duplicate_proposal_is_one_persistent_decision(self) -> None:
        flow = self.workflow()
        candidate = example_graph()
        first = flow.propose(self.root, candidate, "classify pricing", "task1")
        second = flow.propose(self.root, candidate, "same change", "task2")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(flow.pending(self.root)), 1)
        self.assertEqual(second["rationale"], "classify pricing")

    def test_local_approved_flag_cannot_authorize_apply(self) -> None:
        flow = self.workflow()
        proposal = flow.propose(self.root, example_graph(), "new", "task")
        path = self.root / "docs/architecture/proposals" / (proposal["id"] + ".json")
        proposal["state"] = "approved"
        proposal["decision_ref"] = "invented"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "decision"):
            flow.apply(self.root, proposal["id"])
        self.assertFalse((self.root / "docs/architecture/components.json").exists())

    def test_different_candidate_has_different_identity(self) -> None:
        flow = self.workflow()
        first = flow.propose(self.root, example_graph(), "new", "task")
        second = flow.propose(self.root, dict(example_graph(), revision=2), "changed", "task")
        self.assertNotEqual(first["id"], second["id"])

    def test_notification_unavailable_is_not_delivered(self) -> None:
        flow = self.workflow()
        proposal = flow.propose(self.root, example_graph(), "new", "task")
        flow.notify(self.root, proposal["id"])
        stored = flow.pending(self.root)[0]
        self.assertEqual(stored["notification"], "queued")
        self.assertEqual(stored["state"], "awaiting_user")

    def test_pending_read_does_not_write(self) -> None:
        flow = self.workflow()
        self.assertEqual(flow.pending(self.root), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_actual_response_applies_exact_graph_without_host(self) -> None:
        flow = self.workflow()
        graph = example_graph()
        proposal = flow.propose(self.root, graph, "orders classification", "task")
        flow.decide(self.root, proposal["id"], "approve", "이 분류로 진행해", "conversation:turn-2")
        flow.apply(self.root, proposal["id"])
        self.assertEqual(flow.check_approval(self.root, graph), [])
        self.assertEqual(flow.pending(self.root), [])
        graph["revision"] += 1
        self.assertTrue(flow.check_approval(self.root, graph))

    def test_approval_survives_moving_the_checkout(self) -> None:
        """A recorded user decision is about graph content, not where the clone lives."""
        import shutil
        import tempfile
        from pathlib import Path
        flow = self.workflow()
        graph = example_graph()
        proposal = flow.propose(self.root, graph, "orders classification", "task")
        flow.decide(self.root, proposal["id"], "approve", "이 분류로 진행해", "conversation:turn-2")
        flow.apply(self.root, proposal["id"])
        stored = (self.root / "docs/architecture/proposals" / (proposal["id"] + ".json")).read_text(encoding="utf-8")
        self.assertNotIn(json.dumps(str(self.root.resolve()))[1:-1], stored, "absolute checkout path persisted")
        with tempfile.TemporaryDirectory() as other:
            moved = Path(other) / "moved clone"
            shutil.copytree(self.root, moved)
            self.assertEqual(flow.check_approval(moved, graph), [])
            self.assertIn("docs/architecture/proposals/", flow.notify(moved, proposal["id"])["proposal"])

    def test_concurrent_graph_change_rejects_stale_approval(self) -> None:
        flow = self.workflow()
        proposal = flow.propose(self.root, example_graph(), "orders", "task")
        flow.decide(self.root, proposal["id"], "approve", "승인", "conversation:turn-2")
        target = self.root / "docs/architecture/components.json"
        target.write_text(json.dumps(dict(example_graph(), revision=2)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            flow.apply(self.root, proposal["id"])

    def test_rejected_change_cannot_apply_or_notify_as_new(self) -> None:
        flow = self.workflow()
        proposal = flow.propose(self.root, example_graph(), "orders", "task")
        flow.decide(self.root, proposal["id"], "reject", "이 분류는 아니야", "conversation:turn-2")
        self.assertEqual(flow.pending(self.root), [])
        self.assertEqual(flow.propose(self.root, example_graph(), "again", "task")["state"], "rejected")
        with self.assertRaises(ValueError):
            flow.apply(self.root, proposal["id"])

    def test_mutated_proposal_cannot_reuse_approval(self) -> None:
        flow = self.workflow()
        proposal = flow.propose(self.root, example_graph(), "orders", "task")
        flow.decide(self.root, proposal["id"], "approve", "승인", "conversation:turn-2")
        path = self.root / "docs/architecture/proposals" / (proposal["id"] + ".json")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["candidate"]["revision"] += 1
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            flow.apply(self.root, proposal["id"])

    def test_interrupted_receipt_write_can_finish_without_new_approval(self) -> None:
        flow = self.workflow()
        graph = example_graph()
        proposal = flow.propose(self.root, graph, "orders", "task")
        flow.decide(self.root, proposal["id"], "approve", "approved", "test:user-2")
        original = flow._write
        with patch.object(flow, "_write", side_effect=[None, OSError("disk unavailable")]):
            with self.assertRaises(OSError):
                flow.apply(self.root, proposal["id"])
        original(self.root / "docs/architecture/components.json", graph)
        flow.apply(self.root, proposal["id"])
        self.assertEqual(flow.check_approval(self.root, graph), [])


if __name__ == "__main__":
    unittest.main()
