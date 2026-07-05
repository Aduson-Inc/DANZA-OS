# DANZA Workstation — Onboarding Dashboard & Conductor (W1)

**Date:** 2026-07-05
**Status:** Approved design (user-reviewed in session), pre-implementation
**Layer:** 0 work on Layer 1 — this extends the boot image; nothing here runs DANZABOSS in this repo
**Prereqs:** CORTEX C1–C6 complete (401 tests), CORTEX UI server pattern (port 33000), kernel scheduler dual modes, planning/decompose verifiable-task gate, kernel/tiers

---

## 1. What this is

A web workstation for DANZABOSS: one dashboard with a **"Who's the Boss?"** button
(*Start / continue project* beneath it) that onboards a user through a comprehensive,
revisable interview, compiles an approved `spec.md`, decomposes it into an ordered
plan of ≤30-minute verifiable tasks, ignites the AI boss session in a background tmux,
and relays turns automatically per a user-chosen cadence. CORTEX's existing UI mounts
inside it as a section. The UI never scrapes the terminal: all data flows through the
`.danza/` blackboard, exactly like the agents themselves.

**Audience decision (approved):** design flows/copy as the eventual product face of
DANZABOSS, implement with the cheap local stack now (stdlib server, no dependencies).

**v1 boundary (approved):** onboarding through ignition, plus a *minimal live strip*
(whose turn, feature #, checkpoint status from `team-state.json` polling). The full
live build view (agent cards, animated status, live task cross-off) is a separate
later phase.

## 2. Decision record (from the brainstorm)

| # | Decision |
|---|---|
| D1 | Design-for-users, build-cheap-local ("C"): product-quality flows, stdlib implementation |
| D2 | One server, one port, one process. Workstation is the shell; CORTEX UI mounts under `/cortex/` unchanged. CORTEX stays a feature of the OS, not a separate product; its external product surface is the MCP server (C6) |
| D3 | Onboarding is hybrid: deterministic wizard collects, AI checkpoints review (3 checkpoints + reality check). Full AI "Interview Mode" is future work |
| D4 | The button **spawns** the boss session (tmux) rather than attaching to a manually started one |
| D5 | Single runner in v1 (claude CLI); runner registry schema ships now so mixed models (codex, hermes, endpoints) land later as new runners, not a redesign |
| D6 | Cadence knob replaces hard-coded 2-features-per-turn: **relay-2** / **continuous-checkpointed** (default, N=4) / **supervised**. Requires Rule 3 amendment |
| D7 | The turn relay is closed by a deterministic **conductor** (postman, not boss): watches `team-state.json`, ignites sessions, never holds a turn. Hermes-as-intelligent-conductor (+ Telegram notify) is future work on the same seat |
| D8 | Reality Check (Phase 1.5): explicit, consented, cached web research on the user's idea via a provider interface (Tavily; headless-boss-with-web fallback). Restores Rule 29's mid-onboarding research in v1 |
| D9 | Non-app project types (design ideas, workflow, other, not-sure-yet) get lightweight **seed capture** in v1; full interview is app-building (website/SaaS) only |
| D10 | New scaffold state dirs ship in the boot image: `.danza/onboarding/`, `.danza/design/` |

## 3. Architecture

```
danzaboss/workstation/            NEW package (stdlib only)
  server.py       HTTP shell on port 33000 — nav, routing, static assets, SSE.
                  Thin view layer; mounts CORTEX UI handlers under /cortex/.
  wizard.py       Onboarding engine. Question tree as DATA (declarative structure),
                  phase state machine, downstream-stale invalidation, resume.
                  Pure library, no HTTP.
  checkpoints.py  AI checkpoint runner. Builds review prompt from answers-so-far
                  (+ user memory files when present, Rule 32), calls the boss CLI
                  headless (`claude -p --output-format json`) via an injectable
                  command, parses structured verdict, one retry on garbage,
                  degraded wizard-only mode if unreachable.
  research.py     Reality Check provider interface. v1 providers: Tavily (direct
                  API, stdlib urllib, key from /models screen or env) and
                  headless-boss-with-web fallback. Stubbed in tests.
  compiler.py     Approved answers → .danza/spec.md (existing spec_template.md
                  format) + design assets manifest + research digest inclusion.
  conductor.py    Deterministic relay daemon. Polls team-state.json (mtime ~2s),
                  spawns/ignites tmux sessions, pauses at cadence checkpoints,
                  surfaces blocks/stalls. Writes only conductor-log.jsonl.
  runners.py      Runner registry: role→runner config at
                  .danza/runtime/runners.json. v1 implements the claude CLI
                  runner (spawn-in-tmux + headless call). Schema supports
                  codex / hermes / endpoint runners later.
  templates/stacks/*.json   Stack template library (data, §5).
```

**Routes:** `/` dashboard (button, project status, seeds, live strip) ·
`/onboard/...` wizard · `/cortex/...` mounted CORTEX UI ·
`/models` runner detection + assignment + API keys ·
`/api/...` JSON · `/api/events` SSE.

**Data flow:**
1. Wizard writes incrementally to `.danza/onboarding/answers.json` (crash-safe resume).
2. Checkpoints and the Reality Check read answers-so-far; outputs render as wizard
   steps; research digest caches to `.danza/onboarding/research/`.
3. Final approval → `compiler.py` writes `spec.md` → headless planning call emits
   `plan.json`/`plan.md` → extended `planning/decompose.py` validates (§6) →
   button armed.
4. Ignition: conductor spawns tmux at the target repo root, sends "Who's the Boss?",
   then only watches `team-state.json`.
5. Live strip polls `team-state.json` + latest run log. No hook parsing in v1.

**Contracts:** wizard/checkpoints/research/compiler/conductor/runners are pure,
unit-testable libraries (no HTTP inside); `server.py` is the only web-aware module —
the same engine/UI split CORTEX uses. The conductor never reads the spec and never
holds a turn. The workstation operates **on a target repo** (project-root parameter,
like `danza scan`); it is factory equipment, not runtime state.

## 4. Onboarding flow & question tree

Question tree is data in `wizard.py`; evolving onboarding (Rule 21) = editing the
tree. Every phase revisable; left-nav shows phase status: draft / approved / **stale**.
Editing an approved phase marks downstream checkpoints stale for re-approval.
Approval at Phase 6 is the only gate that writes `spec.md` and arms the button.

- **Phase 0 — Project type.** Website · SaaS app · Design ideas · Workflow/automation ·
  Other · Not sure yet. Website/SaaS → full interview. Others → **seed capture**
  (name, intent paragraph, links/uploads → `.danza/onboarding/seeds/`, shown on the
  dashboard, convertible later). "Not sure yet" offers an idea-prompting exchange at
  one checkpoint call's cost.
- **Phase 1 — Concept.** What it does, who it's for, problem solved, similar products
  liked, editable must-have/nice-to-have feature list, explicit non-goals.
- **Phase 1.5 — Reality Check (explicit, skippable, cached).** "Run reality check"
  button → one research pass: direct competitors and near-substitutes, pricing,
  user complaints, recent entrants/shutdowns, whether the described angle exists.
  Renders a **Reality Digest**: competitor cards with links, differentiation
  assessment, and a verdict — **saturated/flawed** (evidence-backed pushback),
  **crowded-but-viable** (the wedge named), or **novel angle** (applause plus the
  closest adjacents so the claim is falsifiable). User revises concept (loop) or
  proceeds; proceeding past "saturated" is recorded in `spec.md` as an informed
  override. Digest feeds Checkpoint 1 and the final rundown, persists to
  `.danza/onboarding/research/`, and distills to a CORTEX observation for build-time
  Carmella. Concept edits mark the digest stale and offer a re-run (never silent
  re-spend). Research is never automatic: the click is the user approval external
  research requires in every profile.
- **Checkpoint 1 — Concept review.** AI reflects back "here's what I understand
  you're building" informed by the digest, flags contradictions and unstated
  assumptions, asks follow-ups that render as wizard steps. Loop until approved.
- **Phase 2 — Features.** Structured feature list (add/remove/rename/describe,
  MVP vs later) + capability checklist (accounts/auth, payments, admin,
  notifications, uploads, search, …). Auth/payments checked here plant the
  Rule 13–14 hard-stop flags honored at build time.
- **Phase 3 — Stack.** Template pick / custom / no preference. Custom → checkpoint
  validation with reasoned pushback + nearest template; the user can insist
  (recorded as user-overrode-recommendation). No preference → researched
  recommendation with trade-offs (Rule 30), never a silent pick.
  **Checkpoint 2** approves.
- **Phase 4 — Design.** Reference URLs, image uploads (→ `.danza/design/`), color
  direction (pick/upload/"propose for me"), style words, optional notes → `design.md`.
  No checkpoint — captured faithfully as Hank's build-time inputs.
- **Phase 5 — Practicalities.** Fresh vs existing repo (existing → scan before
  planning), deployment intent, **cadence knob** (default continuous-checkpointed,
  N=4), model-connect confirmation.
- **Phase 6 — Final rundown + Checkpoint 3.** Compiler assembles concept, features
  with priorities, approved stack, design summary (palette + asset thumbnails),
  reality digest, non-goals, cadence. Checkpoint renders the narrative rundown plus
  a gap list. Jump back and edit anything; approve → `spec.md`.

**Checkpoint contract:** one headless boss-CLI call returning
`{summary, concerns[], follow_up_questions[], recommendation, verdict}`; validated
on parse, one retry, degraded wizard-only continuation (flagged in spec) if the CLI
is unreachable.

## 5. Stack templates

A template is a data file (`workstation/templates/stacks/*.json`), fields:
`name, tagline, best_for, components (frontend/backend/database/ORM/auth/payments/
hosting), why, tradeoffs, avoid_when, testing_defaults, philosophy_fit`.

Rules: **combinations, never pinned versions** (planner resolves versions at build
time); **templates are data under evolution** (research/checkpoints may propose new
files; user approves; Rule 21).

Starting library (7): **Static site** (HTML/CSS/JS or Astro) · **Content site/blog**
(Astro + Markdown) · **SaaS Standard TypeScript** (Next.js + Postgres +
Prisma/Drizzle + Auth.js + Stripe — the recommended default when accounts+payments
are checked) · **SaaS Standard Python** (FastAPI + Postgres + SQLAlchemy +
React/Vite + Stripe) · **Lightweight app/internal tool** (Flask or FastAPI + HTMX +
SQLite; philosophy-purest; upgrade path noted) · **Realtime/collaborative**
(Next.js + Supabase) · **CLI/automation** (Python + Typer + SQLite, pipx). Mobile is
deliberately absent in v1 — the wizard says so honestly and captures a seed.

Selection: wizard filters by project type + capability flags, shows the fitting 2–3
(recommended first, tagline + why + tradeoffs). Checkpoint 2 grounds validation in
this library. `testing_defaults` seeds the planner's test policy (§6).

## 6. Decomposition engine

Pipeline at final approval:
`spec.md → headless planning call → plan.json + plan.md → machine validation
(extended decompose.py) → violations bounced back for re-split (max 3 rounds) →
approved plan → task list rendered, button armed.`
The AI proposes; deterministic code refuses bad breakdowns.

**Task record** (extends `plan_schema.json`):
`id` hierarchical `section.feature.task` (sections = app areas; stable references) ·
`kind` scaffold | backend | frontend | db-migration | integration | config | design |
test · `size_est` minutes, hard cap 30 · `depends_on` · `writes` (files/areas) ·
`verification` (one of the existing five concrete kinds — gate unchanged) ·
`flags` auth/payment/db-schema (Rules 13–15 surfaced at planning time: the rundown
says where the build will pause, no surprise mid-build stops).

**20–30-minute rule, enforced by proxy:** validator requires per leaf — ≤3 files
touched, one concern (conjunction-chained descriptions rejected), exactly one
verification, `size_est ≤ 30`. Oversized → "split this." Actual task durations are
recorded as CORTEX observations so estimates calibrate against reality via the C5
learning engine.

**Ordering:** deterministic topological sort over `depends_on` (tie-break: section
order, then id); cycles rejected; every task must follow its dependencies. `writes`
is captured per task so `orchestration/parallel.py` wave planning applies later;
v1 flattens to a linear order (single builder).

**TDD, right-sized** (from template `testing_defaults` + `kernel/tiers.py`):
1. Every leaf keeps a concrete verification, but verification ≠ unit test —
   scaffold/config verify at tier 0–1 (build passes, lint, boots).
2. Test-first only where behavior is spec'd (business logic, API endpoints, data
   rules); UI layout and glue get smoke/integration checks.
