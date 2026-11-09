# Personal Loop Architecture — Proposal

Status: DRAFT for Martin's approval (2026-11-08, rev 11 — adds the cutover
discipline, section 14; runtime decided: Hermes Agent; system repo named
gentlemen-bastards)
Supersedes: the Cursor Automations driver era (Oct–Nov 2026) and the Grok Bot period.
Design inputs: Martin's architecture principles, the dotai instruction stack, the
mbrain design record, the 2026-11-08 repo/cluster/Cursor/Linear inventory.

## 1. The shape in one paragraph

Martin talks to one thin conversational layer — Muse — which is the interface
and manager, not the engine. Underneath it, the personal loop is a small swarm
of self-hosted role-agents resident in Martin's cluster: each former pipeline
stage is a bot with its own instructions, schedule, and narrow job, and the
bots coordinate by exchanging typed artifacts, not conversation. A coordinator
bot keeps the day-to-day order; anything needing a human decision escalates
through Muse to Martin, and Martin's decisions feed back into the brain, the
code, or the instructions — which is how the system improves. Nothing
important lives inside any vendor's bot.

## 2. Where things live (repository topology)

Four homes, each with one job. This separation is the architecture's
load-bearing wall: behavior, loop code, knowledge, and system wiring evolve
independently and are owned by different repos.

