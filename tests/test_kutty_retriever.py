"""
Tests for Kutty retriever status-filter logic (pure functions — no index/LLM).

Run:  python -m unittest tests.test_kutty_retriever
"""
import unittest

from training.kutty.retriever import (
    _group_for,
    _infer_status_filter,
    _resolve_status_filter,
    _OPEN_STATUSES,
)


class TestStatusInference(unittest.TestCase):
    def test_open_intent(self):
        self.assertEqual(_infer_status_filter("open ABAP tickets for Rayzon"), _OPEN_STATUSES)

    def test_completed_intent(self):
        self.assertEqual(_infer_status_filter("completed MM tickets"), {"completed"})

    def test_wip_intent_wins_over_open(self):
        # "in progress" is more specific than the broad open bucket.
        self.assertEqual(_infer_status_filter("work in progress stock transfer"), {"wip"})

    def test_dropped_intent(self):
        self.assertEqual(_infer_status_filter("dropped tickets"), {"drop", "send for drop"})

    def test_no_status_intent(self):
        self.assertIsNone(_infer_status_filter("show all MM tickets for stock transfer"))

    def test_word_boundary_no_false_trigger(self):
        # 'threshold' must NOT trigger the 'hold' group; 'installation' not 'still'.
        self.assertIsNone(_infer_status_filter("threshold installation report"))


class TestResolveStatusFilter(unittest.TestCase):
    def test_explicit_keyword_expands(self):
        allowed, explicit = _resolve_status_filter("open", "")
        self.assertTrue(explicit)
        self.assertEqual(allowed, _OPEN_STATUSES)

    def test_explicit_list(self):
        allowed, explicit = _resolve_status_filter(["completed", "wip"], "")
        self.assertTrue(explicit)
        self.assertEqual(allowed, {"completed", "wip"})

    def test_explicit_canonical_status_literal(self):
        allowed, explicit = _resolve_status_filter("Raised to SAP", "")
        self.assertTrue(explicit)
        self.assertEqual(allowed, {"raised to sap"})

    def test_inferred_from_query(self):
        allowed, explicit = _resolve_status_filter(None, "completed tickets")
        self.assertFalse(explicit)
        self.assertEqual(allowed, {"completed"})

    def test_none_when_no_signal(self):
        allowed, explicit = _resolve_status_filter(None, "list MM tickets")
        self.assertFalse(explicit)
        self.assertEqual(allowed, set())


if __name__ == "__main__":
    unittest.main()
