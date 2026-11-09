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
| `type` | One of: `snapshot`, `plan`, `question`, `receipt`, `report`, `consult-request`, `consult-response`. |
| `version` | Protocol version; currently `1`. |
| `created_at` | ISO 8601 date-time when the artifact was produced. |
| `producer` | Bot role that produced the artifact (e.g. `scout`, `planner`, `writer`). |
| `refs` | Lineage and cross-references (type-specific; may be `{}`). |
| `payload` | Type-specific body (required fields per schema; additional fields allowed). |

Schemas live in `protocol/schemas/` (JSON Schema draft 2020-12).

## Lineage rules

- Every **Plan** references exactly one **Snapshot** via `refs.snapshot_id`.
- Every **Receipt** references exactly one **Plan** via `refs.plan_id`.
- A **Question** references the artifact and item it is about via
  `refs.artifact_id` and `refs.item_ref`.
- A **Consult-request** references the artifact item it concerns via
  `refs.artifact_id` and `refs.item_ref`.
- A **Consult-response** references the consult-request it answers via
  `refs.request_id`.
- **Snapshot** and **Report** have no required refs (empty `refs` is allowed).

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
consult-response→consult-request). Exit code `0` means all checks passed.

Individual schema files can be sanity-checked with:

```bash
python3 -m json.tool protocol/schemas/<name>.schema.json
```
