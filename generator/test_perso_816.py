#!/usr/bin/env python3
"""PERSO-816: integration tests for rendered gate.py and loop_health.py."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeMcpClient:
    def __init__(self, token: str, handler) -> None:
        self.handler = handler

    def initialize(self) -> None:
        return None

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.handler(name, arguments)


class GateScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_module(
            REPO_ROOT / "dist/coordinator/scripts/gate.py",
            "perso816_coord_gate",
        )

    def test_wakes_via_per_type_queries_when_question_exists(self) -> None:
        calls: list[dict] = []

        def handler(name: str, arguments: dict) -> dict:
            if name != "artifacts_list":
                raise AssertionError(name)
            calls.append(arguments)
            if arguments.get("type") == "question":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q1"}],
                    }
                }
            return {"structuredContent": {"artifacts": []}}

        with (
            patch.object(self.gate, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.gate, "load_token", return_value="token"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.gate.main(), 0)

        payload = json.loads(out.getvalue().strip())
        self.assertTrue(payload["wakeAgent"])
        self.assertTrue(
            all("type" in call for call in calls),
            "each artifacts_list call must pass type (per-kind wake queries)",
        )
        self.assertIn(
            {"type": "question", "unprocessed_for": "coordinator", "limit": 1},
            calls,
        )

    def test_stays_asleep_when_no_relevant_unprocessed(self) -> None:
        def handler(name: str, arguments: dict) -> dict:
            return {"structuredContent": {"artifacts": []}}

        with (
            patch.object(self.gate, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.gate, "load_token", return_value="token"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.gate.main(), 0)

        self.assertFalse(json.loads(out.getvalue().strip())["wakeAgent"])


class LoopHealthScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        gate_path = REPO_ROOT / "dist/herald/scripts/gate.py"
        load_module(gate_path, "gate")
        cls.health = load_module(
            REPO_ROOT / "dist/herald/scripts/loop_health.py",
            "perso816_loop_health",
        )

    def test_degraded_when_questions_wait_and_coordinator_stale(self) -> None:
        fixed_now = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [
                            {
                                "type": "question",
                                "id": "q1",
                                "created_at": "2026-11-27T17:00:00Z",
                            }
                        ],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "finished",
                                "finished_at": "2026-11-27T16:30:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with (
            patch.object(self.health, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.health, "load_token", return_value="token"),
            patch.object(self.health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.health.main(), 0)

        body = json.loads(out.getvalue().strip())
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["alerts"][0]["code"], "coordinator_stale")

    def test_ignores_runs_without_coordinator_role(self) -> None:
        fixed_now = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [
                            {
                                "type": "question",
                                "id": "q1",
                                "created_at": "2026-11-27T17:00:00Z",
                            }
                        ],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "finished_at": "2026-11-27T19:30:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with (
            patch.object(self.health, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.health, "load_token", return_value="token"),
            patch.object(self.health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.health.main(), 0)

        body = json.loads(out.getvalue().strip())
        self.assertEqual(body["status"], "degraded")
        self.assertIsNone(body.get("coordinator_last_finished_at"))

    def test_ok_when_coordinator_finished_after_oldest_question(self) -> None:
        fixed_now = datetime(2026, 11, 27, 19, 30, tzinfo=timezone.utc)

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [
                            {
                                "type": "question",
                                "id": "q1",
                                "created_at": "2026-11-27T18:00:00Z",
                            }
                        ],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "finished_at": "2026-11-27T19:00:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with (
            patch.object(self.health, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.health, "load_token", return_value="token"),
            patch.object(self.health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.health.main(), 0)

        self.assertEqual(json.loads(out.getvalue().strip())["status"], "ok")

    def test_ok_fresh_question_after_idle_coordinator(self) -> None:
        """1-minute-old Question must not flag stale after a long Coordinator idle."""
        fixed_now = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [
                            {
                                "type": "question",
                                "id": "q1",
                                "created_at": "2026-11-27T19:59:00Z",
                            }
                        ],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "finished",
                                "finished_at": "2026-11-27T15:00:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with (
            patch.object(self.health, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.health, "load_token", return_value="token"),
            patch.object(self.health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.health.main(), 0)

        self.assertEqual(json.loads(out.getvalue().strip())["status"], "ok")

    def test_ignores_failed_coordinator_run_for_freshness(self) -> None:
        fixed_now = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [
                            {
                                "type": "question",
                                "id": "q1",
                                "created_at": "2026-11-27T18:00:00Z",
                            }
                        ],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "failed",
                                "finished_at": "2026-11-27T19:55:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with (
            patch.object(self.health, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.health, "load_token", return_value="token"),
            patch.object(self.health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.health.main(), 0)

        self.assertEqual(json.loads(out.getvalue().strip())["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
