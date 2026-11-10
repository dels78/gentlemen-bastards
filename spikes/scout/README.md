# Scout spike runbook (Hermes, SHADOW)

**Goal:** Validate [Hermes Agent](https://github.com/dels78/gentlemen-bastards/blob/main/PROPOSAL.md) as the shared bot runtime by operating **Scout** alone in **SHADOW** mode with real Gmail and Linear reads, before any other role is deployed on the gateway. Scout is the read-only sensing bot; if Hermes, personal-mcp wiring, profile rendering from `dist/`, and artifact output behave as designed, the personal triage loop can build on this stack with confidence. This spike tracks [PERSO-727](https://linear.app/dels78/issue/PERSO-727/build-step-4-scout-spike-on-hermes-shadow-then-coordinator-planner) in Linear.

**Status:** The spike is **staged, not live**. GB-05a lands the Hermes gateway in homeops with the workload **disabled** (`replicas: 0`). Nothing in this document assumes Scout is running until someone deliberately enables it.

---

## What is deployed

| Piece | Detail |
|-------|--------|
| **Runtime** | Hermes Agent gateway in the **homeops** cluster (`clusters/homeops/` in the homeops repo). Single-gateway “big pod” topology: one gateway process loads exactly one bot profile for this spike. |
| **Image** | Derived image `ghcr.io/dels78/hermes-scout`, built in **homeops** by `.github/workflows/hermes-scout-image.yaml` from `workload/apps/hermes/Dockerfile`. Each build pushes a version tag derived from the Dockerfile pins (e.g. `v0.23.0-cc2.1.319`) **and** an immutable full commit-SHA tag — **the deployment runs the SHA tag**. On build completion, `.github/workflows/update-homeops-hermes-image.yaml` mints a GitHub App installation token (no PAT) and opens an auto-PR that rewrites `newTag` in `workload/apps/hermes/kustomization.yaml` to the build’s full SHA; the PR auto-merges (squash) once checks pass and Argo CD syncs the SHA-pinned image. **Renovate does not manage this tag** — its only hermes rule bumps the `CLAUDE_CODE_VERSION` pin in the Dockerfile. Roll back by reverting the write-back PR (SHA tags are immutable, so the previous image remains in GHCR). |
| **Profile** | **Scout only** — no Coordinator, Planner, Writer, Herald, or Librarian bundles on this gateway. |
| **Profile source** | Rendered bundle pinned to a specific **gentlemen-bastards** git commit (manifest / image build records the SHA). Regenerate from `bots/scout/` via `generator/generate.py`; deployed bits must match **`dist/scout/`** at that commit, not hand-edited tree copies. |
| **Rendered source of truth** | [`dist/scout/`](../../dist/scout/) — `bundle.json`, `system-prompt.md`, `schedule.json`, `tools.json`, `budget.json`. Gateway-wide allowlists: [`dist/gateway-allowlists.json`](../../dist/gateway-allowlists.json) (Scout stanza must agree with `dist/scout/tools.json`). |
| **MCP** | **personal-mcp** is the **only** MCP server on this gateway. Scout reaches Gmail and Linear (and Calendar reads per profile) through that server — not through ad-hoc tools or extra MCP endpoints. |
| **Framework memory** | **Disabled** for the spike. Runs are stateless aside from artifact files and Hermes run logs; no Hermes long-term memory store. |
| **Model supply** | Claude via the owner’s **subscription**, using the official **Direct SDK** plugin path. **Never** an Anthropic API key on the cluster for this spike. |
| **Initial scale** | **`replicas: 0`** at merge — manifests present, no scheduled Scout executions until enabled. |

Instructions and behavior contracts live under [`bots/scout/`](../../bots/scout/) and [`contracts/`](../../contracts/); **`dist/`** is what Hermes actually loads after generation.

---

## SHADOW invariant

The spike runs in **SHADOW**: Scout may **read** live state that overlaps with the **still-running Cursor automations** (same inbox, same Linear workspace). That overlap is intentional for comparing Snapshot quality against reality.

**Writes never overlap** with the live loop:

- Scout’s gateway allowlist has **no** Gmail or Linear **write** tools — only read-style calls plus artifact I/O. From [`dist/gateway-allowlists.json`](../../dist/gateway-allowlists.json), the Scout `allow` list is:

  - `gmail.search_emails`, `gmail.read_email`, `gmail.get_thread`
  - `linear.list_issues`, `linear.get_issue`
  - `calendar.list_events`, `calendar.get_event`
  - `artifacts.read`, `artifacts.write`

  There is no `gmail.apply`, no Linear `save_*`, no `whatsapp.send`, and no other external mutators. **Scout cannot write to Gmail or Linear by construction** if the gateway enforces this list.

- The **only writes in the Scout spike** are **Snapshot** (and supporting artifact-store) files via `artifacts.write` into the spike’s configured artifact store. Cursor automations remain the **live** writers to Gmail and Linear throughout the spike.

If an allowlist violation appears in gateway logs, treat it as a **severity-1** finding and disable the workload until understood.

---

## Enabling

### Enable (start the spike)

1. Confirm GB-05a is merged and the homeops app for Scout exists under `clusters/homeops/` with **`replicas: 0`**.
2. Open a **reviewed homeops PR** (or equivalent change control) that sets Scout Hermes workload **`replicas: 1`** — do not enable via unreviewed cluster edits.
3. Verify the deployed image matches the intended build — the pod’s image tag should be the homeops build SHA pinned as `newTag` in `workload/apps/hermes/kustomization.yaml` (written back by CI; see **Image** above) — and that `dist/scout/` at the intended gentlemen-bastards SHA is what was baked into the bundle.
4. **Watch the first run manually** (schedule tick or one-shot trigger): gateway pod healthy, personal-mcp reachable, first Snapshot land in the artifact store, no unexpected tool names in logs.
5. Only after the first run looks sane, let the **30-minute** interval schedule take over (see [`dist/scout/schedule.json`](../../dist/scout/schedule.json): `kind: interval`, `detail: 30m`).

### Disable (pause the spike)

1. **Pause runs:** reviewed homeops change back to **`replicas: 0`**. Pods drain; no new Scout runs; staged config remains for a later re-enable.
2. **Full removal:** delete the Scout Hermes app directory from `clusters/homeops/` (and any associated secrets references only used by this spike) via reviewed change. Cursor automations are untouched either way.

---

## What a good run looks like

On Scout’s schedule (**every 30 minutes** per [`dist/scout/schedule.json`](../../dist/scout/schedule.json)), a **successful** run:

1. **Opens** the run window (since last successful Snapshot or the schedule window — see [`bots/scout/INSTRUCTIONS.md`](../../bots/scout/INSTRUCTIONS.md)).
2. **Reads** recent Gmail and Linear state (and Calendar per profile) through **personal-mcp**, using only tools on the Scout allowlist.
3. **Classifies** items with deterministic rules; uses the model only where the profile delegates judgment.
4. **Writes exactly one** `snapshot` artifact with full **protocol envelope** fields (`id`, `type`, `version`, `created_at`, `producer`, `refs`, `payload`) and a payload conforming to [`protocol/schemas/snapshot.schema.json`](../../protocol/schemas/snapshot.schema.json). See [`protocol/examples/snapshot.json`](../../protocol/examples/snapshot.json) for shape.
5. **Validates** against repo semantics: envelope rules and schema checks as implemented in [`protocol/validate.py`](../../protocol/validate.py) (schema satisfaction for the Snapshot type; lineage rules for Snapshot allow empty `refs`).

On partial API failure, a good run still emits one Snapshot with honest `payload.errors[]` — not a silent omission of a source.

### Sample validation checklist (per run)

| Check | Pass criterion |
|-------|----------------|
| Artifact validates | JSON parses; envelope fields present; `type` is `snapshot`; `producer` is `scout`; payload matches `snapshot.schema.json` under `protocol/validate.py` rules. |
| Sources covered | Snapshot reflects Gmail + Linear reads attempted in the window; errors array documents any miss. |
| Allowlist | Gateway tool log shows **only** Scout-allowed tools (see SHADOW section); **zero** out-of-list attempts. |
| Cost / model | Run metadata or gateway accounting records model id and approximate cost for the run (subscription path, not API key billing). |

---

## Validation checklist for the spike

Use this before calling the spike successful and before feeding go/no-go into step 5 ([PERSO-728](https://linear.app/dels78/issue/PERSO-728/build-step-5-writer-for-linear-then-email-herald-librarian-on-schedule)):

- [ ] Several **consecutive scheduled runs** complete without crash loops or repeated hard failures.
- [ ] **Every** emitted Snapshot is **schema-valid** (protocol envelope + snapshot payload).
- [ ] **Zero** out-of-allowlist tool attempts in gateway logs across those runs.
- [ ] **No external writes** observed (Gmail sent mail, label changes, Linear issue mutations) attributable to Scout or this gateway — only artifact files grow in the spike store.
- [ ] **Cost per run** noted (rough subscription burn acceptable; trend stable, no runaway loops).
- [ ] Snapshot **content sanity-checked by a human** at least once: compare a Snapshot’s items/summaries to the actual inbox and Linear triage view at that time.

---

## Findings

Record dated notes here during and after the spike. Do **not** silently patch `dist/` or homeops from this file — file gentlemen-bastards or homeops issues (GB-*) for durable fixes.

### Hermes behavior surprises

- **2026-11-08 (ET)** — Appliance realignment (GB-05h): the hermes-agent image is an s6-overlay appliance, not a CLI container; the spike’s early failures (uid/permission chain, plugin-install idempotency, `gateway` StartError) all traced to that one wrong assumption. Manifests now follow the vendor contract: vendor entrypoint + args `["gateway","run"]`, uid/gid 10000 (vendor-native), bootstrap as Argo PreSync hook Jobs on the derived image, declarative plugin enablement via config.yaml, API server on loopback with the stage2-generated key.

### Build + rollout log

- **2026-11-08–09 (ET)** — Derived-image build chain (GB-05i..05n, five failed runs, each a distinct defect): fabricated GitHub Action pin SHAs (verify every pin resolves before use); the stock image ships dangling `/usr/local/bin/npm`+`npx` symlinks (final stage lacks the node install) so the derived image transplants its own Node 22; the claude-code npm package’s bin is a non-executable stub until its postinstall runs; root cause of the last two failures: inside the hermes image, `npm config get prefix` resolves to the vendor’s node tree (`/opt/hermes/tools/node-26.12.1-linux-x64`), so `npm install -g` silently installed claude-code there instead of `/usr/local`. Fix: `npm install -g --prefix /usr/local` + explicit postinstall run, gated by an in-Dockerfile `claude --version` assertion. Build green from run 42561798551 (2026-11-09): `ghcr.io/dels78/hermes-scout:v0.23.0-cc2.1.319` + sha tag pushed.

- **2026-11-09 (ET)** — Rollout blocked at the PreSync fetch Job: ImagePullBackOff; `ghcr.io` token endpoint returns 401 to the anonymous fetch for the brand-new `dels78/hermes-scout` package (first pushed by the workflow’s `GITHUB_TOKEN` tonight). The ghcr-pull-secret pattern is proven — the same 1Password item pulls three other dels78 GHCR packages in three other namespaces — so the fix is owner-side package access (connect the homeops repo in the package settings) and/or confirming the secret materialized in the new hermes namespace (tracked on PERSO-727). Until the fetch Job pulls, Argo cannot apply the GB-05h deployment; the pre-05h pod remains in place. SHADOW validation (first Snapshot, zero external writes) is still pending this unblock.

- **2026-11-09 (ET)** — Image tag propagation corrected (GB-12g): the 2026-11-08–09 entry above frames the **version tag** (`v0.23.0-cc2.1.319`) as the build’s deployable output; the deployment does not track it. After GB-12f showed a same-version-tag rebuild could leave the pod running a stale digest, the kustomization pins the **full commit-SHA tag** instead, propagated mechanically: `hermes-scout-image.yaml` builds and pushes both tags → `update-homeops-hermes-image.yaml` fires on the build’s completion, mints a **GitHub App** installation token (no PAT), and opens an auto-PR (`auto/update-hermes-scout-<sha7>`) rewriting `newTag` in `workload/apps/hermes/kustomization.yaml` to the build’s full SHA → auto-merge (squash) once yamllint and the Renovate Evaluator pass → Argo CD syncs. Validated end to end the same evening: the GB-12g merge’s own build produced write-back PR #3727 in homeops, which auto-merged, and the gateway pod rolled to the new SHA digest with a clean boot. Renovate’s hermes-scout tag customManager was **removed** as part of GB-12g — Renovate does not manage this tag (see **Image** in “What is deployed”).

### Profile / `dist/` gaps (feed back into GB issues)

- _YYYY-MM-DD — _

### Model supply notes (Direct SDK / subscription path)

- _YYYY-MM-DD — _

### Go / no-go input for build step 5 (PERSO-728)

- **2026-11-09 (ET)** — Go/no-go input for PERSO-728 remains open pending first SHADOW cycle; no model-supply issues observed (no gateway turn has run yet).

---

## Failure handling

If runs fail repeatedly, produce garbage Snapshots, or logs show allowlist violations:

1. **Disable immediately:** homeops change to **`replicas: 0`** (see Enabling).
2. **Capture evidence:** export gateway logs, relevant personal-mcp errors, and any partial artifacts for the failing window.
3. **Document** in **Findings** above (dated entry under the right subsection).
4. **Leave Cursor automations running** — they remain the **live** personal triage system for the entire spike; do not disable or reconfigure them as part of Scout debugging.

Re-enable only after the root cause has a tracked fix (homeops or gentlemen-bastards) and a human agrees to another watched first run.
