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


CONSULT_BLOCK_MARKER = "<!-- consult-inbox-protocol:v1 -->"
CONSULT_BLOCK_HEADING = "## Consult inbox protocol"

_PARAM_PATTERNS = {
    "may": re.compile(r"^- May consult: (.+) \(max (\d+) per run\)$", re.M),
    "answers": re.compile(r"^- Answers consults from: (.+)$", re.M),
    "tclass": re.compile(r"^- Timeout class: (.+)$", re.M),
    "cadence": re.compile(r"^- Wake cadence: (.+)$", re.M),
    "bound": re.compile(r"^- Consult timeout bound: (.+)$", re.M),
}


def _split_roles(text: str) -> list[str]:
    return [] if text == "none" else [r.strip() for r in text.split(",")]


def expected_timeout_params(profile: dict) -> tuple[str, str, str]:
    """(timeout class, wake cadence, timeout bound) a role's consult
    block must state, derived from its profile schedule.

    Event-kind profiles have no interval in profile.json; their wake
    cadence is the 5-minute poll tick (plan D3, deployed by the 728-D
    cron seed). Cron bounds are the spec's (728-G D4): max cron gap
    + 30m responder allowance.
    """
    sched = profile["schedule"]
    kind, detail = sched["kind"], sched["detail"]
    if kind == "interval":
        bound = {"5m": "(30m, 35m]", "30m": "(30m, 60m]"}[detail]
        return "tick", f"{detail} tick", bound
    if kind == "event":
        return "tick", "5m tick", "(30m, 35m]"
    if kind == "cron":
        bound = {"0 7,19 * * *": "at most ~12.5h", "0 5 * * *": "at most ~24.5h"}[
            detail
        ]
        return "cron", f"cron `{detail}`", bound
    raise ValueError(f"no timeout expectation for schedule kind {kind!r}")


def check_consult_inbox_block(profiles: dict[str, dict]) -> list[bool]:
    """728-G B2: every role's INSTRUCTIONS.md carries the Consult inbox
    protocol block, and its stated parameters equal profile.json's
    consult/budget/schedule values — the block must not drift from the
    enforced matrix silently."""
    results: list[bool] = []
    for bot in sorted(EXPECTED_BOTS):
        prof = profiles.get(bot)
        if prof is None:
            results.append(check(f"{bot}: consult inbox block", False, "no profile"))
            continue
        text = (BOTS_DIR / bot / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        present = CONSULT_BLOCK_HEADING in text and CONSULT_BLOCK_MARKER in text
        results.append(check(f"{bot}: consult inbox block present", present))
        if not present:
            continue

        problems: list[str] = []
        found: dict[str, re.Match | None] = {
            k: pat.search(text) for k, pat in _PARAM_PATTERNS.items()
        }
        for k, m in found.items():
            if m is None:
                problems.append(f"missing parameter line: {k}")
        if not problems:
            may_roles = _split_roles(found["may"].group(1))
            if may_roles != prof["consult"]["may_consult"]:
                problems.append(
                    f"may_consult block={may_roles} profile={prof['consult']['may_consult']}"
                )
            if int(found["may"].group(2)) != prof["budget"]["max_consults_per_run"]:
                problems.append(
                    f"max block={found['may'].group(2)} "
                    f"profile={prof['budget']['max_consults_per_run']}"
                )
            ans_roles = _split_roles(found["answers"].group(1))
            if ans_roles != prof["consult"]["may_be_consulted_by"]:
                problems.append(
                    f"answers block={ans_roles} "
                    f"profile={prof['consult']['may_be_consulted_by']}"
                )
            try:
                exp_class, exp_cadence, exp_bound = expected_timeout_params(prof)
            except (KeyError, ValueError) as exc:
                problems.append(f"timeout expectation: {exc}")
            else:
                if found["tclass"].group(1) != exp_class:
                    problems.append(
                        f"timeout class block={found['tclass'].group(1)!r} "
                        f"expected={exp_class!r}"
                    )
                if found["cadence"].group(1) != exp_cadence:
                    problems.append(
                        f"cadence block={found['cadence'].group(1)!r} "
                        f"expected={exp_cadence!r}"
                    )
                if found["bound"].group(1) != exp_bound:
                    problems.append(
                        f"bound block={found['bound'].group(1)!r} expected={exp_bound!r}"
                    )
        results.append(
            check(
                f"{bot}: consult block parameters match profile",
                not problems,
                "; ".join(problems),
            )
        )
    return results


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


def main() -> int:
    profiles, results = load_profiles()
    if profiles:
        results.extend(check_consult_symmetry(profiles))
        results.extend(check_consult_inbox_block(profiles))
        results.extend(check_write_tools(profiles))
        results.extend(check_writer_only_external_writes(profiles))

    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    print("SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
