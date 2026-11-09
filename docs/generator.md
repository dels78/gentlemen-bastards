# Generator (`generator/generate.py`)

The generator is the deterministic bridge between **behavior contracts**, **per-role bot definitions**, and **deployable runtime bundles** under `dist/`. It does not talk to Hermes or the cluster; it only renders files from git sources so drift is diffable and enforcement can be applied elsewhere.

## Why it exists

- **Cross-cutting loop behavior** lives in `contracts/` (especially `contracts/BEHAVIOR.md`).
- **Per-role behavior** lives in `bots/<role>/` (`profile.json` + `INSTRUCTIONS.md`).
- **Artifact shapes** live in `protocol/`.

The generator concatenates contracts + role instructions into `system-prompt.md`, copies structured fields into JSON sidecars, and builds **`gateway-allowlists.json`** for the personal-mcp gateway. Capability enforcement is server-side at that gateway — not in generated prose alone.

`dotai` remains Martin's general instruction stack for interactive clients (laptop agents, Muse-facing tools). It is a different audience. **These loop contracts are consumed only by this system** and therefore live in `gentlemen-bastards`, not in dotai, after the GB-04 placement decision.

**Tie-break:** role-specific detail in `bots/<role>/` wins; cross-cutting behavior in `contracts/` wins on conflicts.

## Regenerating output

From the repository root:

```bash
python3 generator/generate.py
```

Defaults: `--bots bots`, `--behavior contracts/BEHAVIOR.md`, `--out dist`.

### Drift check (`--check`)

Regenerates into a temporary directory and byte-compares against committed `dist/`:

```bash
python3 generator/generate.py --check
```

Exit `0` if identical; exit `1` with a short diff summary if not. Use this in review before merging any change to `contracts/`, `bots/`, or the generator.

### Tests

```bash
python3 -m unittest discover -s generator
```

`generator/test_generate.py` uses a synthetic `BEHAVIOR.md` in a temp dir for isolation. One policy check allows librarian non-artifact tools to use `notion.*` or `linear.*`: the GB-02 profile includes `linear.list_issues` and `linear.get_issue` for backlog tending (see `bots/librarian/INSTRUCTIONS.md`), while cross-cutting “brain via notion” behavior still lives in `contracts/BEHAVIOR.md`.

## `dist/` layout

### Per role: `dist/<role>/`

| File | Contents |
|------|----------|
| `bundle.json` | `role`, `purpose`, `model_tier`, `consumes`, `produces`, `escalates_to` from `profile.json` |
| `system-prompt.md` | HTML provenance headers (source paths + sha256), full `BEHAVIOR.md`, `---`, then `INSTRUCTIONS.md` |
| `tools.json` | `{"allow": [...]}` from profile; **writer** also has `read_back_only` (see below) |
| `schedule.json` | `profile.json` → `schedule` verbatim |
| `budget.json` | `{"budget": ..., "consult": ...}` from profile |

Roles are emitted in sorted name order.

### Repository root under `dist/`

| File | Purpose |
|------|---------|
| `gateway-allowlists.json` | Per-role `allow` lists (same as each `tools.json`); writer includes `read_back_only` |
| `manifest.json` | Generator path, behavior path + sha256, sorted `sources` map (sha256 of every `contracts/*.md` and `bots/<role>/{profile.json,INSTRUCTIONS.md}` input), sorted `roles` list |

All JSON uses sorted keys and two-space indent. No timestamps or run-dependent fields — two runs over the same inputs produce byte-identical trees.

## Hermes mapping (honest scope)

This `dist/` format is **this repo's intermediate representation**. It is designed to be consumed by deployment/GitOps and validated against Hermes profile distributions in the **Scout spike** job (PERSO-727 build step 4), not fully mapped here.

Expected mapping direction (validated later, not implemented in GB-04):

- `bundle.json` + `budget.json` + `schedule.json` → Hermes profile config
- `tools.json` / `gateway-allowlists.json` → per-server MCP tool include lists (enforced again at personal-mcp)
- Framework memory → disabled; brain access via Notion MCP under dotai's access pattern

## Writer `read_back_only`

Writer's profile includes `gmail.read_email` and `linear.get_issue` for **verify-after-write** read-back, not as general fetch tools. The generator intersects the writer `allow` list with `{gmail.read_email, linear.get_issue}` and emits `read_back_only` on writer's `tools.json` and on `gateway-allowlists.json` so the gateway can scope those tools to post-write verification only. No other role carries this annotation.
