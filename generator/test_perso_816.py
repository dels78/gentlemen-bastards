#!/usr/bin/env python3
"""PERSO-816: integration tests for rendered gate.py and loop_health.py."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent

_validate_spec = importlib.util.spec_from_file_location(
    "gb_validate_perso816", REPO_ROOT / "bots" / "validate.py"
)
assert _validate_spec and _validate_spec.loader
_validate = importlib.util.module_from_spec(_validate_spec)
_validate_spec.loader.exec_module(_validate)
parse_config_yaml = _validate.parse_config_yaml


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
        self.calls: list[tuple[str, dict]] = []

    def initialize(self) -> None:
        return None

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        return self.handler(name, arguments)


class FixedDateTime(datetime):
    """Patch target: freeze datetime.now for loop_health staleness tests."""

    fixed: datetime = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def run_loop_health(handler) -> dict:
    health = LoopHealthScriptTest.health
    with (
        patch.object(health, "McpClient", lambda token: FakeMcpClient(token, handler)),
        patch.object(health, "load_token", return_value="herald-test-token"),
        patch.object(health, "datetime", FixedDateTime),
        redirect_stdout(io.StringIO()) as out,
    ):
        health.main()
    return json.loads(out.getvalue().strip())


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

    def test_wakes_despite_unrelated_types_starving_a_bulk_query(self) -> None:
        """Per-type limit=1 cannot be starved by hundreds of plan rows."""
        plan_ids = [f"plan-{i}" for i in range(600)]

        def handler(name: str, arguments: dict) -> dict:
            if name != "artifacts_list":
                raise AssertionError(name)
            if arguments.get("type") == "question":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q-only"}],
                    }
                }
            if arguments.get("type") == "plan":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "plan", "id": plan_ids[0]}],
                    }
                }
            return {"structuredContent": {"artifacts": []}}

        with (
            patch.object(self.gate, "McpClient", lambda token: FakeMcpClient(token, handler)),
            patch.object(self.gate, "load_token", return_value="token"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(self.gate.main(), 0)
        self.assertTrue(json.loads(out.getvalue().strip())["wakeAgent"])

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
    health = None  # set in setUpClass

    @classmethod
    def setUpClass(cls) -> None:
        gate_path = REPO_ROOT / "dist/herald/scripts/gate.py"
        sys.modules["gate"] = load_module(gate_path, "perso816_herald_gate")
        cls.health = load_module(
            REPO_ROOT / "dist/herald/scripts/loop_health.py",
            "perso816_loop_health",
        )
        LoopHealthScriptTest.health = cls.health

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

    def test_boundary_59_minute_question_stays_ok(self) -> None:
        FixedDateTime.fixed = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
        created = (FixedDateTime.fixed - timedelta(minutes=59)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q1", "created_at": created}],
                    }
                }
            if name == "runs_list":
                return {"structuredContent": {"runs": []}}
            raise AssertionError(name)

        self.assertEqual(run_loop_health(handler)["status"], "ok")

    def test_boundary_60_minute_question_stays_ok(self) -> None:
        FixedDateTime.fixed = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
        created = (FixedDateTime.fixed - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q1", "created_at": created}],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "completed",
                                "finished_at": "2026-11-27T15:00:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        self.assertEqual(run_loop_health(handler)["status"], "ok")

    def test_boundary_61_minute_question_degraded(self) -> None:
        FixedDateTime.fixed = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
        created = (FixedDateTime.fixed - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q1", "created_at": created}],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "completed",
                                "finished_at": "2026-11-27T18:30:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        body = run_loop_health(handler)
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["alerts"][0]["code"], "coordinator_stale")

    def test_boundary_61_minute_failed_finish_does_not_clear_stale(self) -> None:
        FixedDateTime.fixed = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
        created = (FixedDateTime.fixed - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {
                    "structuredContent": {
                        "artifacts": [{"type": "question", "id": "q1", "created_at": created}],
                    }
                }
            if name == "runs_list":
                return {
                    "structuredContent": {
                        "runs": [
                            {
                                "role": "coordinator",
                                "status": "failed",
                                "finished_at": "2026-11-27T19:58:00Z",
                            }
                        ],
                    }
                }
            raise AssertionError(name)

        self.assertEqual(run_loop_health(handler)["status"], "degraded")


class HeraldLoopHealthProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if "gate" not in sys.modules or not hasattr(sys.modules["gate"], "PERSONAL_MCP_URL"):
            gate_path = REPO_ROOT / "dist/herald/scripts/gate.py"
            sys.modules["gate"] = load_module(gate_path, "perso816_herald_gate_profile")
        if LoopHealthScriptTest.health is None:
            LoopHealthScriptTest.setUpClass()

    def test_rendered_herald_config_exposes_loop_health_tools(self) -> None:
        cfg = parse_config_yaml(
            (REPO_ROOT / "dist/herald/config.yaml").read_text(encoding="utf-8")
        )
        inc = cfg["mcp_servers"]["personal-mcp"]["tools"]["include"]
        self.assertIn("artifacts_list", inc)
        self.assertIn("runs_list", inc)
        url = cfg["mcp_servers"]["personal-mcp"]["url"]
        auth = cfg["mcp_servers"]["personal-mcp"]["headers"]["Authorization"]
        self.assertIn("personal-mcp.personal-mcp.svc.cluster.local", url)
        self.assertEqual(auth, "Bearer ${MCP_SERVICE_TOKEN_HERALD}")

    def test_loop_health_uses_herald_gate_mcp_client_and_expected_calls(self) -> None:
        health = LoopHealthScriptTest.health
        gate = sys.modules["gate"]

        def handler(name: str, arguments: dict) -> dict:
            if name == "artifacts_list":
                return {"structuredContent": {"artifacts": []}}
            if name == "runs_list":
                return {"structuredContent": {"runs": []}}
            raise AssertionError(name)

        client_holder: list[FakeMcpClient] = []

        def make_client(token: str) -> FakeMcpClient:
            client = FakeMcpClient(token, handler)
            client_holder.append(client)
            return client

        health.__file__ = str(REPO_ROOT / "dist/herald/scripts/loop_health.py")
        FixedDateTime.fixed = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
        with (
            patch.object(health, "McpClient", make_client),
            patch.object(health, "load_token", return_value="herald-test-token"),
            patch.object(health, "datetime", FixedDateTime),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(health.main(), 0)

        self.assertEqual(len(client_holder), 1)
        client = client_holder[0]
        self.assertEqual(
            client.calls,
            [
                ("artifacts_list", {"type": "question", "unprocessed_for": "coordinator", "limit": 500}),
                ("runs_list", {"role": "coordinator", "limit": 100}),
            ],
        )
        self.assertEqual(gate.PERSONAL_MCP_URL, "http://personal-mcp.personal-mcp.svc.cluster.local:80/mcp")


if __name__ == "__main__":
    unittest.main()
