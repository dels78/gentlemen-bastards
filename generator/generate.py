#!/usr/bin/env python3
"""Deterministic generator: bots/ + contracts/ -> dist/."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"

BUNDLE_FIELDS = (
    "role",
    "purpose",
    "model_tier",
    "consumes",
    "produces",
    "escalates_to",
)

WRITER_READ_BACK_ONLY = frozenset({"gmail.read_email", "linear.get_issue"})


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def discover_roles(bots_dir: Path) -> list[str]:
    if not bots_dir.is_dir():
        raise SystemExit(f"bots directory not found: {bots_dir}")
    roles = sorted(
        p.name
        for p in bots_dir.iterdir()
        if p.is_dir() and (p / "profile.json").is_file()
    )
    if not roles:
        raise SystemExit(f"no roles with profile.json under {bots_dir}")
    return roles


def collect_sources(repo_root: Path, bots_dir: Path, contracts_dir: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    if contracts_dir.is_dir():
        for fp in sorted(contracts_dir.glob("*.md")):
            try:
                rel = fp.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            sources[rel] = sha256_file(fp)

    for role in discover_roles(bots_dir):
        role_dir = bots_dir / role
        for fname in ("INSTRUCTIONS.md", "profile.json"):
            fp = role_dir / fname
            if not fp.is_file():
                raise SystemExit(f"missing {fp}")
            rel = fp.relative_to(repo_root).as_posix()
            sources[rel] = sha256_file(fp)
    return dict(sorted(sources.items()))


def tools_payload(profile: dict, role: str, portal: dict | None = None) -> dict:
    allow = list(profile["tools"]["allow"])
    payload: dict = {"allow": allow}
    if role == "writer":
        read_back = [t for t in allow if t in WRITER_READ_BACK_ONLY]
        payload["read_back_only"] = read_back
        if portal is not None:
            # 728-E/F D8 item 3: read_back_only extends to the portal entry
            # (real served names), kept disjoint from write_capable.
            payload["portal"] = {
                "entry": portal["entry"],
                "active_phases": portal["active_phases"],
                "include": portal["include"],
                "read_back_only": portal["read_back_only"],
                "write_capable": portal["write_capable"],
            }
    return payload


# --- 728-F: contract -> real-name mapping and per-role config.yaml -----------

SAFE_YAML_SCALAR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def load_role_data(data_dir: Path) -> tuple[dict, dict]:
    return (
        load_json(data_dir / "role-configs.json"),
        load_json(data_dir / "contract-mapping.json"),
    )


def expand_personal_mcp(allow: list[str], groups: dict[str, list[str]]) -> list[str]:
    """Expand `group:<name>` refs the same way personal-mcp's tool_scopes.json does."""
    out: list[str] = []
    for entry in allow:
        names = groups[entry[len("group:"):]] if entry.startswith("group:") else [entry]
        for name in names:
            if name not in out:
                out.append(name)
    return out


def served_name(server: str, tool: str) -> str:
    # Portal namespacing outside Code Mode: `<server id>_<tool>`, id verbatim.
    return f"{server}_{tool}"


def resolve_portal(role: str, portal_cfg: dict, mapping: dict) -> dict:
    """Active-phase portal selection, gated on D7 rows (D6 gate ii)."""
    entry = portal_cfg["entry"]
    rows = [
        r for r in mapping["portal_rows"]
        if r["role"] == role and r["server_entry"] == entry
    ]
    include: list[str] = []
    read_back: list[str] = []
    write_capable: list[str] = []
    for phase in portal_cfg["active_phases"]:
        if phase not in portal_cfg["phases"]:
            raise SystemExit(f"{role}: unknown active phase {phase!r}")
        for server, tools in portal_cfg["phases"][phase].items():
            for tool in tools:
                matched = [r for r in rows if r["server"] == server and r["tool"] == tool]
                if not matched:
                    raise SystemExit(
                        f"{role}: {server}/{tool} is in active phase {phase!r} "
                        f"but has no contract-mapping row for {entry} (D7) — refusing to render"
                    )
                name = served_name(server, tool)
                if name in include:
                    continue
                include.append(name)
                if any(r["read_back_only"] for r in matched):
                    read_back.append(name)
                elif any(r["kind"] == "write" for r in matched):
                    write_capable.append(name)
    return {
        "entry": entry,
        "active_phases": list(portal_cfg["active_phases"]),
        "include": include,
        "read_back_only": read_back,
        "write_capable": write_capable,
    }


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value))


