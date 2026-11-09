#!/usr/bin/env python3
"""Deterministic generator: bots/ + contracts/ -> dist/."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

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


def tools_payload(profile: dict, role: str) -> dict:
    allow = list(profile["tools"]["allow"])
    payload: dict = {"allow": allow}
    if role == "writer":
        read_back = [t for t in allow if t in WRITER_READ_BACK_ONLY]
        payload["read_back_only"] = read_back
    return payload


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
) -> None:
    repo_root = bots_dir.parent
    contracts_dir = behavior_path.parent

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

        tools = tools_payload(profile, role)
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
) -> int:
    if not out_dir.is_dir():
        print(f"check failed: output directory missing: {out_dir}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "dist"
        generate(bots_dir, behavior_path, tmp_out, behavior_label=behavior_label)

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
        "--check",
        action="store_true",
        help="Regenerate to temp dir and diff against --out",
    )
    args = parser.parse_args(argv)

    bots_dir = args.bots.resolve()
    behavior_path = args.behavior.resolve()
    out_dir = args.out.resolve()
    behavior_label = args.behavior.as_posix()

    if args.check:
        return check_against(
            bots_dir, behavior_path, out_dir, behavior_label=behavior_label
        )

    generate(bots_dir, behavior_path, out_dir, behavior_label=behavior_label)
    print(f"generated {len(discover_roles(bots_dir))} roles -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
