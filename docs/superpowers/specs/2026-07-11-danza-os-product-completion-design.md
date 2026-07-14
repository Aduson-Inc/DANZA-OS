# DANZA-OS Product Completion — Design Spec

- **Date:** 2026-07-11
- **Status:** APPROVED DESIGN (pending user review of this document)
- **Layer:** 0 (OS_DEV) — this spec describes work ON the OS. Constitution runtime
  ceremony does not apply while building it; Rule 16 (no deletions without approval)
  and research-approval remain active.
- **Supersedes nothing.** Extends `2026-07-05-workstation-onboarding-design.md`
  (W1) by delivering its unbuilt P5 product shell, and completes distribution,
  multi-model routing, and end-to-end validation.

## 1. Mission

Turn DANZA-OS from a tested library collection into an installable product: a
user runs one terminal command in a fresh repo, onboards through a dashboard
that grills their idea until it is crystal clear, picks 1–5 AI CLI runners, and
the conductor relay builds a professional app — with CORTEX memory driving
agent context and keeping token cost visible and bounded.

**Acceptance (the whole spec is done when):** in a brand-new repo created by
the user — install one-liner → `danza init` → `danza ui` → dashboard
onboarding → `danza conduct` — the relay builds a small real app, CORTEX
captures and injects memory throughout, and the full OS test suite is green.

## 2. What already exists (verified 2026-07-11)

| Layer | State |
|---|---|
| Brain (`danzaboss/`): kernel, planning, memory, context, security, observability, orchestration, selftest, cortex (C1–C6 incl. UI on :33000), hooks, research, runtime | REAL, 733 tests green |
| Workstation W1 P1–P4: wizard engine + question tree, checkpoints (headless AI calls), reality-check research, spec compiler, plan validator, runner registry (claude/codex), tmux+headless session hosts, deterministic conductor loop with safety valves | REAL, tested, library-only |
| Prompt layer: 8 agents, constitution (45 rules), "Who's the Boss?" skill, CC hooks | REAL |
| W1-P5 product shell (dashboard, /onboard, /models) | NOT BUILT |
| Packaging / installer | NOT BUILT |
| Multi-model routing (who gets the next turn) | NOT BUILT (schema ready) |
| Adaptive AI interview ("grill until clear") | NOT BUILT (designed as future work) |
| End-to-end clean-install proof | NEVER RUN |

## 3. Decisions (locked with user, 2026-07-11)

| # | Decision | Choice |
|---|---|---|
| D1 | Install path | Both: pip package (`pipx install git+https://github.com/Aduson-Inc/DANZA-OS`) as primary, hardened `install.sh` curl|bash wrapper |
| D2 | Install source | GitHub at launch; PyPI later |
| D3 | Runners | Any detectable CLI (claude, codex, gemini, grok, opencode, …) via a known-runner catalog |
| D4 | Dashboard | One stdlib server: DANZA dashboard at `/`, CORTEX UI mounted at `/cortex`, redirect button in top bar |
| D5 | Onboarding surface | Web dashboard forms (`/onboard`) over the existing wizard engine |
| D6 | Grilling | Adaptive AI interview per wizard phase + clarity gate (max 3 follow-up rounds, then escalate to user) |
| D7 | Model routing | Deterministic routing table (work type → runner) set on `/models`; rotation fallback; no per-handoff AI routing calls |
| D8 | GSD borrowings | Auto-resume SessionStart hook only; nothing that duplicates DANZA's engine |
| D9 | CORTEX | Load-bearing in the product: dormant only in OS_DEV; doctor fails if dormant in an activated repo; E2E test asserts capture + injection |
| D10 | Token economy | Single source of truth for role budgets, tunable with tested floors; interview rounds capped; per-turn/per-agent telemetry on dashboard |

## 4. Architecture

One Python package, stdlib only, one server process for the product UI.

