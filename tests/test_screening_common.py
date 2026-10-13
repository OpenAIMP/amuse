import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from screening_common import (evaluation_record, qualification_counts,
                              rank_qualified, sort_evaluations)


class TestSharedScreeningContract(unittest.TestCase):
    def test_statuses_distinguish_rejection_from_missing_data_and_errors(self):
        rows = [
            evaluation_record({"symbol": "A"}),
            evaluation_record({"symbol": "B"}, ["price too low"]),
            evaluation_record({"symbol": "C"}, ["no intraday bars"]),
            evaluation_record({"symbol": "D"}, error="MCP error: unavailable"),
        ]
        self.assertEqual([r["qualification_status"] for r in rows],
                         ["qualified", "rejected", "incomplete_data", "error"])
        self.assertEqual(qualification_counts(rows), {
            "qualified": 1, "rejected": 1, "incomplete_data": 1, "error": 1})

    def test_rank_and_selection_are_deterministic(self):
        rows = [
            {"symbol": "B", "qualification_status": "qualified", "score": 4},
            {"symbol": "A", "qualification_status": "qualified", "score": 4},
            {"symbol": "C", "qualification_status": "rejected", "score": 99},
        ]
        selected = rank_qualified(rows, rows[:2], limit=1, score_key="score")
        self.assertEqual([r["symbol"] for r in selected], ["A"])
        self.assertTrue(rows[1]["selected"])
        self.assertEqual(rows[1]["candidate_rank"], 1)
        self.assertFalse(rows[0]["selected"])
        self.assertIsNone(rows[2]["candidate_rank"])
        self.assertEqual([r["symbol"] for r in sort_evaluations(rows, "score")],
                         ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