- **dotai — agent behavior.** The instruction stack. It contains the AGENTS.md
  (and drives CLAUDE.md and every other client's native instruction files)
  that tells agents how to work: the baseline critical rules — route coding
  to Cursor agents on composer/cheap models, plan-and-review before merge,
  no silent fallbacks — and the instructions to use the brain: what to load
  once, what to query on demand. Behavior changes are made here and nowhere
  else.
- **personal-triage — loop code.** The deterministic engines the role bots
  run (today: the `triage/` fetch/plan/render/verify core and its
  successors). No behavior prose, no system wiring; it is a code repo. It
  stays the loop's home — there is no reason to move away from it unless a
  later evaluation determines something else is better.
- **The brain (Notion) — knowledge and persistence.** A discoverable database
  of principles, rulings, and knowledge that doubles as the system's
  persistence layer and auto-improves: bots write back what they learn, the
  Librarian mines Martin's corrections into proposed updates. It is never
  copied into a repo; agents reach it through dotai's instructions, so only
  the access pattern lives in dotai, never the content. **Restructuring the
  brain itself for discoverability and performance is a separate
  workstream** (PERSO-664 and successors) — this proposal depends only on
  the access pattern, not on that restructure being done first.
- **gentlemen-bastards (the system repo, new; named by Martin for the book series) — the running system.** Composition and wiring:
  the bots' definitions and schedules, the message protocol, the generator
  that projects dotai into each runtime's native format, ledger locations,
  and the deployment/GitOps manifests. It consumes dotai (behavior),
  personal-triage (loop code), and the brain (via dotai's instructions). It
  contains neither the behavior source nor the loop code itself. This
  proposal becomes its first document; its name is Martin's call.

## 3. Roles

- **Martin** — principal. Answers questions, reviews what is gated for review,
  sets principles and budgets. Should never have to live in Linear or read raw
  run logs.
- **Muse (thin layer)** — interface + orchestration only:
  - converse with Martin; raise questions, digests, and exceptions proactively
  - supervise the swarm and the engineering agents; start, stop, and inspect
    them
  - carry decisions between Martin and the Coordinator, in both directions
  - direct and review the self-hosted engineering work (specs in, diffs and
    PRs reviewed before merge)
  - create and manage the Linear tickets and Notion brain entries
  - watch run ledgers and budgets; flag drift, failures, and cost anomalies
  - Explicitly NOT: the scheduler, the store of record, or a stateful bot whose
    chat context the loop depends on. Loop state lives in files, Linear, and
    Notion — never only in a conversation.
- **The role bots** — the loop itself, as self-hosted agents. See §5.
- **Specialized agents** — spawned per task class, configured before they run
  (see §7). Examples: a coding agent (Cursor via cursor-delegate), a research
  agent, a plan reviewer. Each is short-lived and disposable.
- **Engineering agents** — self-hosted agents that build and maintain the
  system itself. See §4.

## 4. Self-hosted engineering agents

Martin builds these agents (with Muse directing and reviewing); they live in
his cluster and accumulate native experience with his stack that no hosted
bot has. The role bots in §5 are their siblings — same population, different
job descriptions.

- **Job:** the system's own engineering and operations work — GitOps
  migrations, infrastructure changes, maintenance — executed as PRs against
  the repos, never as direct mutation. Pilot task: the Tailscale tailnet
  policy GitOps migration and ACL tightening already tracked as PERSO-723.
- **Working pattern:** Muse writes the spec (per dotai's delegation rules),
  the agent implements in its environment, an independent review checks the
  result including the repo's own CI, and only then does anything merge.
  This is the pattern proven on 2026-11-08 with the homeops Tailscale PRs,
  made permanent.
- **Governance:** same rules as every agent here — behavior from dotai,
  instructions enforced at construction (system prompt, tool allowlist,
  budget), tools reached through personal-mcp and the cluster's own APIs,
  every run in the ledger. Writes to production-shaped things go through the
  PR gate; there is no direct-apply path.

## 5. The loop as a swarm

Each former stage is a resident bot with its own instructions (from dotai),
its own schedule and event triggers, and a narrow job. Working names below
are strawmen — Martin renames at will; what matters is that the names are
jobs, not pipeline stages.

- **Scout** (was SENSE) — watches Gmail, Calendar, Linear. Deterministic
  fetch and rule-based classification; emits a *Snapshot*. Read-only tools.
- **Planner** (was PLAN) — turns Snapshots into a *Plan*: an explicit,
  ordered list of proposed writes plus *Questions* it cannot resolve. Runs
  the deterministic engine; a bounded model call only at genuine judgment
  points. Cannot write.
- **Writer** (was ACT) — the only bot holding write tools, and the name says
  so. Applies Plan items, verifies each by read-back, emits *Receipts*.
  Accepts only a Plan artifact; has no fetch tools.
- **Herald** (was DIGEST) — renders what Martin sees: digests, urgent pings
  (the old Groko-sweep function, folded in), and the Questions queue. Talks
  to the Coordinator and Muse, never writes to the world.
- **Librarian** (was MAINTAIN) — tends the brain and the backlog: files what
  the bots learned, dedupes, proposes principle updates from Martin's
  corrections (suggest-only; Martin approves), trims stale tickets.
- **Coordinator** — keeps order without becoming a bottleneck. The happy
  path is peer-to-peer (Scout → Planner → Writer by artifact handoff); the
  Coordinator handles scheduling nudges, retries, stuck-bot detection, and
  every exception or decision. It is the only bot that escalates, and it
  escalates to Muse, who carries decisions to Martin.

**How bots communicate — typed artifacts, never chat.** Bots exchange a
small set of artifact types (Snapshot, Plan, Question, Receipt, Report)
through a durable store — files in the system repo's data area, a queue, or
Linear itself, decided at build time — and every exchange is written to the
run ledger. No bot's memory is another bot's input; state lives in the
artifacts, Linear, and the brain. This is the line between a swarm and the
Grok-era failure mode: free-form agent chatter is how context explodes and
accountability for a write disappears. Here, every write traces to a Plan,
and every Plan to a Snapshot.

**Live consultation — the controlled exception.** Artifacts are the system of
record, but a bot mid-task may need an answer *now*: Writer hits an ambiguous
Plan item; Scout spots something urgent off-schedule. So bots also have a
synchronous consult channel, kept clean by construction:

- A consult is a typed question about one referenced artifact item, answered
  from the answerer's own context. No transcripts are shared — context
  pollution travels through shared memory, and consults share none.
- **Advice crosses; authority does not.** A consult can inform a bot, never
  arm it. Writer may ask Planner "is this the right issue?"; it cannot ask
  Scout to fetch for it — no channel grants a capability.
- Every consult and answer is written to the run ledger, so live help stays
  as auditable as the artifacts.
- Consults are budgeted per run (count and timeout). Budget exhausted: the
  bot parks the item as a Question artifact and continues with the rest —
  live flexibility degrades gracefully into the asynchronous path instead of
  deadlocking.
- Human decisions are never consulted peer-to-peer. A bot needing Martin
  still goes Coordinator → Muse → Martin, so he gets one aggregated queue
  (via Herald), not five bots asking questions at 3 a.m.

**Inside each bot, the same discipline:** a deterministic core doing the
mechanical work, with a model invoked only where judgment is genuinely
needed. "Agent" describes the deployment and communication shape — resident,
addressable, able to raise its hand — not a license to replace code with
prose. Each bot runs on its own routines (schedule + event triggers), so a
stuck bot blocks nobody: the old design's single global writer, where one
stalled loop froze everything, does not exist here.

**The feedback loop.** When a bot needs a decision, the Question travels
Coordinator → Muse → Martin. Martin's answer flows back down and lands in
one of three places, chosen deliberately: the **brain** (a principle or
ruling), **personal-triage** (a code fix), or **dotai** (an instruction
change). The Librarian proposes; Martin approves; the system compounds.

## 6. How the bots are built (runtime decision)

**The bots run on an adopted agent framework — used selectively, configured
from our repos, and treated as a replaceable provider.** A plain Kubernetes
workload is a process supervisor, not an agent runtime: the agent loop,
inter-bot communication, session handling, scheduling/event triggers, and
live consults that §5 requires are a product in themselves. Building them
would recreate the machinery-building trap this architecture exists to
escape (the old system's ~30 supervision modules are the warning). So the
framework provides the runtime; we decline the rest of its opinions:

- **Used:** agent loop and tool calling, bot hosting (several distinct bots
  with separate identities and configs), scheduling and event triggers,
  inter-bot messaging and the consult channel, session/context handling.
- **Not used by default:** its persona/assistant features and any hosted
  tier. Its memory/second-brain layer is a live candidate, not a rejection:
  if a framework's brain layer beats the current Notion setup on
  discoverability, query performance, write-back, and portability, we adopt
  it — the brain workstream (§2) decides on merit. The guardrail is
  Martin's own principle: whatever store wins stays behind dotai's access
  pattern and remains fully exportable. The interface is permanent; the
  store is negotiable.
- **Ours, not its:** bot definitions live in the system repo, generated from
  dotai (role, instructions, tool allowlist, model, budget, consult rights);
  the deterministic cores from personal-triage are exposed to the bots as
  tools, so the mechanical work stays code even inside an agent runtime.
- **Replaceable:** if the framework degrades or its roadmap turns, the bots'
  definitions, the artifacts, the gateway, and the brain survive; swapping
  the runtime is a provider change (the dotai pattern), not a rebuild.

**Evaluation outcome and decision (2026-11-08): the runtime is Hermes
Agent.** The docs-and-repos evaluation eliminated Rakazo first — bot
definitions live in Postgres/UI rather than git and its built-in memory
cannot be replaced, against two stated guardrails, on top of beta/pre-1.0
status. Hermes vs OpenClaw scored genuinely close (Hermes: strongest
MCP/tool granularity, GitOps-able profile distributions, healthiest
stewardship; weaknesses: single-host gateway, self-rewriting config
defaults, no synchronous consult between persistent bots. OpenClaw:
cleanest git story, only native synchronous consult, best observability;
weaknesses: gateway-global MCP registry, extreme churn). Martin decided
to bet on Hermes — the evaluation's lean, plus good reports from friends —
rather than spend the effort on a two-framework bake-off. The Scout spike
in §13 therefore validates the chosen runtime instead of comparing two.
Hermes' single-gateway "big pod" topology is accepted: the cluster runs
it comfortably, and the real caveat is blast radius, handled by GitOps
redeploy and configuration locks, not capacity. OpenClaw remains the
documented fallback if the spike fails — per the replaceable-runtime
principle, switching costs a provider change, not a redesign: bot
definitions, artifacts, gateway, and brain are all ours. Cross-cutting,
for all three frameworks: no native typed-artifact consults (a convention
on top, as designed), no per-bot hard budget caps (enforcement stays at
the gateway/provider, as designed), and no Kubernetes-native control
plane (one stateful workload hosts the swarm in every case).

On the second-brain question: **none of the three frameworks' memory beats
the Notion brain on merit** — all three are small flat notes or chat memory
(Rakazo caps at 4 KB per bot), and none offers structured, field-filtered
queries over a principles corpus. The brain stays in Notion; framework
memory is disabled or cache-only; bots reach the brain via MCP under
dotai's access pattern. (Hermes/OpenClaw can host a small curated core and
beat Notion on that core's portability — a composition the brain
workstream may still choose.)

Because the runtime is borrowed, enforcement concentrates where we have
total control: the gateway (§7, §8). A bot that misbehaves inside its
framework still cannot call a tool the gateway does not allow it, write an
artifact that fails schema validation, or act unlogged.

## 7. Enforcement model (the dotai problem)

Rules are split by how they are enforced, weakest mechanism last:

1. **Capabilities and code, enforced at the gateway.** What must never
   happen is made impossible: per-bot tool allowlists held server-side at
   the personal-mcp gateway (Scout cannot write; Writer cannot fetch —
   whatever runtime a bot lives in), typed artifact schemas validated on
   write, budget caps that halt a bot, write gates on the Plan, and a ledger
   line written by the gateway for every tool-mediated action, so the audit
   trail does not depend on the bot's own honesty. Prose is never the only
   guard.
2. **Instructions configured at construction.** Every bot and agent gets its
   instructions in its definition, generated from dotai — not from files it
   is trusted to open. Each job carries: a self-contained spec, numbered
   requirements, an acceptance checklist, the tool allowlist, a model
   choice, and a budget. Per dotai: no delegation of exploration, debugging,
   or anything touching secrets or production; no silent fallback to another
   engine — a blocked bot stops and reports NEEDS_EVIDENCE.
3. **Small injected guidance.** A load-once core (the principles, pulled from
   the brain per dotai's instructions) plus the task-relevant slice.
4. **Verification.** Deterministic read-back after writes; diff review before
   merges; an append-only run ledger recording artifacts, writes,
   verification results, tokens, and estimated cost per bot per run (the
   dotai usage.jsonl pattern, generalized). A run that fails verification is
   not done, whatever the bot says.

The generator lives in the system repo and projects dotai per runtime:
AGENTS.md + symlinks + hooks for laptop clients, bot definitions for the
swarm, skill + job instructions for Muse's scheduled work, and agent
definitions for the engineering agents. Deployed instruction sets carry a
version/hash of the dotai source so drift is diffable instead of discovered
by vibes.

Hosted bots with no injection point and no capability limits (the Grokbot
shape) are disqualified as drivers or rule-holders. At most they may be
clients of well-defined APIs.

## 8. Tools and the gateway

- Gmail, Calendar, Linear, Notion: official MCP connectors where they exist.
- personal-mcp is the agent tool gateway for everything without an MCP —
  today chiefly Monarch Money (retire that half if Monarch ships an official
  MCP) — and for capabilities the bots need in a uniform shape.
- Repos are the source of truth for machinery; Notion holds the brain;
  Linear holds every follow-up task. No state of consequence lives in chat.

## 9. Vendors and cost (decided 2026-11-08)

- **Grok Bot: out.** No role.
- **Cursor: coding executor only**, inside the prepaid plan (~$60/mo yearly,
  sunk). Usage is routed and ledgered per the dotai pattern; no on-demand
  overage, no renewal without a fresh decision. Refunds for the prepaid year
  are effectively unavailable (Cursor: 14-day/no-usage only; xAI: terms say
  non-refundable, case-by-case form exists).
- **Muse: the thin layer** ($0 marginal).
- **Claude Pro (+$20/mo): standing fallback** — an alternate interface/driver
  of last resort (the proven routines-era shape) and an independent second
  reviewer. Total new spend: $20/mo, well under the ~$100/mo budget line.

## 10. Portability and exit

Every asset lives in Martin's repos, Notion, or Linear. The proposal includes
an exit runbook (to be written as a build step): the exact procedure to
re-point the system if Muse disappears — the swarm keeps running (it never
depended on Muse to execute), and a replacement interface only needs the
Coordinator's escalation contract. Muse's replaceability is a tested
property of the system, not a hope.

## 11. What gets retired

- Cursor Automations as the loop driver (definitions in `infra/` are evidence
  of the old era; they get disabled at cutover, after dashboard verification).
- The 181 KB prose runbook and the lease/checkpoint supervision labyrinth —
  machinery that existed to supervise an unreliable driver.
- Groko sweep as a separate bot (function folded into the Herald).
- Ambiguous run state: SHADOW vs LIVE becomes explicit per-bot config
  (PERSO-699).
- The stage names SENSE/PLAN/ACT/DIGEST/MAINTAIN.

## 12. Open verifications before build

1. Cursor dashboard: which automations are actually enabled in Cursor's
   cloud, today's run history and failure messages (the API cannot show
   this; needs one browser pass with Martin's sign-in).
2. claude.ai: whether any historical routines remain enabled there.
3. The "operator box" holding tofu state and CURSOR_TOKEN: locate it, or
   declare the tofu layer abandoned and manage Cursor purely via dashboard
   until it is phased out of the loop entirely.

## 13. First build steps (become the PERSO project, once approved)

1. Create the system repo (dels78/gentlemen-bastards); this proposal
   lands as its first document.
2. Dashboard + claude.ai verification pass (§12).
3. Define the artifact protocol and bot definitions in the system repo;
   behavior contracts into dotai; wire the generator.
4. Spike: Scout on Hermes (definition from dotai, real inputs, SHADOW,
   memory disabled, tools via personal-mcp). Validate Plan quality, gateway
   fit, config-drift behavior with the self-modification locks on, and the
   consult convention. If the spike fails, fall back to the same spike on
   OpenClaw before reconsidering. Then Coordinator + Planner; Muse
   reviews Plans with Martin until they match expectations.
5. Add Writer for Linear writes, verify; then email actions; then Herald
   and Librarian on schedule.
6. Pilot the engineering agents on PERSO-723 (Tailscale policy GitOps).
7. Disable the Cursor automations; write the exit runbook; close or fold the
   ~18 scattered loop issues into the project.

## 14. Cutover discipline

Build the new system fully in parallel: the current Cursor-automation loop
keeps running untouched until the new system is proven. The invariant is:
**reads may overlap, writes never do** — at any moment exactly one system
may write to the user's accounts.

Graduation is staged:

1. **SHADOW** — the new bots read live data, but the gateway blocks every
   write. Plans are produced and reviewed against the old loop's behavior.
2. **Supervised LIVE** — once SHADOW Plans match expectations, the Writer is
   enabled, gated at first; in the same motion the old system's writing
   automation (ACT) is disabled, preserving the single-writer invariant.
3. **Full LIVE** — the Writer runs autonomously within its budgets.
4. **Retirement (build step 7)** — only at full LIVE are the remaining Cursor
   automations switched off: disabled, not deleted. The old system stays
   dormant and intact for a rollback window; re-enabling it is a toggle, not a
   rebuild. Final retirement comes later.