def _yaml_list_item(name: str) -> str:
    return name if SAFE_YAML_SCALAR.match(name) else json.dumps(name)


def _render_server(name: str, url: str, headers: list[tuple[str, str]], include: list[str]) -> list[str]:
    lines = [
        f"  {name}:",
        "    enabled: true",
        f"    url: {_yaml_scalar(url)}",
        "    headers:",
    ]
    lines += [f"      {k}: {_yaml_scalar(v)}" for k, v in headers]
    lines += [
        "    connect_timeout: 30",
        "    timeout: 300",
        "    tools:",
        "      include:",
    ]
    lines += [f"        - {_yaml_list_item(t)}" for t in include]
    lines += [
        "      resources: false",
        "      prompts: false",
    ]
    return lines


def render_config_yaml(
    role: str,
    role_cfg: dict,
    personal_mcp: dict,
    portal: dict,
    portal_url: str,
) -> str:
    upper = role.upper()
    model = role_cfg["model"]
    lines = [
        "# GENERATED by generator/generate.py from generator/data/ — do not edit.",
        f"# Per-profile config for role `{role}` in the 728-D D2 shape (728-E/F D8).",
        "# Secrets are ${VAR} refs only, resolved in this profile's own scope.",
        f"# Portal include phase(s): {', '.join(portal['active_phases'])}; names are",
        "# the portal's prefixed served names (<server id>_<tool>).",
    ]
    if model.get("note"):
        lines.append(f"# model: {model['note']}")
    lines += [
        "model:",
        f"  provider: {model['provider']}",
        f"  default: {model['default']}",
        f"  context_length: {model['context_length']}",
        "mcp_servers:",
    ]
    lines += _render_server(
        "personal-mcp",
        personal_mcp["url"],
        [("Authorization", f"Bearer ${{MCP_SERVICE_TOKEN_{upper}}}")],
        expand_personal_mcp(role_cfg["personal_mcp_allow"], personal_mcp["groups"]),
    )
    lines += _render_server(
        portal["entry"],
        portal_url,
        [
            ("CF-Access-Client-Id", f"${{CF_ACCESS_CLIENT_ID_{upper}}}"),
            ("CF-Access-Client-Secret", f"${{CF_ACCESS_CLIENT_SECRET_{upper}}}"),
        ],
        portal["include"],
    )
    return "\n".join(lines) + "\n"


def system_prompt(
    behavior_text: str,
    behavior_path: Path,
    behavior_sha: str,
    instructions_path: Path,
    instructions_sha: str,
    instructions_text: str,
) -> str:
    inst_rel = instructions_path.as_posix()
    beh_rel = behavior_path.as_posix()
    header = (
        f"<!-- behavior-source: {beh_rel} sha256={behavior_sha} -->\n"
        f"<!-- role-instructions-source: {inst_rel} sha256={instructions_sha} -->\n"
    )
    return header + behavior_text.rstrip("\n") + "\n\n---\n\n" + instructions_text


