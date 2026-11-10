# Artifact protocol

The personal-loop swarm (Scout, Planner, Writer, Herald, Librarian,
Coordinator) coordinates by exchanging **typed artifacts** instead of
free-form chat. Each artifact is a JSON document with a common envelope and a
type-specific `payload`. Artifacts are the system of record: every proposed
write traces to a Plan, every Plan to a Snapshot, and every applied write to
a Receipt.

## Common envelope

Every artifact includes these top-level fields (no extra keys at the envelope
level):

| Field | Meaning |
|-------|---------|
| `id` | Unique artifact identifier (string). |
| `type` | One of: `snapshot`, `plan`, `question`, `receipt`, `report`, `consult-request`, `consult-response`, `brain-proposal`, `decision`. |
| `version` | Protocol version; currently `1`. |
| `created_at` | ISO 8601 date-time when the artifact was produced. |
| `producer` | Bot role that produced the artifact (e.g. `scout`, `planner`, `writer`). |
| `refs` | Lineage and cross-references (type-specific; may be `{}`). |
| `payload` | Type-specific body (required fields per schema; additional fields allowed). |

Schemas live in `protocol/schemas/` (JSON Schema draft 2020-12).

## Lineage rules

- Every **Plan** references exactly one **Snapshot** via `refs.snapshot_id`.
- A **Receipt** takes one of two variants: a **plan receipt** references exactly one **Plan** via `refs.plan_id`; a **brain-apply receipt** (gated brain apply, see Decision convention) references exactly one **Decision**, one **Question**, and one **Brain-proposal** via `refs.decision_id`, `refs.question_id`, and `refs.proposal_id`, and carries no `plan_id`.
- A **Question** references the artifact and item it is about via
  `refs.artifact_id` and `refs.item_ref`.
- A **Consult-request** references the artifact item it concerns via
  `refs.artifact_id` and `refs.item_ref`.
- A **Consult-response** references the consult-request it answers via
  `refs.request_id`.
- A **Decision** carries its lineage in its payload, not in `refs`: `refs` is the empty object, `payload.subject_ref` names the **Question** it answers, and `payload.proposal_ref` names the **Brain-proposal** that Question develops.
- **Snapshot** and **Report** have no required refs (empty `refs` is allowed).

## Brain-proposal convention

Brain-proposal is the loop's inbox for suggested brain (mbrain) changes:

- **Any role bot may propose** by emitting a `brain-proposal` artifact (`payload.proposer` names the originating bot role; `producer` is whoever wrote the artifact to the store).
- **Proposer ≠ applier ≠ approver.** Proposals are artifacts only — they do not write the brain. The **Librarian** triages proposals, develops well-formed ones, and re-emits **Questions** for human approval. Only after Martin's approval has been recorded as a `decision` artifact by the Coordinator may the Librarian invoke the gated apply (`brain_apply_gated` in personal-mcp), which opens a Librarian-apply PR in dels78/mbrain. The gated tool never commits directly to `main`, and no other apply path exists inside this protocol.
- **`payload.target`** is an existing brain record id, or `null` when proposing a new record.
- **`payload.change_kind`** is one of `create`, `amend`, `supersede`, or `archive`.
- **`payload.evidence_refs`** must cite supporting artifact ids or durable source pointers (non-empty).

Librarian-routed **Questions** about an approved proposal path should reference the originating `brain-proposal` via `refs.artifact_id` and a stable `refs.item_ref` (for example the brain record id or proposal id).

## Decision convention

A `decision` artifact is the **only** record of a human decision inside the protocol, and the only approval the gated brain apply accepts:

- **Producer: `coordinator` only.** Decisions enter the store exclusively through the Coordinator/Muse bridge: the Coordinator records answers Martin actually gave on the Muse escalation path. No other role — including the Librarian that will act on the decision — can mint one. `payload.decided_by` is the const `"martin"`; it is an attestation recorded by the Coordinator, not a cryptographic proof, so custody of the Coordinator role's credential is the control.
- **Payload (closed — no additional fields):** `decision` (`"approved"` or `"rejected"`), `subject_ref` (the `question` artifact id being answered), `proposal_ref` (the `brain-proposal` artifact id), `decided_by` (`"martin"`), and optional `rationale` (approval context only; it is never written into the brain or an apply PR). Lineage lives in these payload fields; **`refs` is always the empty object**.
- **Write-time chain validation:** `subject_ref` must resolve to a stored `question`, `proposal_ref` to a stored `brain-proposal`, the question's `refs.artifact_id` must equal `proposal_ref`, and the question's `producer` must be `librarian` (only the Librarian develops proposals into Questions). A decision failing any of these is refused at write.
- **A `rejected` decision is a first-class record** — it is how a "no" is recorded. It never authorizes anything and is never consumed; a later, distinct `approved` decision on the same chain is a new record, evaluated on its own.
- **Single-use:** an `approved` decision authorizes at most one gated apply. Consumption is recorded by the gated tool in the store's append-only marks with the purpose `brain_apply_consumed` (generic processing marks do not count). One proposal gets at most one gated apply, however many decisions approve it.

### Brain-apply receipts

The gated apply evidences itself with the **brain-apply receipt variant** (the plan receipt — producer `writer`, `refs.plan_id`, statuses `applied`/`failed`/`skipped` — is unchanged):

- `producer` is `librarian`; `refs` contains exactly `decision_id`, `question_id`, and `proposal_id`, each resolving to the stored artifact of that type, and no `plan_id`.
- `payload` requires `pr_url`, `branch`, `base_sha`, and `head_sha`, plus `results` with exactly one entry: `{"object_ref": "mbrain:<record_id>", "status": "pr_opened", "readback": "<pr_url>"}`. `pr_opened` is valid only for this variant; the receipt evidences that the apply PR was **opened** — it does not claim the change is on `main`.
- **Minting is reserved to the gated tool** in personal-mcp: the generic artifact write path refuses this variant from every role, so a brain-apply receipt cannot be forged; the tool stamps `producer: "librarian"` itself after a successful PR creation.

## Consult convention

Live consultation is the controlled exception to pure artifact handoff:

- A consult is a typed **consult-request** / **consult-response** pair about
  one referenced artifact item.
- **Advice crosses; authority never does.** A consult can inform a bot; it
  cannot grant capabilities (e.g. Writer cannot consult Scout into fetching).
- Consults are budgeted per run (count and timeout). When budget is exhausted,
  the bot parks the item as a **Question** artifact and continues
  asynchronously.
- Human decisions are not peer consults; they flow Coordinator → Muse → Martin.

## Validation

From the repository root:

```bash
python3 protocol/validate.py
```

The script checks that schema files parse, examples parse, each example
satisfies envelope and type-specific `refs`/`payload` requirements, and that
the example chain is internally consistent (plan→snapshot, receipt→plan,
consult-response→consult-request, decision→question→brain-proposal,
brain-apply receipt→decision/question/brain-proposal). Exit code `0` means all checks passed.

Individual schema files can be sanity-checked with:

```bash
python3 -m json.tool protocol/schemas/<name>.schema.json
```
