#!/usr/bin/env python3
"""Validate canonical bot definitions under bots/."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOTS_DIR = Path(__file__).resolve().parent

EXPECTED_BOTS = frozenset(
    {"scout", "planner", "writer", "herald", "librarian", "coordinator"}
)

KNOWN_ARTIFACT_TYPES = frozenset(
    {
        "snapshot",
        "plan",
        "question",
        "receipt",
        "report",
        "consult-request",
        "consult-response",
        "brain-proposal",
    }
)

MODEL_TIERS = frozenset({"cheap", "strong"})
SCHEDULE_KINDS = frozenset({"interval", "cron", "event", "manual"})

WRITE_MARKERS = (".apply", ".send", ".create", ".update")

REQUIRED_TOP_LEVEL = {
    "role": str,
    "purpose": str,
    "consumes": list,
    "produces": list,
    "tools": dict,
    "model_tier": str,
    "budget": dict,
    "schedule": dict,
    "consult": dict,
    "escalates_to": str,
}


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")
    return ok


def load_profiles() -> tuple[dict[str, dict], list[bool]]:
    results: list[bool] = []
    profiles: dict[str, dict] = {}

    bot_dirs = sorted(p for p in BOTS_DIR.iterdir() if p.is_dir())
    found_names = {p.name for p in bot_dirs}

    results.append(
        check(
            "bot directories match expected set",
            found_names == EXPECTED_BOTS,
            f"found={sorted(found_names)}",
        )
    )

    for bot in sorted(EXPECTED_BOTS):
        bot_path = BOTS_DIR / bot
        profile_path = bot_path / "profile.json"
        instructions_path = bot_path / "INSTRUCTIONS.md"

        results.append(
            check(
                f"{bot}: profile.json and INSTRUCTIONS.md present",
                profile_path.is_file() and instructions_path.is_file(),
            )
        )

        if not profile_path.is_file():
            continue

        try:
            with profile_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            results.append(check(f"{bot}: profile.json parses", False, str(exc)))
            continue

        results.append(check(f"{bot}: profile.json parses", True))

        keys = set(data.keys())
        required_keys = set(REQUIRED_TOP_LEVEL)
        exact_keys = keys == required_keys
        results.append(
            check(
                f"{bot}: profile top-level fields exact",
                exact_keys,
                f"keys={sorted(keys)}",
            )
        )

        type_ok = True
        type_detail: list[str] = []
        for field, typ in REQUIRED_TOP_LEVEL.items():
            if field not in data or not isinstance(data[field], typ):
                type_ok = False
                type_detail.append(f"{field} expected {typ.__name__}")
        results.append(
            check(
                f"{bot}: profile field types",
                type_ok,
                "; ".join(type_detail),
            )
        )

        if data.get("role") != bot:
            results.append(
                check(
                    f"{bot}: role matches directory",
                    False,
                    f"role={data.get('role')!r}",
                )
            )
        else:
            results.append(check(f"{bot}: role matches directory", True))

        consumes = data.get("consumes", [])
        produces = data.get("produces", [])
        art_ok = all(
            t in KNOWN_ARTIFACT_TYPES for t in consumes + produces
        )
        results.append(
            check(
                f"{bot}: consumes/produces known artifact types",
                art_ok,
                f"consumes={consumes}, produces={produces}",
            )
        )

        tier_ok = data.get("model_tier") in MODEL_TIERS
        results.append(check(f"{bot}: model_tier valid", tier_ok))

        budget = data.get("budget", {})
        budget_ok = (
            isinstance(budget.get("max_tokens_per_run"), int)
            and isinstance(budget.get("max_consults_per_run"), int)
            and set(budget.keys()) == {"max_tokens_per_run", "max_consults_per_run"}
        )
        results.append(check(f"{bot}: budget shape", budget_ok))

        schedule = data.get("schedule", {})
        sched_ok = (
            schedule.get("kind") in SCHEDULE_KINDS
            and isinstance(schedule.get("detail"), str)
            and set(schedule.keys()) == {"kind", "detail"}
        )
        results.append(check(f"{bot}: schedule shape", sched_ok))

        tools = data.get("tools", {})
        tools_ok = (
            isinstance(tools.get("allow"), list)
            and all(isinstance(t, str) for t in tools["allow"])
            and set(tools.keys()) == {"allow"}
        )
        results.append(check(f"{bot}: tools.allow shape", tools_ok))

        consult = data.get("consult", {})
        consult_ok = (
            isinstance(consult.get("may_consult"), list)
            and isinstance(consult.get("may_be_consulted_by"), list)
            and all(isinstance(r, str) for r in consult["may_consult"])
            and all(isinstance(r, str) for r in consult["may_be_consulted_by"])
            and set(consult.keys()) == {"may_consult", "may_be_consulted_by"}
        )
        results.append(check(f"{bot}: consult shape", consult_ok))

        esc = data.get("escalates_to")
        if bot == "coordinator":
            esc_ok = esc == "muse"
        else:
            esc_ok = esc == "coordinator"
        results.append(check(f"{bot}: escalates_to", esc_ok, f"value={esc!r}"))

        profiles[bot] = data

    return profiles, results


def check_consult_symmetry(profiles: dict[str, dict]) -> list[bool]:
    results: list[bool] = []
    ok = True
    pairs: list[str] = []
    for role, prof in profiles.items():
        for target in prof["consult"]["may_consult"]:
            reverse = profiles.get(target, {}).get("consult", {}).get(
                "may_be_consulted_by", []
            )
            if role not in reverse:
                ok = False
                pairs.append(f"{role} may_consult {target} but reverse missing")
    results.append(check("consult symmetry", ok, "; ".join(pairs)))
    return results


def check_write_tools(profiles: dict[str, dict]) -> list[bool]:
    results: list[bool] = []
    ok = True
    violations: list[str] = []
    for role, prof in profiles.items():
        for tool in prof["tools"]["allow"]:
            if not any(marker in tool for marker in WRITE_MARKERS):
                continue
            if role == "writer" and (
                tool.startswith("gmail.") or tool.startswith("linear.")
            ):
                continue
            if role == "coordinator" and tool.startswith("schedule."):
                continue
            ok = False
            violations.append(f"{role}: {tool}")
    results.append(
        check(
            "write/apply/send tools restricted to Writer (plus Coordinator schedule)",
            ok,
            "; ".join(violations),
        )
    )
    return results


def check_writer_only_external_writes(profiles: dict[str, dict]) -> list[bool]:
    results: list[bool] = []
    ok = True
    bad: list[str] = []
    for role, prof in profiles.items():
        if role == "writer":
            continue
        for tool in prof["tools"]["allow"]:
            if tool.startswith("gmail.") or tool.startswith("linear."):
                if any(m in tool for m in WRITE_MARKERS):
                    ok = False
                    bad.append(f"{role}: {tool}")
    results.append(
        check(
            "only Writer holds gmail./linear. write-capable tools",
            ok,
            "; ".join(bad),
        )
    )
    return results


# --- 728-E/F D8: rendered dist/<role>/config.yaml checks ----------------------

DATA_DIR = REPO_ROOT / "generator" / "data"
DIST_DIR = REPO_ROOT / "dist"

# Live portal endpoints from the 728-E/F Package 1/2 creation read-backs
# (2026-11-13). Pinned here independently of generator/data so a hand edit
# to either the read-back artifact or the render cannot drift silently.
LIVE_PORTAL_ENDPOINTS = {
    "writer": "https://writer.delisle.me/mcp",
    "librarian": "https://librarian.delisle.me/mcp",
}
PERSONAL_MCP_URL = "http://personal-mcp.personal-mcp.svc.cluster.local:80/mcp"
VAR_REF = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


def parse_config_yaml(text: str) -> dict:
    """Parse the YAML subset generate.py emits (block maps, scalar lists, comments).

    Stdlib-only on purpose (the repo has no third-party deps). Anything
    outside the subset raises ValueError — the validator then fails.
    """
    root: dict = {}
    # Each frame: (indent of the key that opened it, container).
    stack: list[tuple[int, object]] = [(-1, root)]
    pending: tuple[dict, str, int] | None = None  # key awaiting a nested block

    def scalar(raw: str) -> object:
        raw = raw.strip()
        if raw.startswith('"'):
            return json.loads(raw)
        if raw in ("true", "false"):
            return raw == "true"
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        return raw

    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if pending is not None:
            parent, key, key_indent = pending
            pending = None
            if indent > key_indent:
                parent[key] = [] if body.startswith("- ") else {}
                stack.append((key_indent, parent[key]))
            else:
                parent[key] = None
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        container = stack[-1][1]
        if body.startswith("- "):
            if not isinstance(container, list):
                raise ValueError(f"line {lineno}: list item outside a list")
            container.append(scalar(body[2:]))
            continue
        if ":" not in body or not isinstance(container, dict):
            raise ValueError(f"line {lineno}: unsupported syntax: {body!r}")
        key, _, rest = body.partition(":")
        if rest.strip():
            container[key.strip()] = scalar(rest)
        else:
            pending = (container, key.strip(), indent)
    if pending is not None:
        pending[0][pending[1]] = None
    return root


def _phase_names(phase: dict) -> set[str]:
    """Both spellings of every tool in a phase set: catalog and served."""
    names: set[str] = set()
    for server, tools in phase.items():
        for tool in tools:
            names.add(tool)
            names.add(f"{server}_{tool}")
    return names


def validate_role_config(
    role: str,
    config: dict,
    role_cfg: dict,
    personal_mcp: dict,
    mapping: dict,
    readback: dict,
    tools_json: dict,
) -> list[tuple[str, bool, str]]:
    """728-E/F D8 checks for one rendered role config. Pure — returns results."""
    out: list[tuple[str, bool, str]] = []
    upper = role.upper()
    portal_cfg = role_cfg["portal"]
    entry = portal_cfg["entry"]
    servers = config.get("mcp_servers") or {}
    pm = servers.get("personal-mcp") or {}
    portal = servers.get(entry) or {}
    portal_include = list((portal.get("tools") or {}).get("include") or [])
    pm_include = list((pm.get("tools") or {}).get("include") or [])
    all_includes = {"personal-mcp": pm_include, entry: portal_include}

    # Shape (728-D D2).
    model = config.get("model") or {}
    shape_bad: list[str] = []
    if set(config) != {"model", "mcp_servers"}:
        shape_bad.append(f"top-level keys {sorted(config)}")
    if set(servers) != {"personal-mcp", entry}:
        shape_bad.append(f"servers {sorted(servers)}")
    want_model = {k: v for k, v in role_cfg["model"].items() if k != "note"}
    if model != want_model:
        shape_bad.append(f"model {model}")
    for name, srv in (("personal-mcp", pm), (entry, portal)):
        tools = srv.get("tools") or {}
        if not (
            srv.get("enabled") is True
            and srv.get("connect_timeout") == 30
            and srv.get("timeout") == 300
            and tools.get("resources") is False
            and tools.get("prompts") is False
        ):
            shape_bad.append(f"{name}: enabled/timeouts/resources/prompts")
    if pm.get("url") != PERSONAL_MCP_URL:
        shape_bad.append(f"personal-mcp url {pm.get('url')!r}")
    out.append((f"{role}: config.yaml in 728-D D2 shape", not shape_bad, "; ".join(shape_bad)))

    # Secrets: ${VAR} refs only, and only this role's own vars (728-D D3).
    want_headers = {
        "personal-mcp": {"Authorization": f"Bearer ${{MCP_SERVICE_TOKEN_{upper}}}"},
        entry: {
            "CF-Access-Client-Id": f"${{CF_ACCESS_CLIENT_ID_{upper}}}",
            "CF-Access-Client-Secret": f"${{CF_ACCESS_CLIENT_SECRET_{upper}}}",
        },
    }
    hdr_bad = [
        f"{name}: {srv.get('headers')}"
        for name, srv in (("personal-mcp", pm), (entry, portal))
        if srv.get("headers") != want_headers[name]
    ]
    out.append((f"{role}: headers are own-role ${{VAR}} refs only", not hdr_bad, "; ".join(hdr_bad)))

    # personal-mcp include == the role's token scope expansion.
    want_pm: list[str] = []
    for item in role_cfg["personal_mcp_allow"]:
        for n in personal_mcp["groups"][item[6:]] if item.startswith("group:") else [item]:
            if n not in want_pm:
                want_pm.append(n)
    out.append((
        f"{role}: personal-mcp include == token scope expansion",
        pm_include == want_pm,
        f"got={pm_include}" if pm_include != want_pm else "",
    ))

    # D8 check 1: every portal include name is in the recorded read-back set,
    # and the read-back artifact is internally consistent.
    served: set[str] = set()
    rb_bad: list[str] = []
    for server, rec in readback["servers"].items():
        expect = [f"{server}_{t}" for t in rec["enabled_catalog"]]
        if rec["enabled_served"] != expect:
            rb_bad.append(f"{server}: enabled_served != <server>_<catalog>")
        served.update(rec["enabled_served"])
    capture = readback["tools_list_capture"]
    live = set(capture["names"]) - set(capture["management_tools"])
    if not live <= served:
        rb_bad.append(f"tools/list names not in enabled set: {sorted(live - served)}")
    missing = [n for n in portal_include if n not in served]
    out.append((
        f"{role}: [D8-1] portal include names ⊆ committed read-back set",
        not missing and not rb_bad,
        "; ".join(rb_bad + ([f"not served: {missing}"] if missing else [])),
    ))

    # D8 check 2: no dotted contract name in any include list.
    dotted = [f"{s}: {n}" for s, inc in all_includes.items() for n in inc if "." in str(n)]
    out.append((f"{role}: [D8-2] no dotted contract names in includes", not dotted, "; ".join(dotted)))

    # D8 check 3: no inactive-phase (W1/W2/W3) write name, nor any explicitly
    # unmapped / absent-on-portal name, in any include list.
    forbidden: set[str] = set()
    inactive = [p for p in portal_cfg["phases"] if p not in portal_cfg["active_phases"]]
    for p in inactive:
        forbidden |= _phase_names(portal_cfg["phases"][p])
    for block in mapping["explicitly_unmapped"] + mapping["absent_on_portal"]:
        if block.get("role", role) == role:
            forbidden |= _phase_names({block["server"]: block["tools"]})
    leaked = [f"{s}: {n}" for s, inc in all_includes.items() for n in inc if n in forbidden]
    out.append((
        f"{role}: [D8-3] no inactive-phase/unmapped write names in includes (inactive: {inactive or 'none'})",
        not leaked,
        "; ".join(leaked),
    ))

    # D8 check 4: writer read_back_only survives into the bundle (tools.json).
    if role == "writer":
        rbo_rows = {
            f"{r['server']}_{r['tool']}"
            for r in mapping["portal_rows"]
            if r["role"] == role and r["server_entry"] == entry and r["read_back_only"]
        }
        expected = [n for n in portal_include if n in rbo_rows]
        tp = tools_json.get("portal") or {}
        got = tp.get("read_back_only")
        wc = set(tp.get("write_capable") or [])
        bad: list[str] = []
        if got != expected:
            bad.append(f"tools.json portal.read_back_only={got} expected={expected}")
        if wc & set(got or []):
            bad.append(f"read_back_only classified write-capable: {sorted(wc & set(got or []))}")
        if tp.get("include") != portal_include:
            bad.append("tools.json portal.include != config.yaml include")
        if not {"gmail.read_email", "linear.get_issue"} <= set(tools_json.get("read_back_only") or []):
            bad.append("contract-level read_back_only lost")
        out.append((f"{role}: [D8-4] read_back_only flags survive into tools.json", not bad, "; ".join(bad)))

    # D8 check 5: portal URL byte-matches the live endpoint.
    live_url = LIVE_PORTAL_ENDPOINTS.get(role)
    url = portal.get("url")
    url_ok = (
        url == live_url
        and readback.get("endpoint") == live_url
        and live_url == f"https://{readback.get('hostname')}/mcp"
    )
    out.append((
        f"{role}: [D8-5] portal url byte-matches live endpoint",
        url_ok,
        f"render={url!r} readback={readback.get('endpoint')!r} live={live_url!r}" if not url_ok else "",
    ))
    return out


def check_role_configs(data_dir: Path = DATA_DIR, dist_dir: Path = DIST_DIR) -> list[bool]:
    results: list[bool] = []
    role_data = json.loads((data_dir / "role-configs.json").read_text(encoding="utf-8"))
    mapping = json.loads((data_dir / "contract-mapping.json").read_text(encoding="utf-8"))
    for role, role_cfg in sorted(role_data["roles"].items()):
        cfg_path = dist_dir / role / "config.yaml"
        if not cfg_path.is_file():
            results.append(check(f"{role}: dist config.yaml present", False, str(cfg_path)))
            continue
        try:
            config = parse_config_yaml(cfg_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            results.append(check(f"{role}: config.yaml parses", False, str(exc)))
            continue
        readback = json.loads(
            (data_dir / role_cfg["portal"]["readback"]).read_text(encoding="utf-8")
        )
        if readback["tools_list_capture"].get("pending"):
            print(f"NOTE: {role}: portal tools/list capture is partial — {readback['tools_list_capture']['pending']}")
        tools_json = json.loads((dist_dir / role / "tools.json").read_text(encoding="utf-8"))
        for name, ok, detail in validate_role_config(
            role, config, role_cfg, role_data["personal_mcp"], mapping, readback, tools_json
        ):
            results.append(check(name, ok, detail))
    return results


def check_all_config_includes_undotted(dist_dir: Path = DIST_DIR) -> list[bool]:
    """D8 check 2 across every dist/*/config.yaml (incl. hand-authored scout)."""
    bad: list[str] = []
    for cfg_path in sorted(dist_dir.glob("*/config.yaml")):
        try:
            config = parse_config_yaml(cfg_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            bad.append(f"{cfg_path.parent.name}: unparseable ({exc})")
            continue
        for sname, srv in (config.get("mcp_servers") or {}).items():
            for n in ((srv or {}).get("tools") or {}).get("include") or []:
                if "." in str(n):
                    bad.append(f"{cfg_path.parent.name}/{sname}: {n}")
    return [check("[D8-2] no dotted contract names in any dist/*/config.yaml include", not bad, "; ".join(bad))]


def main() -> int:
    profiles, results = load_profiles()
    if profiles:
        results.extend(check_consult_symmetry(profiles))
        results.extend(check_write_tools(profiles))
        results.extend(check_writer_only_external_writes(profiles))
    results.extend(check_role_configs())
    results.extend(check_all_config_includes_undotted())

    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    print("SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