def generate(
    bots_dir: Path,
    behavior_path: Path,
    out_dir: Path,
    behavior_label: str | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> None:
    repo_root = bots_dir.parent
    contracts_dir = behavior_path.parent
    role_data, mapping = load_role_data(data_dir)

    roles = discover_roles(bots_dir)
    behavior_text = behavior_path.read_text(encoding="utf-8")
    behavior_sha = sha256_hex(behavior_text.encode("utf-8"))

    try:
        behavior_rel = behavior_path.relative_to(repo_root).as_posix()
    except ValueError:
        behavior_rel = behavior_label or behavior_path.name

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    gateway: dict[str, dict] = {}

    for role in roles:
        role_dir = bots_dir / role
        profile_path = role_dir / "profile.json"
        instructions_path = role_dir / "INSTRUCTIONS.md"

        profile = load_json(profile_path)
        instructions_text = instructions_path.read_text(encoding="utf-8")
        instructions_sha = sha256_hex(instructions_text.encode("utf-8"))

        role_out = out_dir / role
        role_out.mkdir(parents=True)

        bundle = {k: profile[k] for k in BUNDLE_FIELDS}
        write_json(role_out / "bundle.json", bundle)

        prompt = system_prompt(
            behavior_text,
            Path(behavior_rel),
            behavior_sha,
            instructions_path.relative_to(repo_root),
            instructions_sha,
            instructions_text,
        )
        (role_out / "system-prompt.md").write_text(prompt, encoding="utf-8")

        role_cfg = role_data["roles"].get(role)
        portal = None
        if role_cfg is not None:
            portal = resolve_portal(role, role_cfg["portal"], mapping)
            readback = load_json(data_dir / role_cfg["portal"]["readback"])
            config_text = render_config_yaml(
                role,
                role_cfg,
                role_data["personal_mcp"],
                portal,
                readback["endpoint"],
            )
            (role_out / "config.yaml").write_text(config_text, encoding="utf-8")

        tools = tools_payload(profile, role, portal)
        write_json(role_out / "tools.json", tools)

        write_json(role_out / "budget.json", {
            "budget": profile["budget"],
            "consult": profile["consult"],
        })

        write_json(role_out / "schedule.json", profile["schedule"])

        gw_entry: dict = {"allow": list(profile["tools"]["allow"])}
        if role == "writer":
            gw_entry["read_back_only"] = tools["read_back_only"]
        gateway[role] = gw_entry

    write_json(out_dir / "gateway-allowlists.json", dict(sorted(gateway.items())))

    sources = collect_sources(repo_root, bots_dir, contracts_dir)
    manifest = {
        "behavior": behavior_rel,
        "behavior_sha256": behavior_sha,
        "generator": "generator/generate.py",
        "roles": roles,
        "sources": sources,
    }
    write_json(out_dir / "manifest.json", manifest)


def tree_diff(a: Path, b: Path) -> list[str]:
    """Return human-readable diff lines between directory trees."""
    lines: list[str] = []
    all_rel: set[str] = set()

    for root in (a, b):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                all_rel.add(p.relative_to(root).as_posix())

    for rel in sorted(all_rel):
        pa, pb = a / rel, b / rel
        if pa.is_file() != pb.is_file():
            lines.append(f"only in {'a' if pa.is_file() else 'b'}: {rel}")
            continue
        if pa.read_bytes() != pb.read_bytes():
            lines.append(f"content differs: {rel}")
    return lines


def check_against(
    bots_dir: Path,
    behavior_path: Path,
    out_dir: Path,
    behavior_label: str | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    if not out_dir.is_dir():
        print(f"check failed: output directory missing: {out_dir}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "dist"
        generate(
            bots_dir, behavior_path, tmp_out,
            behavior_label=behavior_label, data_dir=data_dir,
        )

        diffs = tree_diff(tmp_out, out_dir)
        if diffs:
            print("check failed: dist/ differs from regenerated output", file=sys.stderr)
            for line in diffs:
                print(f"  {line}", file=sys.stderr)
            return 1

    print("check passed: dist/ matches generator output")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bots", type=Path, default=Path("bots"))
    parser.add_argument(
        "--behavior", type=Path, default=Path("contracts/BEHAVIOR.md")
    )
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="728-F mapping/role-config/read-back inputs (default: generator/data)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate to temp dir and diff against --out",
    )
    args = parser.parse_args(argv)

    bots_dir = args.bots.resolve()
    behavior_path = args.behavior.resolve()
    out_dir = args.out.resolve()
    behavior_label = args.behavior.as_posix()
    data_dir = args.data.resolve()

    if args.check:
        return check_against(
            bots_dir, behavior_path, out_dir,
            behavior_label=behavior_label, data_dir=data_dir,
        )

    generate(
        bots_dir, behavior_path, out_dir,
        behavior_label=behavior_label, data_dir=data_dir,
    )
    print(f"generated {len(discover_roles(bots_dir))} roles -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
