#!/usr/bin/env python3
"""Validate canonical bot definitions under bots/."""

from __future__ import annotations

import json
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
            if role == "herald" and tool.startswith("whatsapp.") and ".send" in tool:
                continue
            if role == "coordinator" and tool.startswith("schedule."):
                continue
            ok = False
            violations.append(f"{role}: {tool}")
    results.append(
        check(
            "write/apply/send tools restricted to Writer (plus Herald whatsapp, Coordinator schedule)",
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


def main() -> int:
    profiles, results = load_profiles()
    if profiles:
        results.extend(check_consult_symmetry(profiles))
        results.extend(check_write_tools(profiles))
        results.extend(check_writer_only_external_writes(profiles))

    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    print("SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
