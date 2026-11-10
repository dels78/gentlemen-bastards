#!/usr/bin/env python3
"""Tests for generator/generate.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "generator" / "generate.py"
BOTS_DIR = REPO_ROOT / "bots"

FIXTURE_BEHAVIOR = """# Synthetic behavior fixture

Cross-cutting rules for generator tests only.
"""

EXPECTED_ROLES = (
    "coordinator",
    "herald",
    "librarian",
    "planner",
    "scout",
    "writer",
)

ROLE_ARTIFACTS = (
    "bundle.json",
    "system-prompt.md",
    "tools.json",
    "schedule.json",
    "budget.json",
)


def run_generate(bots: Path, behavior: Path, out: Path, check: bool = False) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(GENERATOR),
        "--bots",
        str(bots),
        "--behavior",
        str(behavior),
        "--out",
        str(out),
    ]
    if check:
        cmd.append("--check")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def tree_bytes(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


class GenerateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)
        self.behavior_path = Path(self._tmpdir) / "BEHAVIOR.md"
        self.behavior_path.write_text(FIXTURE_BEHAVIOR, encoding="utf-8")
        self.out_dir = Path(self._tmpdir) / "dist"

    def test_emits_all_roles_and_root_files(self) -> None:
        result = run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        self.assertEqual(result.returncode, 0, result.stderr)

        for role in EXPECTED_ROLES:
            role_dir = self.out_dir / role
            self.assertTrue(role_dir.is_dir(), role)
            for name in ROLE_ARTIFACTS:
                self.assertTrue((role_dir / name).is_file(), f"{role}/{name}")

        self.assertTrue((self.out_dir / "gateway-allowlists.json").is_file())
        self.assertTrue((self.out_dir / "manifest.json").is_file())

        manifest = json.loads((self.out_dir / "manifest.json").read_text())
        self.assertEqual(manifest["roles"], list(EXPECTED_ROLES))

    def test_tools_allow_matches_profile(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        for role in EXPECTED_ROLES:
            profile = json.loads((BOTS_DIR / role / "profile.json").read_text())
            tools = json.loads((self.out_dir / role / "tools.json").read_text())
            self.assertEqual(tools["allow"], profile["tools"]["allow"])

    def test_planner_has_no_gmail_linear_whatsapp(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        tools = json.loads((self.out_dir / "planner" / "tools.json").read_text())
        for entry in tools["allow"]:
            self.assertFalse(
                entry.startswith("gmail.")
                or entry.startswith("linear.")
                or entry.startswith("whatsapp."),
                entry,
            )

    def test_herald_holds_no_non_artifact_tools(self) -> None:
        # M2/M5: Herald delivers via Muse — no direct send surface in v1
        # (whatsapp.send removed from Herald's allowlist).
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        tools = json.loads((self.out_dir / "herald" / "tools.json").read_text())
        non_artifacts = [t for t in tools["allow"] if t != "artifacts.read"]
        self.assertEqual(non_artifacts, [])

    def test_librarian_non_artifacts_allow_mbrain_prefix(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        tools = json.loads((self.out_dir / "librarian" / "tools.json").read_text())
        non_artifacts = [t for t in tools["allow"] if not t.startswith("artifacts.")]
        # GB-02 librarian includes linear read tools for backlog dedupe (see INSTRUCTIONS).
        for entry in non_artifacts:
            self.assertTrue(
                entry.startswith("mbrain.") or entry.startswith("linear."),
                entry,
            )

    def test_writer_read_back_only_and_gateway(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        tools = json.loads((self.out_dir / "writer" / "tools.json").read_text())
        self.assertIn("gmail.read_email", tools["read_back_only"])
        self.assertIn("linear.get_issue", tools["read_back_only"])

        gateway = json.loads((self.out_dir / "gateway-allowlists.json").read_text())
        self.assertIn("read_back_only", gateway["writer"])
        self.assertEqual(
            gateway["writer"]["read_back_only"],
            tools["read_back_only"],
        )
        for role in EXPECTED_ROLES:
            if role != "writer":
                self.assertNotIn("read_back_only", gateway[role])

    def test_system_prompt_order(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        for role in EXPECTED_ROLES:
            prompt = (self.out_dir / role / "system-prompt.md").read_text()
            instructions = (BOTS_DIR / role / "INSTRUCTIONS.md").read_text()
            beh_idx = prompt.index(FIXTURE_BEHAVIOR.strip())
            inst_idx = prompt.index(instructions.strip())
            self.assertLess(beh_idx, inst_idx)

    def test_determinism_two_runs(self) -> None:
        out_a = Path(self._tmpdir) / "dist_a"
        out_b = Path(self._tmpdir) / "dist_b"
        self.assertEqual(run_generate(BOTS_DIR, self.behavior_path, out_a).returncode, 0)
        self.assertEqual(run_generate(BOTS_DIR, self.behavior_path, out_b).returncode, 0)
        self.assertEqual(tree_bytes(out_a), tree_bytes(out_b))


if __name__ == "__main__":
    unittest.main()