3. Regression = accumulation: written tests join the suite; Bonnie runs the cheapest
   safe tier per change set and the full suite at cadence checkpoints.

**Rule 3 tie-in:** a "feature" for turn counting = one feature node (e.g. `3.2`)
whose leaves passed the size gate. Cadence × size cap compose: continuous-checkpointed
N=4 = pause for the user every 4 verified feature nodes.

**Artifacts:** `.danza/plan.md` (human-readable numbered list; the UI right panel)
+ `.danza/plan.json` (scheduler + future live view).

## 7. Ignition & conductor

**/models screen:** detect installed runners (`claude` present+authed; `codex`
presence), pick the boss runner, write `.danza/runtime/runners.json`, set spawned
session permission mode (default: the repo's `.claude/settings.json` — the DANZA
template ships the hooks, so spawned sessions get governance automatically), enter
research API keys. No runner → button dark with the reason.

**The button (mode-aware, mirrors Rule 39):** no spec + "No handoff yet." →
onboarding · spec+plan approved + runner connected → **ignite** · real handoff data →
**Continue project** (resume relay) · awaiting checkpoint → **Approve & continue**.

**Ignition:**
```
tmux new-session -d -s danza-<project> -c <repo-root> '<runner cmd>'
tmux send-keys "Who's the Boss?" Enter
watch team-state.json + SessionStart marker
UI: "Igniting…" → "TONY DANZA! — system active"
```
UI displays `tmux attach -t danza-<project>`; optional pane pipe to a log file the
UI tails read-only (no parsing).

