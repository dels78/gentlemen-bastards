#!/usr/bin/env python3
"""Tests for bots/validate.py instruction-tool and planner decision-lookup checks."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOTS_DIR = REPO_ROOT / "bots"
DATA_DIR = REPO_ROOT / "generator" / "data"
DIST_DIR = REPO_ROOT / "dist"

_spec = importlib.util.spec_from_file_location("gb_validate", BOTS_DIR / "validate.py")
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(validate)


def _role_data() -> dict:
    return json.loads((DATA_DIR / "role-configs.json").read_text(encoding="utf-8"))


class InstructionToolValidationTest(unittest.TestCase):
    def test_stale_mbrain_reference_is_violation(self) -> None:
        profile = json.loads((BOTS_DIR / "planner" / "profile.json").read_text(encoding="utf-8"))
        stale, unknown = validate.collect_instruction_tool_violations(
            "planner",
            profile,
            "Load rules via `mbrain.brain.read` before judging.",
            _role_data(),
            DIST_DIR,
        )
        self.assertEqual(stale, ["mbrain.brain.read"])
        self.assertEqual(unknown, [])

    def test_unknown_tool_is_violation(self) -> None:
        profile = json.loads((BOTS_DIR / "planner" / "profile.json").read_text(encoding="utf-8"))
        stale, unknown = validate.collect_instruction_tool_violations(
            "planner",
            profile,
            "Call `brain_hallucinate` on each item.",
            _role_data(),
            DIST_DIR,
        )
        self.assertEqual(stale, [])
        self.assertEqual(unknown, ["brain_hallucinate"])

    def test_planner_instructions_pass_collector(self) -> None:
        profile = json.loads((BOTS_DIR / "planner" / "profile.json").read_text(encoding="utf-8"))
        text = (BOTS_DIR / "planner" / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        stale, unknown = validate.collect_instruction_tool_violations(
            "planner", profile, text, _role_data(), DIST_DIR
        )
        self.assertEqual(stale, [])
        self.assertEqual(unknown, [])

    def test_planner_decision_lookup_markers_required(self) -> None:
        self.assertTrue(validate.check_planner_decision_lookup()[0])
        self.assertFalse(validate.check_planner_decision_lookup("no decision lookup here")[0])

    def test_planner_system_prompt_carries_decision_lookup(self) -> None:
        self.assertTrue(validate.check_planner_decision_lookup_in_dist(DIST_DIR)[0])


class LoadProfilesBotDirTest(unittest.TestCase):
    def test_unexpected_bot_directory_fails_set_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bots = Path(tmp) / "bots"
            bots.mkdir()
            for name in validate.EXPECTED_BOTS:
                role = bots / name
                role.mkdir()
                shutil.copy(BOTS_DIR / name / "profile.json", role / "profile.json")
                shutil.copy(BOTS_DIR / name / "INSTRUCTIONS.md", role / "INSTRUCTIONS.md")
            (bots / "intruder").mkdir()
            (bots / "__pycache__").mkdir()
            (bots / ".hidden").mkdir()
            orig = validate.BOTS_DIR
            try:
                validate.BOTS_DIR = bots
                with contextlib.redirect_stdout(io.StringIO()):
                    _, results = validate.load_profiles()
                self.assertFalse(results[0])
            finally:
                validate.BOTS_DIR = orig


if __name__ == "__main__":
    unittest.main()