```
danzaboss/
  product/                    NEW — packaging & lifecycle
    scaffold.py               danza init: idempotent copy/merge of .claude/ + .danza/
    doctor.py                 danza doctor: env + profile + CORTEX + runner checks
    templates/                bundled scaffold payload (via importlib.resources)
  workstation/
    server.py                 NEW — DANZA dashboard (ThreadingHTTPServer, ADUSON design)
    static/                   NEW — index.html, app.css, app.js (CORTEX UI patterns)
    interview.py              NEW — adaptive follow-up generation + clarity gate
    routing.py                NEW — deterministic work-type → runner router
    runners.py                EXTENDED — known-runner catalog + auth probe
    conductor.py              EXTENDED — consumes routing decision on ignite
  cortex/  kernel/  ...       unchanged except budget reconciliation (§8)
pyproject.toml                NEW — zero deps, console script `danza`
install.sh                    NEW — hardened curl|bash wrapper
```

Data flow (product loop): `danza init` scaffolds state → `danza ui` serves
dashboard → `/onboard` walks wizard + interview → compiler writes
`.danza/spec.md` → planner writes `.danza/plan.json` → `/models` writes
`runners.json` + `routing.json` → `danza conduct` relays boss sessions, each
ignition carrying the routed runner → CORTEX captures observations and
compiles per-driver context → dashboard streams progress via SSE.

## 5. Phase 1 — Installable product

- `pyproject.toml`: `[project] name = "danza-os"`, zero runtime deps,
  optional extra `neon` (`psycopg[binary]`), `[project.scripts] danza =
  "danzaboss.cli:main"`. Package data includes scaffold templates.
- `danza init [dir]`:
  - Copies `.claude/` (agents, rules, skills, settings hooks) and `.danza/`
    (templates + bootstrap state) from bundled package data — copy, not
    symlink, so activated repos survive OS upgrades.
  - Idempotent: per-file result `created / merged / skipped(user-modified)`;
    never overwrites user-edited files (Rules 34–35 apply to the scaffold).
  - Appends a managed block (begin/end markers) to the target repo's
    `CLAUDE.md`, creating it if absent.
  - Stamps `.danza/.scaffold-version` for future `danza init --upgrade` diffs.
  - Installs the auto-resume SessionStart hook (D8): on session start in an
    activated repo, if `handoff.md` holds real data, the hook emits a
    "CONTINUE MODE — resume via 'Who's the Boss?'" context block.
  - Ends by running `danza doctor` and printing next steps.
- `danza doctor`: wraps selftest; adds checks — Python ≥ 3.10, git repo,
  scaffold integrity, runner detection summary, active profile, CORTEX state
  (FAIL if profile is APP_BUILD/OS_BOOT_TEST and CORTEX is dormant or its DB
  unwritable — D9).
- `install.sh`: `set -euo pipefail`, body inside `main()` invoked on last
  line, `curl -fsSL`, HTTPS only, `DANZA_VERSION` env pin (default: latest
  release tag), `DANZA_BIN_DIR`, `CONFIGURE=false` for CI, detects existing
  install and upgrades or no-ops, installs pipx if missing, then
  `pipx install git+https://github.com/Aduson-Inc/DANZA-OS@$DANZA_VERSION`.
- **Acceptance:** on this machine — fresh temp repo, `pipx install` from a
  local clone, `danza init`, `danza doctor` green; re-running `init` reports
  all-skip; suite green.

## 6. Phase 2 — DANZA-OS dashboard

> **STATUS: COMPLETE 2026-07-11 @20b02de** (plan:
> `docs/superpowers/plans/2026-07-11-phase2-danza-dashboard.md`). All
> acceptance criteria met; suite 821 green; final whole-branch review
> READY-TO-MERGE (0 Critical; the 1 Important — SSE change token missing
> runners.json/wizard state — fixed @0e77395). Deferred-minors triage
> recorded in `.superpowers/sdd/progress.md` under "Phase 2": fix-later =
> Rule-45 schema validation once the dashboard gains writes (P3/P4),
> conductor `limit` clamp+400, reverse-seek log tail if P4 telemetry grows
> the log, single-parse `/api/plan`, topbar overflow below ~930px; ignored
> (with reasons) = mount-snippet duplication, taskHTML esc pattern, Google
> Fonts CDN, positional-dir parse permutation, hidden-attr assertion.

- `danza ui [--port N] [--no-open]` → `workstation/server.py`, same
  construction as `cortex/ui/server.py`: ThreadingHTTPServer, static assets
  beside the module, JSON API, SSE heartbeat. Binds `127.0.0.1` only;
  default port 33100 (CORTEX keeps 33000); auto-opens browser.