**Session-host abstraction:** the conductor's session-host is an interface (same
socket discipline as runners and research providers), not a tmux dependency. tmux is
the default POSIX implementation — it gives the boss session a persistent detached
terminal that survives dashboard restarts and browser closes and stays attachable
for human watch/intervene. The fallback implementation is **headless-per-turn**
(`claude -p "Who's the Boss?"` per relay turn) for hosts without tmux (native
Windows) or users who prefer invisible operation; it trades away attach-and-watch
only. The choice of host is orthogonal to how many LLMs are connected: one runner
means one session, whichever host implements it.

**Relay loop** (conductor polls team-state.json mtime ~2s):
`ready_for_<runner>` + cadence allows → spawn a **fresh** session (fresh context per
turn) and ignite · feature count hits N → `awaiting_user`: pause, show checkpoint
summary + Approve & continue (Telegram notify slots here later) · `blocked` (hard
stop or Rule 18 loop) → halt, surface reason from handoff/run log, wait.

**Safety rails (deterministic):** postman discipline (reads team-state, writes only
`conductor-log.jsonl`; never work files; never holds a turn — Rule 38 safe) ·
single-instance pidfile (two conductors would double-ignite) · stall detection
(no state/log change and no pane output for T minutes, default T=10 → surface,
don't auto-kill; Rule 33 machine-side) · dead-session valve (K=2 consecutive sessions exiting without
advancing `turn_number` → stop relay with report) · crash recovery (conductor is
stateless beyond its log; restart re-reads team-state and resumes — which is exactly
what makes the seat swappable for Hermes later).

