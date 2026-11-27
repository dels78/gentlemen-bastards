#!/usr/bin/env python3
"""Payload contract tests traced to dels78/personal-mcp src/tools/artifacts.py."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "personal_mcp_perso816_payloads.json"


def load_fixtures() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


class PersonalMcpListArtifactsBehaviorTest(unittest.TestCase):
    """Mirrors ArtifactStore.list_artifacts filter order (type, unprocessed_for, then limit)."""

    def test_filters_before_limit_like_personal_mcp(self) -> None:
        """personal-mcp builds `results` with all filters, then `results[:limit]`."""
        index = [
            {"id": "p1", "type": "plan", "created_at": "2026-01-01T00:00:00Z", "producer": "planner"},
            {"id": "p2", "type": "plan", "created_at": "2026-01-02T00:00:00Z", "producer": "planner"},
            {"id": "q1", "type": "question", "created_at": "2026-01-03T00:00:00Z", "producer": "writer"},
        ]
        processed_by: dict[str, set[str]] = {}
        limit = 1
        artifact_type = "question"
        unprocessed_for = "coordinator"

        results: list[dict] = []
        for entry in index:
            if artifact_type and entry.get("type") != artifact_type:
                continue
            roles_done = processed_by.get(str(entry["id"]), set())
            if unprocessed_for and unprocessed_for in roles_done:
                continue
            results.append(entry)

        sliced = results[:limit]
        self.assertEqual(len(sliced), 1)
        self.assertEqual(sliced[0]["type"], "question")
        self.assertEqual(sliced[0]["id"], "q1")
        # A naive limit-first on 500 plans would have omitted q1 entirely.


class PersonalMcpFixtureShapeTest(unittest.TestCase):
    def test_fixture_traces_to_personal_mcp_source(self) -> None:
        data = load_fixtures()
        self.assertEqual(data["source_repo"], "dels78/personal-mcp")
        self.assertIn("list_artifacts", data["source_functions"][0])
        arts = data["artifacts_list_response"]["artifacts"][0]
        for key in ("id", "type", "created_at", "producer", "processed_by"):
            self.assertIn(key, arts)
        run = data["runs_list_response"]["runs"][0]
        for key in ("run_id", "role", "status", "started_at", "finished_at"):
            self.assertIn(key, run)

    def test_loop_health_parses_fixture_payloads(self) -> None:
        import importlib.util
        import sys

        repo = Path(__file__).resolve().parent.parent
        gate_path = repo / "dist/herald/scripts/gate.py"
        spec = importlib.util.spec_from_file_location("perso816_contract_gate", gate_path)
        assert spec and spec.loader
        gate = importlib.util.module_from_spec(spec)
        sys.modules["gate"] = gate
        spec.loader.exec_module(gate)

        health_path = repo / "dist/herald/scripts/loop_health.py"
        spec2 = importlib.util.spec_from_file_location("perso816_contract_health", health_path)
        assert spec2 and spec2.loader
        health = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(health)

        data = load_fixtures()
        question = data["artifacts_list_response"]["artifacts"][0]
        run = data["runs_list_response"]["runs"][0]
        run_finish = datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00"))
        question_create = datetime.fromisoformat(question["created_at"].replace("Z", "+00:00"))
        self.assertGreater(run_finish, question_create)

        items = gate.extract_items({"structuredContent": data["artifacts_list_response"]})
        self.assertEqual(len(items), 1)
        runs = health.extract_runs({"structuredContent": data["runs_list_response"]})
        self.assertEqual(runs[0]["role"], "coordinator")
        finished = health.latest_coordinator_finished_at(runs)
        self.assertIsNotNone(finished)
        oldest = health.oldest_question_created_at(items)
        now = run_finish + timedelta(minutes=5)
        self.assertFalse(
            health.coordinator_stale(len(items), finished, oldest, now),
            "fixture run completed after question",
        )


if __name__ == "__main__":
    unittest.main()