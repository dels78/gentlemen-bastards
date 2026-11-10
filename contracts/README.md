# Loop bot behavior contracts

These are the **gentlemen-bastards system's behavior contracts**: cross-cutting rules for the personal triage loop (scout, planner, writer, herald, librarian, coordinator) over email, Linear, and the brain (mbrain).

## Who consumes this

- **This repo's generator** (`generator/generate.py`), which renders deployable bundles under `dist/` from these contracts plus per-role definitions in `bots/`.
- **Human operators** configuring or supervising the loop without running the generator.

## Source-of-truth split

| Concern | Where it lives |
| --- | --- |
| Cross-cutting **behavior** (how every bot must act) | **Here** (`contracts/` in gentlemen-bastards) |
| Per-role **definitions** (profile, instructions, tools, routing) | `bots/<role>/` (`profile.json` + `INSTRUCTIONS.md`) |
| Typed **artifact schemas** and protocol | `protocol/` |

**dotai** remains Martin's general instruction stack for interactive clients (laptop agents, Muse-facing tools). That audience is different from the loop runtime; **dotai is not a source for these contracts anymore.**

If a role definition in `bots/<role>/` and a statement in `contracts/` **disagree on role detail** (tools, channels, profile fields), the **role definition wins**.

If they disagree on **cross-cutting behavior** (artifacts, tasks, escalation, write discipline, failure conduct), **`contracts/` wins**.

Read `BEHAVIOR.md` for the shared contract and `ROLES.md` for a one-page index of roles—not a second copy of role truth.
