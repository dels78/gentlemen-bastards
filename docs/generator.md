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

`generator/test_generate.py` uses a synthetic `BEHAVIOR.md` in a temp dir for isolation. One policy check allows librarian non-artifact tools to use `mbrain.*` or `linear.*`: the GB-02 profile includes `linear.list_issues` and `linear.get_issue` for backlog tending (see `bots/librarian/INSTRUCTIONS.md`), while cross-cutting “brain via mbrain” behavior still lives in `contracts/BEHAVIOR.md`.

## `dist/` layout

### Per role: `dist/<role>/`

| File | Contents |
|------|----------|
| `bundle.json` | `role`, `purpose`, `model_tier`, `consumes`, `produces`, `escalates_to` from `profile.json` |
| `system-prompt.md` | HTML provenance headers (source paths + sha256), full `BEHAVIOR.md`, `---`, then `INSTRUCTIONS.md` |
| `tools.json` | `{"allow": [...]}` from profile; **writer** also has `read_back_only` and a `portal` block (see below) |
| `schedule.json` | `profile.json` → `schedule` verbatim |
| `budget.json` | `{"budget": ..., "consult": ...}` from profile |
| `config.yaml` | writer, librarian, planner, herald, coordinator: Hermes profile config (see "Per-profile `config.yaml`"). Scout's is hand-authored, not generated |
| `scripts/gate.py` | roles with `gate_wake_kinds` in role-configs.json (all five generated roles): cron wake gate (see "Gate scripts") |

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
- Framework memory → disabled; brain access via personal-mcp `brain_*` tools (mbrain) under dotai's access pattern

## Per-profile `config.yaml` (728-F; 728-D D2 shape)

For every role listed in `generator/data/role-configs.json` (today: **writer**, **librarian**, **planner**, **herald**, **coordinator**) the generator also emits `dist/<role>/config.yaml` — the Hermes profile user layer: `model` block + `personal-mcp` entry + the role's Cloudflare portal entry (`writer-portal` / `librarian-portal`) where the role has one. Planner, herald and coordinator are personal-mcp-only: no `portal` key in role-configs.json, and their renders carry the single `personal-mcp` server. Scout's `dist/scout/config.yaml` is still hand-authored (728-D prerequisite) and not generated — a full generator run deletes it from `dist/`; restore it before committing (the known F1 hazard).

Inputs under `generator/data/` (all non-secret):

| File | Contents |
|------|----------|
| `contract-mapping.json` | The 728-E/F D7 contract→real-tool table, per role and server entry (`read_back_only` + `kind` per row), plus the explicit negative assertions (`explicitly_unmapped`, `absent_on_portal`). |
| `role-configs.json` | Per role: model tier values, personal-mcp scope (`group:` refs expanded like personal-mcp's `tool_scopes.json`), portal entry, the phase sets (`construction`, `W1`, `W2`, `W3`) and the pinned `active_phases`. |
| `portal-readback/<role>.json` | The portal's creation/enablement read-back: endpoint, per-server enabled tools in catalog **and** served (`<server id>_<tool>`) form, and the token-authenticated `tools/list` capture. |

Rules the generator enforces:

- Portal include = union of the active phases' tools, rendered as **served names** (`linear_get_issue`, `google-calendar_list_events` — hyphen kept); Hermes matches includes by exact string against served names.
- Every tool in an active phase must have a D7 row for that role + server entry, or generation fails (D6 gate ii). Moving to W1 is a one-line `active_phases` change; W2/W3 additionally need their D7 rows (contract/plan amendments first).
- Secrets are `${VAR}` refs only: `${MCP_SERVICE_TOKEN_<ROLE>}`, `${CF_ACCESS_CLIENT_ID_<ROLE>}`, `${CF_ACCESS_CLIENT_SECRET_<ROLE>}`.

Writer's `tools.json` gains a `portal` block (`include`, `read_back_only`, `write_capable` in served names) so the read-back-only classification survives at the real-name level (D8 item 3).

Writer's personal-mcp include is the explicit 8-name gmail list, not `group:gmail`: `gmail_send` and `gmail_delete` are SHADOW-withheld server-side for `sub=writer` (728-D D5 step 3), and the include must stay within the server-side scope. Restoring them is a paired change (role-configs.json + personal-mcp `tool_scopes.json` together).

## Gate scripts (`scripts/gate.py`; 728-D plan D3, 728-EF D10)

For every role with `gate_wake_kinds` in `role-configs.json` the generator renders `dist/<role>/scripts/gate.py` from the shared template `generator/data/gate.py.tmpl` — one shared logic, per-role wake-kind constants. The fetch hook lays `dist/<role>/scripts/*` into `<profile home>/scripts/`, where Hermes' cron scheduler runs it as a pre-run gate: the last stdout line `{"wakeAgent": false}` skips the model run; any failure wakes (safe direction), so the script exits non-zero with no `wakeAgent` line on any error. The script derives its role from its home directory name, reads `MCP_SERVICE_TOKEN_<ROLE>` from `<home>/.env`, and makes one unfiltered `artifacts_list(unprocessed_for=<role>, limit=500)` call to the in-cluster personal-mcp server, type-filtering client-side against its wake kinds (the D10 fallback shape). Wake kinds per role live in `role-configs.json`; `bots/validate.py` checks each rendered gate carries exactly its kinds.

`bots/validate.py` checks each rendered config: D2 shape and own-role `${VAR}` headers; **[D8-1]** portal includes ⊆ the committed read-back's enabled served names; **[D8-2]** no dotted contract names in any include (all `dist/*/config.yaml`); **[D8-3]** no inactive-phase (W1/W2/W3), unmapped, or absent-on-portal name in any include, prefixed or not; **[D8-4]** writer `read_back_only` present in `tools.json` and disjoint from `write_capable`; **[D8-5]** portal URL byte-equals the live endpoint.

## Writer `read_back_only`

Writer's profile includes `gmail.read_email` and `linear.get_issue` for **verify-after-write** read-back, not as general fetch tools. The generator intersects the writer `allow` list with `{gmail.read_email, linear.get_issue}` and emits `read_back_only` on writer's `tools.json` and on `gateway-allowlists.json` so the gateway can scope those tools to post-write verification only. No other role carries this annotation.
