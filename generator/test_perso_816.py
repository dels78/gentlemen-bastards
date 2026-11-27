#!/usr/bin/env python3
"""PERSO-816: coordinator gate starvation and Herald loop health."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from gate_wake_lib import wake_from_per_type_queries, wake_from_unfiltered_window
from loop_health_lib import (
    coordinator_stale,
    latest_coordinator_finished_at,
    loop_health_payload,
    parse_instant,
)

WAKE = frozenset({"question", "consult-request", "consult-response"})


class GateStarvationTest(unittest.TestCase):
    def test_unfiltered_window_starves_behind_500_unrelated(self) -> None:
        unrelated = [
            {"type": "plan", "id": f"p{i}"} for i in range(500)
        ]
        items = unrelated + [{"type": "question", "id": "q-last"}]
        self.assertFalse(wake_from_unfiltered_window(items, WAKE))
        self.assertTrue(
            wake_from_per_type_queries(
                {
                    "question": True,
                    "consult-request": False,
                    "consult-response": False,
                },
                WAKE,
            )
        )

    def test_per_type_query_asleep_with_no_relevant_items(self) -> None:
        self.assertFalse(
            wake_from_per_type_queries(
                {
                    "question": False,
                    "consult-request": False,
                    "consult-response": False,
                },
                WAKE,
            )
        )


class HeraldLoopHealthTest(unittest.TestCase):
    def test_flags_stale_coordinator_when_questions_wait(self) -> None:
        now = parse_instant("2026-11-27T20:00:00Z")
        last = parse_instant("2026-11-27T18:00:00Z")
        self.assertTrue(
            coordinator_stale(
                unprocessed_question_count=3,
                last_coordinator_finished_at=last,
                now=now,
                stale_after_minutes=60,
            )
        )
        payload = loop_health_payload(
            unprocessed_question_count=3,
            last_coordinator_finished_at=last,
            now=now,
        )
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["alerts"][0]["code"], "coordinator_stale")

    def test_ok_when_no_questions(self) -> None:
        now = parse_instant("2026-11-27T20:00:00Z")
        payload = loop_health_payload(
            unprocessed_question_count=0,
            last_coordinator_finished_at=None,
            now=now,
        )
        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("alerts", payload)

    def test_latest_coordinator_finished_at(self) -> None:
        runs = [
            {"role": "coordinator", "finished_at": "2026-11-21T10:00:00Z"},
            {"role": "coordinator", "finished_at": "2026-11-21T19:05:00Z"},
        ]
        self.assertEqual(
            latest_coordinator_finished_at(runs),
            datetime(2026, 11, 21, 19, 5, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()