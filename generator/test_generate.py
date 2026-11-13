#!/usr/bin/env python3
"""Tests for generator/generate.py."""

from __future__ import annotations

import copy
import importlib.util
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
DATA_DIR = REPO_ROOT / "generator" / "data"

# bots/validate.py asserts bots/ holds only the six role dirs, so importing it
# must not drop a __pycache__ there.
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gb_validate", BOTS_DIR / "validate.py")
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)

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


WRITER_CONSTRUCTION_SERVED = [
    "linear_get_issue",
    "linear_list_issues",
    "linear_list_comments",
    "linear_list_issue_statuses",
    "gmail_get_message",
    "gmail_get_thread",
    "gmail_search_threads",
    "gmail_list_labels",
    "gmail_list_drafts",
    "gmail_get_draft",
    "google-calendar_list_events",
    "google-calendar_get_event",
    "google-calendar_list_calendars",
    "google-calendar_search_events",
    "google-calendar_suggest_time",
]


def run_generate(
    bots: Path,
    behavior: Path,
    out: Path,
    check: bool = False,
    data: Path | None = None,
) -> subprocess.CompletedProcess:
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
    if data is not None:
        cmd += ["--data", str(data)]
    if check:
        cmd.append("--check")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def load_config(out: Path, role: str) -> dict:
    return validate.parse_config_yaml((out / role / "config.yaml").read_text())