- Visual identity: the ADUSON system verbatim — tokens copied from
  `cortex/ui/static/app.css` (`--void #0a0a0c`, `--carbon #141417`,
  `--gunmetal #3a3d44`, `--silver #9ba1ab`, `--crimson #c8102e`,
  `--ember #e8354f`, blade clip-path, Chakra Petch / IBM Plex, card +
  drawer + chip + tab patterns, background artwork treatment).
- Home screen: project identity, active profile, team-state (boss, turn,
  status), feature/plan progress, conductor log tail, CORTEX stats strip
  (observations, injected tokens, savings), token telemetry (§8).
- CORTEX mount (D4): dashboard process mounts the CORTEX UI handler under
  `/cortex/*` (delegating to the existing handler logic against the same
  store); top-bar button "CORTEX" navigates there; CORTEX UI gains a
  reciprocal "DANZA-OS" button. `danza cortex ui` standalone still works.
- Nav tabs: OVERVIEW · ONBOARD · MODELS · BUILD · CORTEX (redirect).
- **Acceptance:** `danza ui` in an activated repo serves all tabs; `/cortex`
  renders the real CORTEX feed; HTTP-level tests in the
  `test_cortex_ui.py` style.

## 7. Phase 3 — Onboarding that grills

> **STATUS: COMPLETE 2026-07-12 @89e29dc** (plan:
> `docs/superpowers/plans/2026-07-12-phase3-grilling-onboarding.md`). All
> acceptance criteria met; suite 868 green (14 skipped). Deferred-minors
> triage recorded in `.superpowers/sdd/progress.md` under "Phase 3".

- `/onboard` routes render the existing wizard flow (`tree.py` P0–P6 +
  research + checkpoints) as forms; `wizard.submit()` unchanged; revision
  rule (editing an approved phase stales downstream) surfaces in the UI.