## 8. Testing

Same discipline as the 401-test suite: stdlib unittest, hermetic, deterministic,
extends `run_tests.sh`.

- **Pure-library:** wizard state machine (transitions, downstream-stale, resume from
  partial answers.json) · compiler golden files (fixture answers → exact spec.md) ·
  decomposer validation (size proxies, cycle rejection, deterministic ordering) ·
  template library parse/required-fields.
- **AI without AI:** checkpoint runner takes an injectable command; tests use a stub
  binary returning fixture JSON — valid verdicts, garbage (retry), timeout (degraded
  mode). Research provider stubbed with fixture results — digest rendering, verdict
  paths, stale-on-edit, no-provider degraded path.
- **Server:** CORTEX UI pattern — endpoint unit tests on fixture state + ephemeral-port
  smoke test (every route 200s). Existing CORTEX UI tests pass unchanged (mount
  regression proof).
- **Conductor:** tmux/process spawning behind an injectable runner shim, injected
  clock — stall, valve, pidfile, relay transitions all deterministic against temp
  team-state fixtures. One env-gated live smoke (real tmux + stub script), skipped
  by default.
- **Hermeticity:** fixture repos in temp dirs only; never activates DANZA on
  DANZA-OS; never touches the real global CORTEX store; no network or API keys in
  the suite. `danza selftest` gains a workstation cold-start check (routes boot,
  templates parse, tree valid).