def check_map(results: list[tuple[str, bool, str]]) -> dict[str, bool]:
    """Index validate_role_config results by D8 tag (or full name if untagged)."""
    out: dict[str, bool] = {}
    for name, ok, _ in results:
        tag = name.split(": ", 1)[1]
        key = tag.split("]", 1)[0] + "]" if tag.startswith("[") else tag
        out[key] = ok
    return out


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
        non_artifacts = [t for t in tools["allow"] if not t.startswith("artifacts.")]
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

    def test_config_yaml_only_for_role_config_roles(self) -> None:
        # Every role in role-configs.json gets a config.yaml: portal roles
        # (writer, librarian) and personal-mcp-only roles (planner, herald,
        # coordinator). Scout's is hand-authored in committed dist/ and is
        # NOT generated, so a fresh render has none for scout.
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        for role in EXPECTED_ROLES:
            has = (self.out_dir / role / "config.yaml").is_file()
            self.assertEqual(
                has,
                role in ("writer", "librarian", "planner", "herald", "coordinator"),
                role,
            )

    def test_rendered_includes_exact(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        writer = load_config(self.out_dir, "writer")
        self.assertEqual(
            writer["mcp_servers"]["writer-portal"]["tools"]["include"],
            WRITER_CONSTRUCTION_SERVED,
        )
        writer_pm = writer["mcp_servers"]["personal-mcp"]["tools"]["include"]
        # 728-D D5 step 3 SHADOW withholding: gmail_send + gmail_delete are
        # excluded (server-side scope and include move together); 16 remain.
        self.assertEqual(len(writer_pm), 16)
        self.assertNotIn("gmail_send", writer_pm)
        self.assertNotIn("gmail_delete", writer_pm)
        self.assertEqual(
            writer_pm[:8],
            [
                "gmail_archive", "gmail_archive_batch", "gmail_mark_read",
                "gmail_mark_unread", "gmail_request_delete", "gmail_label",
                "gmail_remove_label", "gmail_request_send",
            ],
        )
        librarian = load_config(self.out_dir, "librarian")
        self.assertEqual(
            librarian["mcp_servers"]["librarian-portal"]["tools"]["include"],
            ["linear_list_issues", "linear_get_issue"],
        )
        pm = librarian["mcp_servers"]["personal-mcp"]["tools"]["include"]
        self.assertEqual(len(pm), 14)
        self.assertIn("brain_apply_gated", pm)
        self.assertEqual(librarian["model"]["default"], "claude-sonnet-5-5")

        # Personal-mcp-only roles (728-D renders): single server, exact scopes.
        planner = load_config(self.out_dir, "planner")
        self.assertEqual(set(planner["mcp_servers"]), {"personal-mcp"})
        self.assertEqual(
            planner["mcp_servers"]["personal-mcp"]["tools"]["include"],
            [
                "artifacts_write", "artifacts_read", "artifacts_list",
                "artifacts_mark_processed", "runs_begin", "runs_finish",
                "runs_get", "runs_list", "brain_status", "brain_scan",
                "brain_get", "brain_search", "brain_traverse", "engine_plan",
            ],
        )
        self.assertEqual(planner["model"]["default"], "claude-sonnet-5-5")
        self.assertEqual(planner["model"]["context_length"], 1000000)
        for role in ("herald", "coordinator"):
            cfg = load_config(self.out_dir, role)
            self.assertEqual(set(cfg["mcp_servers"]), {"personal-mcp"}, role)
            self.assertEqual(
                cfg["mcp_servers"]["personal-mcp"]["tools"]["include"],
                [
                    "artifacts_write", "artifacts_read", "artifacts_list",
                    "artifacts_mark_processed", "runs_begin", "runs_finish",
                    "runs_get", "runs_list",
                ],
                role,
            )
            self.assertEqual(cfg["model"]["default"], "claude-haiku-5-5", role)

    def test_gate_scripts_rendered_and_fail_closed(self) -> None:
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        expected_kinds = {
            "coordinator": ("question", "consult-request", "consult-response"),
            "planner": ("snapshot", "consult-request", "consult-response", "report"),
            "writer": ("plan", "consult-request", "consult-response", "report"),
            "herald": ("receipt", "report", "consult-response"),
            "librarian": ("snapshot", "receipt", "brain-proposal", "consult-request", "consult-response", "report"),
        }
        for role, kinds in expected_kinds.items():
            gate = self.out_dir / role / "scripts" / "gate.py"
            self.assertTrue(gate.is_file(), role)
            text = gate.read_text()
            compile(text, str(gate), "exec")
            for kind in kinds:
                self.assertIn(f'"{kind}"', text, f"{role}: {kind}")
        self.assertFalse((self.out_dir / "scout" / "scripts" / "gate.py").exists())
        # Fail-closed: with no .env in the profile home the gate exits
        # non-zero and prints no wakeAgent line (Hermes wakes — safe).
        home = Path(self._tmpdir) / "planner"
        scripts = home / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(self.out_dir / "planner" / "scripts" / "gate.py", scripts / "gate.py")
        result = subprocess.run(
            [sys.executable, str(scripts / "gate.py")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("wakeAgent", result.stdout)

    def test_renders_match_committed_dist(self) -> None:
        # Full --check is blocked by pre-existing system-prompt/manifest drift
        # from PR #16; pin the files this generator change owns byte-for-byte.
        run_generate(BOTS_DIR, self.behavior_path, self.out_dir)
        for rel in (
            "writer/config.yaml", "librarian/config.yaml", "writer/tools.json",
            "planner/config.yaml", "herald/config.yaml", "coordinator/config.yaml",
            "coordinator/scripts/gate.py", "planner/scripts/gate.py",
            "writer/scripts/gate.py", "herald/scripts/gate.py",
            "librarian/scripts/gate.py",
        ):
            self.assertEqual(
                (self.out_dir / rel).read_bytes(),
                (REPO_ROOT / "dist" / rel).read_bytes(),
                rel,
            )

    def test_w1_phase_is_data_only(self) -> None:
        data = self._data_copy()
        cfg = json.loads((data / "role-configs.json").read_text())
        cfg["roles"]["writer"]["portal"]["active_phases"] = ["construction", "W1"]
        (data / "role-configs.json").write_text(json.dumps(cfg))
        result = run_generate(BOTS_DIR, self.behavior_path, self.out_dir, data=data)
        self.assertEqual(result.returncode, 0, result.stderr)
        tools = json.loads((self.out_dir / "writer" / "tools.json").read_text())
        self.assertEqual(
            tools["portal"]["write_capable"], ["linear_save_issue", "linear_save_comment"]
        )
        # Validator still refuses it until the portal read-back records the flip.
        results = self._validate(self.out_dir, data, "writer")
        self.assertFalse(results["[D8-1]"])
        self.assertTrue(results["[D8-3]"])

    def test_unmapped_phase_refused_by_generator(self) -> None:
        # W2 portal Gmail writes have no D7 rows (§5 item 1) -> gate (ii) closed.
        data = self._data_copy()
        cfg = json.loads((data / "role-configs.json").read_text())
        cfg["roles"]["writer"]["portal"]["active_phases"] = ["construction", "W2"]
        (data / "role-configs.json").write_text(json.dumps(cfg))
        result = run_generate(BOTS_DIR, self.behavior_path, self.out_dir, data=data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no contract-mapping row", result.stderr)

    def _data_copy(self) -> Path:
        data = Path(self._tmpdir) / "data"
        shutil.copytree(DATA_DIR, data)
        return data

    def _validate(self, dist: Path, data: Path, role: str) -> dict[str, bool]:
        role_data = json.loads((data / "role-configs.json").read_text())
        mapping = json.loads((data / "contract-mapping.json").read_text())
        role_cfg = role_data["roles"][role]
        readback = json.loads((data / role_cfg["portal"]["readback"]).read_text())
        config = validate.parse_config_yaml((dist / role / "config.yaml").read_text())
        tools_json = json.loads((dist / role / "tools.json").read_text())
        return check_map(validate.validate_role_config(
            role, config, role_cfg, role_data["personal_mcp"], mapping, readback, tools_json
        ))

    def test_determinism_two_runs(self) -> None:
        out_a = Path(self._tmpdir) / "dist_a"
        out_b = Path(self._tmpdir) / "dist_b"
        self.assertEqual(run_generate(BOTS_DIR, self.behavior_path, out_a).returncode, 0)
        self.assertEqual(run_generate(BOTS_DIR, self.behavior_path, out_b).returncode, 0)
        self.assertEqual(tree_bytes(out_a), tree_bytes(out_b))


class ValidateRoleConfigTest(unittest.TestCase):
    """728-E/F D8 validator checks against the committed renders, incl. negatives."""

    def setUp(self) -> None:
        self.role_data = json.loads((DATA_DIR / "role-configs.json").read_text())
        self.mapping = json.loads((DATA_DIR / "contract-mapping.json").read_text())

    def _inputs(self, role: str) -> dict:
        role_cfg = self.role_data["roles"][role]
        return {
            "role": role,
            "config": load_config(REPO_ROOT / "dist", role),
            "role_cfg": role_cfg,
            "personal_mcp": self.role_data["personal_mcp"],
            "mapping": self.mapping,
            "readback": (
                json.loads((DATA_DIR / role_cfg["portal"]["readback"]).read_text())
                if "portal" in role_cfg else None
            ),
            "tools_json": json.loads((REPO_ROOT / "dist" / role / "tools.json").read_text()),
        }

    def _run(self, inputs: dict) -> dict[str, bool]:
        return check_map(validate.validate_role_config(**inputs))

    def _portal_include(self, inputs: dict) -> list:
        entry = inputs["role_cfg"]["portal"]["entry"]
        return inputs["config"]["mcp_servers"][entry]["tools"]["include"]

    def test_committed_renders_pass(self) -> None:
        for role in ("writer", "librarian", "planner", "herald", "coordinator"):
            results = self._run(self._inputs(role))
            self.assertTrue(all(results.values()), (role, results))

    def test_validate_script_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(BOTS_DIR / "validate.py")],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_w1_name_in_construction_render_fails(self) -> None:
        for name in ("linear_save_issue", "save_comment"):
            inputs = self._inputs("writer")
            self._portal_include(inputs).append(name)
            results = self._run(inputs)
            self.assertFalse(results["[D8-3]"], name)

    def test_w2_w3_and_unmapped_names_fail(self) -> None:
        for name in ("gmail_label_thread", "create_draft", "google-calendar_create_event",
                     "linear_save_document", "gmail_send_message"):
            inputs = self._inputs("writer")
            self._portal_include(inputs).append(name)
            self.assertFalse(self._run(inputs)["[D8-3]"], name)

    def test_dotted_name_fails(self) -> None:
        for server in ("personal-mcp", "writer-portal"):
            inputs = self._inputs("writer")
            inputs["config"]["mcp_servers"][server]["tools"]["include"].append("linear.issue.create")
            self.assertFalse(self._run(inputs)["[D8-2]"], server)

    def test_name_not_in_readback_fails(self) -> None:
        inputs = self._inputs("librarian")
        self._portal_include(inputs).append("linear_whoami")
        self.assertFalse(self._run(inputs)["[D8-1]"])
        inputs = self._inputs("writer")
        self._portal_include(inputs)[0] = "get_issue"  # unprefixed catalog name
        self.assertFalse(self._run(inputs)["[D8-1]"])

    def test_read_back_only_must_survive(self) -> None:
        inputs = self._inputs("writer")
        tp = inputs["tools_json"]["portal"]
        tp["write_capable"] = list(tp["read_back_only"])
        self.assertFalse(self._run(inputs)["[D8-4]"])
        inputs = self._inputs("writer")
        inputs["tools_json"]["portal"]["read_back_only"] = ["linear_get_issue"]
        self.assertFalse(self._run(inputs)["[D8-4]"])

    def test_portal_url_must_match_live(self) -> None:
        for bad in ("https://scout.delisle.me/mcp", "https://writer.delisle.me/",
                    "https://writer.delisle.me/mcp/"):
            inputs = self._inputs("writer")
            inputs["config"]["mcp_servers"]["writer-portal"]["url"] = bad
            self.assertFalse(self._run(inputs)["[D8-5]"], bad)

    def test_headers_must_be_own_role_refs(self) -> None:
        name = "headers are own-role ${VAR} refs only"
        for key, val in (
            ("CF-Access-Client-Secret", "literal-secret-value"),
            ("CF-Access-Client-Id", "${CF_ACCESS_CLIENT_ID_SCOUT}"),
        ):
            inputs = self._inputs("writer")
            inputs["config"]["mcp_servers"]["writer-portal"]["headers"][key] = val
            self.assertFalse(self._run(inputs)[name], val)

    def test_inputs_not_mutated_across_cases(self) -> None:
        a = self._inputs("writer")
        b = copy.deepcopy(a)
        self._run(a)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