- **Interview loop (new, `interview.py`):** after each phase submission, a
  headless boss call (existing `checkpoints.run_headless` plumbing) receives
  the phase answers + accumulated spec context and returns
  `{ambiguities: [...], follow_up_questions: [...], clear: bool}`.
  - `clear: false` → questions render as an extra form step; answers merge
    into the phase record; loop repeats.
  - Hard cap: 3 rounds per phase (D6). Still unclear → phase is flagged
    `needs_user_decision` with the open ambiguities listed; user resolves in
    the UI (their answer is final — no drift beyond the user's stated intent).
  - Clarity gate is enforced in `wizard`-adjacent control logic
    (deterministic), not by the AI: a phase cannot reach `approved` while
    `ambiguities` is non-empty and rounds < cap.
  - Degradation: boss CLI unreachable → interview marked degraded in
    spec.md appendix (same policy as checkpoints), wizard continues.
- Reality-check button and checkpoint verdicts render inline (existing
  `research.py` / `checkpoints.py`).
- Finish: compiler writes `spec.md`; planner produces validated
  `plan.json`/`plan.md`; BUILD tab shows the task tree.
- **Acceptance:** hermetic tests with injected fake boss subprocess: unclear
  phase produces follow-ups, cap escalates to user, gate blocks approval,
  full run compiles spec + plan.

## 8. Phase 4 — 1–5 LLM conductor + token economy

> **STATUS: COMPLETE 2026-07-14 @e6c7415 + T13 verification fixes** (plan:
> `docs/superpowers/plans/2026-07-12-phase4-conductor-setup-token-economy.md`).
> All acceptance criteria met; suite 984 green (skipped=14); live Playwright
> eyeball green (SETUP renders agents/seats/dial; Confirm writes
> routing.json + budgets.json + runners.json and unlocks ONBOARD; ONBOARD
> locked panel shows before confirm; BUILD start gates on setup+plan; 0
> console errors). T13 fixes: bundled Tony D payload re-synced after the T8
> template line; `app.js` agentCard rendered `strengths` as a list — the
> catalog ships a plain sentence (crash found live, pinned in
> `test_danza_ui`).
>
> **Known limitation (final review 2026-07-14):** the dial + Advanced
> overrides persist to a validated `budgets.json` and display everywhere,
> but no runtime call site loads them yet — `driver_context.default_budget`
> resolves with the built-in "normal" dial, so "Full Power" does not change
> real driver budgets until a follow-up wires `load_budgets(root)` into
> `default_budget`/`danza cortex context`. Tracked in
> `.superpowers/sdd/progress.md` (Phase 4 close-out) as the first post-phase
> task.

> **Decisions locked with user (grilling, 2026-07-12)** — these refine the
> bullets below where they differ:
>
> | # | Question | Decision |
> |---|---|---|
> | 0 | Layers | Per-task stops = Layer-0 session discipline only; the OS never stops between its own build tasks |
> | 1 | Flow | Hard setup-first gate — ONBOARD locked until SETUP confirmed |
> | 2 | Conductor seat | Built-in deterministic conductor by default; AI conductor is an advanced opt-in (seat recorded, engine unchanged in v1) |
> | 3 | Seats | Conductor + 8 work types (plan/build/map/qa/review/research/design/security). NO Fast Scaffolder. Seats auto-suggested from per-model strengths; user approves or reassigns among connected models only |
> | 4 | Budgets | Dial = Normal / Full Power (no Economy). Floors protect quality; context/build quality never compromised |
> | 5 | Models | Each CLI runs as configured; per-seat model changes advanced-only, only where the catalog declares a safe flag |
> | 6 | Effort | The dial IS the effort control; per-seat effort advanced-only. v1 catalog ships empty `full_power_extra_argv` (plumbing present, no unverified vendor flags) |
> | 7 | Setup done | probe-passed agent + all seats assigned + dial set + conductor resolved → "Your team" card → Confirm writes validated files and unlocks ONBOARD; later edits apply from the next turn |
> | 8 | Dashboard | SETUP replaces MODELS; tab order OVERVIEW · SETUP · ONBOARD · BUILD · CORTEX; Advanced = collapsed section inside SETUP |
> | 9 | Language | Plain-English copy pass NOW, words only — wizard prompts, labels, buttons, user-visible errors |

> **Drift note (verified 2026-07-12):** the token-economy bullet below says
> the duplicate budget tables are `context/pipeline.py DRIVER_BUDGETS` +
> `cortex/driver_context.py DRIVER_CORTEX`. Reality: `DRIVER_BUDGETS` lives
> in `cortex/driver_context.py`; the actual duplicate was `DRIVER_CORTEX` in
> BOTH `context/pipeline.py` and `cortex/driver_context.py`. Task 4
> reconciled both tables into `cortex/budgets.py`, which both now import.

- **Known-runner catalog (`runners.py`):** claude, codex, gemini, grok,
  opencode + generic entry — each with binary name, interactive argv,
  headless argv (empty = unsupported, fail-closed as today), activation
  style. Auth probe: cheap headless no-op call at registry build; failures
  mark the runner `detected_unauthenticated` (visible on /models, excluded
  from lineups).
- **`/models` screen:** detected runners with auth status; lineup selection
  (1–5); routing table (D7): work types `plan · build · map · qa · review ·
  research · design · security` → runner; rotation fallback for unassigned
  types. Writes `.danza/runtime/routing.json` (validated, fail-closed).
- **Router (`routing.py`):** pure function
  `next_boss(routing, plan, state) -> runner_name` — reads the next
  dispatchable task's type from plan.json; deterministic and unit-tested;
  no AI calls.
- **Conductor integration:** on IGNITE, conductor consults the router for
  the session's runner argv; boss handoff prompts (Tony D template) name the
  routed next boss. Safety rails unchanged (valve, stall, orphan).
- **Dashboard BUILD tab:** start/stop relay (spawn/stop `danza conduct` as a
  managed subprocess), live team-state, session tail, conductor JSONL log
  stream.
- **Token economy (D10):**
  - Reconcile the duplicate role-budget tables — `context/pipeline.py
    DRIVER_BUDGETS` and `cortex/driver_context.py DRIVER_CORTEX` — into one
    module (`cortex/budgets.py`) both import. Defaults keep current tested
    values; floors prevent starving quality (no driver context below its
    tested minimum).
  - Budgets editable in dashboard settings (whitelisted keys, same pattern
    as CORTEX ui-settings.json); out-of-range values rejected.
  - Telemetry: conductor log events + CORTEX read-token stats aggregate into
    per-turn/per-agent token counts on the dashboard; savings shown next to
    spend so cost regressions are visible immediately.
- **Acceptance:** router unit tests (routing table, fallback, missing
  runner); registry tests for catalog + probe (injected `which`/subprocess);
  conductor loop test igniting two different fake runners across a handoff.

## 9. Phase 5 — Professional stack brain

2026 refresh of `workstation/templates/stacks/` (research-backed, 2026-07-11):

- `saas-ts`: Better Auth default (Auth.js noted as maintenance-mode), Neon/
  Supabase + Drizzle, Stripe, Vercel; Clerk tradeoffs recorded.
- `saas-python`: Django-shell/FastAPI-services decision rule; uv + Ruff +
  pytest toolchain.
- `static-site` / `content-site`: Astro 5 default; git-based CMS vs hosted
  headless fork keyed on "who edits content".
- `realtime-app`: staged path Supabase Realtime → Liveblocks/Yjs → Ably;
  10K-connection ceiling + polling fallback noted.
- `cli-tool`: Go + Cobra + GoReleaser distribution-first default; Python +
  Typer + uv alternative for data/AI audiences.
- NEW `ai-app`: Next.js + Vercel AI SDK + pgvector hybrid RAG (or FastAPI
  variant); eval-suite testing discipline.
- NEW `mobile-app`: React Native + Expo (EAS) default; Flutter alternative.
- Every template gains: `testing` block (unit + Playwright/Maestro + CI),
  `deploy` block (preview env, staging, rollback), and `build_order` hint —
  walking skeleton → auth → vertical slices in user-value order → QA →
  security review → deploy → handover. Planner prompt consumes
  `build_order` so generated plans follow professional sequence.
- **Acceptance:** template schema tests updated; planner test asserts plan
  ordering honors `build_order`; template JSON validated by existing loader.

## 10. Phase 6 — Prove it end-to-end

- **Clean-install harness** (`selftest/` extension + shell script): temp
  repo → pipx install from local checkout → `danza init` → `danza doctor` →
  scripted onboarding (fake boss subprocess) → routing config → `danza
  conduct --max-ticks N` with a stub runner that "builds" a trivial app and
  performs a real handoff → assertions: app files exist, verify passes,
  CORTEX captured observations and `cortex context --driver` returns
  non-empty budgeted blocks (D9), token telemetry recorded.
- **Live acceptance run (user-facing):** the user creates a real repo and
  runs the real flow with their installed CLIs; RUNBOOK gets the exact
  command sequence.
- Docs: README (install + quickstart), RUNBOOK (product flow), CLAUDE.md
  test-count/module sync.
- **Acceptance:** harness green in CI-style run on this machine; full suite
  green; docs match reality.

## 11. Cross-cutting rules

- **Stdlib only** in all OS code; optional extras never required for tests.
- **Fail closed:** invalid routing/registry/scaffold state raises; degraded
  AI calls are flagged, never silent.
- **Determinism:** router, clarity gate, scheduler decisions are pure and
  unit-testable; AI output is data they validate, never control flow.
- **No drift:** interview follow-ups clarify the user's stated idea; they
  never introduce features. Escalation puts the decision back with the user.
- **Style is law:** new modules mirror the closest existing module
  (`cortex/ui/server.py` for the dashboard, `runners.py` for the catalog).
- **Tests mandatory:** each phase lands with its tests; suite must be green
  at every phase boundary (tier-appropriate runs during development).

## 12. Non-goals (v1)

- No PyPI publication (GitHub install only, D2).
- No hosted/multi-tenant DANZA service; dashboard is localhost-only.
- No per-handoff AI model arbitration (D7 chose deterministic routing).
- No Claude Code plugin-marketplace packaging (noted as a cheap future
  channel; out of scope now).
- No mobile template execution engine changes beyond template data.
- No rewrite of existing tested libraries; extension only.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Non-claude CLIs vary in activation/headless behavior | Catalog is data + fail-closed; unauthenticated/unsupported runners excluded from lineups; stub-runner tests keep the relay honest without external CLIs |
| Interview loop burns tokens | Hard 3-round cap, budgeted prompts, telemetry makes spend visible |
| CORTEX mount conflicts (two handlers, one store) | Single process, one store handle; CORTEX standalone mode untouched; parity tests |
| Scaffold clobbers user state | Idempotent merge, `skipped(user-modified)` reporting, Rules 34–35 encoded in scaffold logic |
| E2E flakiness from real CLIs | Harness uses injected stub runners; live run is a separate user-facing acceptance, not CI |