## 9. Constitutional amendments required (exact text proposed at implementation, user sign-off — Rule 37)

1. **Rule 3:** defer features-per-turn to the cadence in the approved spec
   (relay-2 / continuous-checkpointed default N=4 / supervised). Cap lives in
   `team-state.json` (scheduler already honors it).
2. **Rules 24/29–31:** recognize the workstation wizard as a valid completion of
   onboarding. With approved `spec.md` + `plan.json`, Tony D validates the spec on
   activation (completeness, scan if existing repo) instead of re-running the
   questionnaire. Rule 31's state-update gate still applies before build.
3. **File protection:** `.danza/onboarding/` and `.danza/design/` join the regime —
   answers/uploads are Rule 35 merge-only state; shipped stubs are Rule 34
   templates; `conductor-log.jsonl` is Rule 36 append-only.
4. **Rule 38 clarification:** the conductor is non-acting infrastructure (delivers
   ignition, reads state, holds no turn — no turn-lock violation); two conductors on
   one project are forbidden (pidfile-enforced).

## 10. Future work (explicit, out of v1)

- **Live build view (next phase):** hook-fed SSE events; right-panel task list
  crossing off live; active-agent cards with per-agent color, name, animated avatar,
  one-line status in Claude-Code-style playful language, feature # and status.
- **Interview Mode:** a live AI conducts onboarding as a conversation, using the
  question tree as its coverage checklist and writing the same `answers.json` —
  replaces only the collection surface; compiler/decomposer/artifacts untouched.
  (More checkpoint frequency is the intermediate dial: per-phase or per-answer
  review moves the design from hybrid toward full-AI without architecture change.)
- **Mixed-model dispatch:** implement additional runners (codex, endpoint runners);
  `danza dispatch <role> <task>` shim with hook-parity (explicit `danza cortex hook`
  + guard calls for non-Claude runners so governance and capture hold). UI warns
  when the orchestrator model is weaker than its drivers.
- **Hermes conductor:** an always-on intelligent conductor holding the same narrow
  seat — routing turns to the best model per work type (rules-based first), and
  messaging the user remotely (Telegram) with turn outcomes and approval requests.
  Telegram notify alone is a cheap earlier add to the deterministic conductor.
- **CORTEX separability:** unchanged stance — feature of the OS, MCP is its external
  surface; the mount keeps spin-out cheap if the market ever says otherwise.

## 11. Relation to prior audit findings (context, not scope)

The session audit that preceded this design found: per-driver spawn payload
~10–13k tokens; the CORTEX protocol block duplicated across 7 agent files
(~910 tokens); `system-map.md`/`decision-log.md` unbounded growth as the largest
token leak; CORTEX read-path honor-system (write-path machine-enforced via the
distillation Stop-gate). These are separate improvement candidates and are *not*
addressed by W1, except that W1's plan artifacts and conductor make turn behavior
more machine-checkable overall.
