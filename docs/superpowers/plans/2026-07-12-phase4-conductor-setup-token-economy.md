# Phase 4 — SETUP Gate, 1–5 LLM Conductor + Token Economy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app user's dashboard gains a hard setup-first gate (SETUP tab replaces
MODELS): connect 1–5 AI CLI agents, auto-suggest plain-English seat assignments from
each model's strengths, set a Normal/Full-Power dial, confirm the team — then, and
only then, onboarding unlocks; the conductor routes every turn to the seat-assigned
runner, the BUILD tab starts/stops the relay, role budgets get one floor-protected
home with visible per-turn/per-agent telemetry, and all app-user-facing copy reads in
plain English.

**Architecture:** Extend `workstation/runners.py` (catalog v2 + auth probe), add pure
`workstation/routing.py` (seats, suggestions, `next_boss`), add `cortex/budgets.py`
(single home for the duplicated driver tables + floors + dial presets), thread the
routing decision through `conductor.py` at IGNITE, and grow `workstation/server.py`
with `/api/setup` + `/api/build` routes following the Phase 3 `_POST_ROUTES` idiom.

**Tech Stack:** Python 3.10+ stdlib only; `unittest`; injected `which`/`subprocess`
doubles (tests never invoke real CLIs); ADUSON design system verbatim for UI.

## Global Constraints

- **Layer 0 discipline (user directive 2026-07-12):** the STOP at the end of every
  task is the *build session's* workflow (controller stops for the user's `/clear`).
  It is NOT product behavior — the shipped OS runs its build loop continuously.
- Suite baseline: **877 OK, skipped=14**. The full `./danzaboss/run_tests.sh` runs
  ONLY in Task 7 (midpoint) and Task 13 (final). Every other task runs ONLY its
  targeted test file(s).
- Every task carries a **Scope (pinned)** — the drift contract. The implementer does
  exactly that, nothing more (user clarification 2026-07-12).
- Stdlib only; fail closed (invalid registry/routing/budget state raises; degraded AI
  paths flagged, never silent); deterministic control logic; style is law
  (`runners.py` idiom for catalog, `cortex/ui/server.py` settings idiom, Phase 3
  `_POST_ROUTES` idiom).
- Plain-English rule: app-user-facing words are jargon-free; dev-facing text (CLI
  output, logs, spec.md/plan.md internals, CORTEX UI) stays technical.
- CORTEX stays dormant in OS_DEV; nothing here changes profile-gated capture.
- Commit after every task: `git add <files> && git commit` with a
  `feat(workstation): …` / `feat(cortex): …` message naming the task.

## Decisions locked with user (grilling, 2026-07-12)

| # | Question | Decision |
|---|---|---|
| 0 | Layers | Per-task stops = Layer-0 session discipline only; the OS never stops between its own build tasks |
| 1 | Flow | Hard setup-first gate — ONBOARD locked until SETUP confirmed |
| 2 | Conductor seat | Built-in deterministic conductor by default; AI conductor is an advanced opt-in (seat recorded, engine unchanged in v1) |
| 3 | Seats | Conductor + 8 work types (plan/build/map/qa/review/research/design/security). NO Fast Scaffolder. Seats auto-suggested from per-model strengths; user approves or reassigns among connected models only |
| 4 | Budgets | Dial = Normal / Full Power (no Economy). Floors protect quality; context/build quality never compromised |
| 5 | Models | Each CLI runs as configured; per-seat model changes advanced-only, only where the catalog declares a safe flag |
| 6 | Effort | The dial IS the effort control; per-seat effort advanced-only. v1 catalog ships empty `full_power_extra_argv` (plumbing present, no unverified vendor flags) |
| 7 | Setup done | probe-passed agent + all seats assigned + dial set + conductor resolved → "Your team" card → Confirm writes validated files and unlocks ONBOARD; later edits apply from the next turn |
| 8 | Dashboard | SETUP replaces MODELS; tab order OVERVIEW · SETUP · ONBOARD · BUILD · CORTEX; Advanced = collapsed section inside SETUP |
| 9 | Language | Plain-English copy pass NOW, words only — wizard prompts, labels, buttons, user-visible errors |

**Spec drift note:** design-spec §8 says the duplicate budget tables are
`context/pipeline.py DRIVER_BUDGETS` + `cortex/driver_context.py DRIVER_CORTEX`.
Reality (verified 2026-07-12): `DRIVER_BUDGETS` lives in `cortex/driver_context.py`;
the actual duplicate is `DRIVER_CORTEX` in BOTH `context/pipeline.py:74` and
`cortex/driver_context.py:36`. Task 4 reconciles both tables into `cortex/budgets.py`.
Task 13 amends spec §8 with this note and the decision table above.

## File structure

| File | Task | Responsibility |
|---|---|---|
| `danzaboss/workstation/runners.py` | 1, 2 | Catalog v2 (display names, strengths, suggested seats, activation) + auth probe + registry build |
| `danzaboss/workstation/routing.py` (NEW) | 3 | Seats, kind→work-type map, suggestions, routing.json persistence, `next_boss` |
| `danzaboss/cortex/budgets.py` (NEW) | 4 | DRIVER_CORTEX + DRIVER_BUDGETS single home, floors, dial presets, budgets.json persistence |
| `danzaboss/workstation/server.py` | 5, 9, 11 | `/api/setup`, setup gate on onboarding routes, `/api/build`, telemetry payload |
| `danzaboss/workstation/static/*` | 6, 10, 12 | SETUP tab UI, BUILD tab UI, copy pass |
| `danzaboss/workstation/conductor.py` | 8 | Per-ignite routing consult + activation phrase |
| `danzaboss/cortex/events.py`, `cortex/commands.py` | 11 | Context-read telemetry recording |
| `danzaboss/workstation/tree.py` | 12 | Wizard prompt copy (words only) |
| `.claude/agents/tony-d-orchestrator.md` | 8 | One handoff line naming the routed next boss (user-approved Rule-37 edit) |

---

### Task 1: Runner catalog v2

**Scope (pinned):** `KNOWN_RUNNERS` gains gemini/grok/opencode/generic entries and
every entry gains `display_name`, `strengths`, `suggested_seats`, `activation`,
`full_power_extra_argv`; `SCHEMA_VERSION` 1→2 fails closed on stale runners.json.
Nothing consumes the new fields yet.

**Files:**
- Modify: `danzaboss/workstation/runners.py`
- Test: `danzaboss/tests/test_workstation_runners.py` (extend)

**Interfaces:**
- Consumes: existing `KNOWN_RUNNERS` / `validate_config` shapes.
- Produces: `KNOWN_RUNNERS[name]` dict with keys `kind, binary, display_name,
  strengths, suggested_seats, activation, full_power_extra_argv, interactive,
  headless`; `SCHEMA_VERSION == 2`. Consumed by Tasks 2, 3, 5, 8.

**Catalog data (exact):**

```python
SCHEMA_VERSION = 2

KNOWN_RUNNERS: dict[str, dict] = {
    "claude": {
        "kind": "cli", "binary": "claude",
        "display_name": "Claude Code",
        "strengths": "Deep reasoning, complex building, careful review",
        "suggested_seats": ["plan", "build", "review", "security"],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": ["claude"],
        "headless": ["claude", "-p", "--output-format", "json"],
    },
    "codex": {
        "kind": "cli", "binary": "codex",
        "display_name": "Codex",
        "strengths": "Fast, focused code edits",
        "suggested_seats": ["build", "qa"],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": ["codex"],
        "headless": [],
    },
    "gemini": {
        "kind": "cli", "binary": "gemini",
        "display_name": "Gemini CLI",
        "strengths": "Long-context research and summarizing",
        "suggested_seats": ["research", "map"],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": ["gemini"],
        "headless": [],
    },
    "grok": {
        "kind": "cli", "binary": "grok",
        "display_name": "Grok CLI",
        "strengths": "Quick answers and fast iteration",
        "suggested_seats": ["qa", "research"],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": ["grok"],
        "headless": [],
    },
    "opencode": {
        "kind": "cli", "binary": "opencode",
        "display_name": "OpenCode",
        "strengths": "Flexible open-source coding",
        "suggested_seats": ["build", "design"],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": ["opencode"],
        "headless": [],
    },
    # Copy-me template for any other CLI. Empty binary => never detected;
    # excluded from detect_runners results and from lineups.
    "generic": {
        "kind": "cli", "binary": "",
        "display_name": "Custom agent",
        "strengths": "",
        "suggested_seats": [],
        "activation": "argv",
        "full_power_extra_argv": [],
        "interactive": [],
        "headless": [],
    },
}
```

- `detect_runners` skips entries with empty `binary` (generic is never "detected").
- `_REQUIRED_RUNNER_KEYS` grows to include the five new keys; `validate_config`
  additionally requires `activation in ("argv", "typed")` and list-of-str for
  `suggested_seats` / `full_power_extra_argv`.
- Version check message must tell the user to regenerate in Setup:
  `runner config version 1 != expected 2 — open the dashboard SETUP tab to
  reconnect your agents`.

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_workstation_runners.py`:
  `test_catalog_has_five_real_runners_plus_generic`,
  `test_every_entry_carries_v2_fields`,
  `test_generic_is_never_detected`,
  `test_v1_config_rejected_with_setup_hint`,
  `test_bad_activation_rejected`.
- [ ] **Step 2:** `python3 -m unittest danzaboss.tests.test_workstation_runners -v` → new tests FAIL.
- [ ] **Step 3:** Implement the catalog + validation changes above.
- [ ] **Step 4:** Targeted file green (existing tests updated only where they assert
  v1 shapes — e.g. version numbers in fixtures).
- [ ] **Step 5:** Commit `feat(workstation): runner catalog v2 — five CLIs + generic, strengths + activation (P4 T1)`.
- [ ] **Step 6: STOP.** Report done; wait for user `/clear`. Do not start Task 2.

---

### Task 2: Auth probe

**Scope (pinned):** `probe_auth(entry, run)` runs one cheap headless no-op with an
injectable subprocess; `build_registry(which, run)` returns a full config whose
entries carry `auth: "ok" | "unauthenticated" | "unprobed"`. Headless-less runners
are `unprobed`. `validate_config` rejects an `unauthenticated` boss. Nothing else
consumes the field yet.

**Files:**
- Modify: `danzaboss/workstation/runners.py`
- Test: `danzaboss/tests/test_workstation_runners.py` (extend)

**Interfaces:**
- Consumes: Task 1 catalog fields.
- Produces: `probe_auth(entry, run=subprocess.run) -> str`,
  `build_registry(which=shutil.which, run=subprocess.run) -> dict` (a
  `default_config` result with per-entry `detected` + `auth`),
  `entry["auth"]` vocabulary. Consumed by Tasks 3, 5.

**Design:**
- Probe command: `entry["headless"] + ["Reply with the single word: pong"]`,
  `run(..., capture_output=True, text=True, timeout=30)`. Exit 0 → `"ok"`;
  nonzero / `OSError` / `subprocess.TimeoutExpired` → `"unauthenticated"`.
  Empty headless argv or not detected → `"unprobed"` (no call made).
- `default_config` stamps `auth: "unprobed"` on every entry so existing callers
  and old tests keep a valid shape; `build_registry` = detect → default_config →
  probe pass over detected+headless-capable entries.
- `validate_config`: `boss` whose entry has `auth == "unauthenticated"` raises
  (`RunnerError`). ("Not in a lineup" is routing.json's check, Task 3.)

**Steps:**

- [ ] **Step 1: Failing tests:** `test_probe_ok_on_zero_exit`,
  `test_probe_unauthenticated_on_failure_timeout_oserror` (3 doubles),
  `test_unprobed_when_headless_empty_or_undetected`,
  `test_build_registry_stamps_auth`, `test_unauthenticated_boss_rejected`.
- [ ] **Step 2:** Run targeted file → FAIL.
- [ ] **Step 3:** Implement; injectable `run` mirrors `detect_runners`'s
  injectable `which` idiom.
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): auth probe + build_registry auth statuses (P4 T2)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 3: Router

**Scope (pinned):** New pure module `routing.py`: seat vocabulary, kind→work-type
map, strengths-based `suggest_seats`, validated `.danza/runtime/routing.json`
save/load, and `next_boss(routing, plan_data, state)` with rotation fallback.
No conductor or server wiring.

**Files:**
- Create: `danzaboss/workstation/routing.py`
- Test: `danzaboss/tests/test_workstation_routing.py` (new)

**Interfaces:**
- Consumes: `KNOWN_RUNNERS` order + `entry["suggested_seats"]`/`entry["auth"]`
  (Tasks 1–2), `TASK_KINDS` (`danzaboss/planning/decompose.py`),
  `TeamState` (`danzaboss/kernel/state.py`), plan.json shape
  (`planner.plan_payload`: `{"spec_ref", "tasks", "order"}`).
- Produces (consumed by Tasks 5, 8):

```python
ROUTING_RELPATH = Path(".danza") / "runtime" / "routing.json"
SEAT_WORK_TYPES = ("plan", "build", "map", "qa", "review",
                   "research", "design", "security")
SEATS = ("conductor",) + SEAT_WORK_TYPES
BUILTIN_CONDUCTOR = "builtin"
KIND_TO_WORK_TYPE = {"scaffold": "build", "backend": "build",
                     "frontend": "build", "db-migration": "build",
                     "integration": "build", "config": "build",
                     "design": "design", "test": "qa"}

class RoutingError(ValueError): ...

def suggest_seats(config: dict) -> dict: ...      # all 9 seats filled
def validate_routing(routing: object, config: dict) -> dict: ...
def save_routing(root, routing: dict, config: dict) -> Path: ...
def load_routing(root) -> dict: ...
def next_boss(routing: dict, plan_data: dict, state: TeamState) -> str: ...
```

**Design:**
- routing.json schema (version 1):
  `{"version": 1, "lineup": [1–5 runner names], "seats": {seat: runner-or-"builtin"}}`
  — `seats` covers ALL 9 seats; only `"conductor"` may be `"builtin"`.
- `validate_routing` (fail-closed): version, lineup 1–5 unique names, every lineup
  member exists in `config["runners"]` with `detected` true and
  `auth != "unauthenticated"`, seats keys == `SEATS` exactly, every non-conductor
  seat value ∈ lineup, conductor value ∈ lineup ∪ {"builtin"}.
- `suggest_seats(config)`: connected = detected ∧ auth ≠ unauthenticated, in
  KNOWN_RUNNERS order. For each work type pick the first connected runner listing
  it in `suggested_seats`; unlisted seats fall back to the first connected runner.
  `conductor` → `"builtin"` (Decision 2). Deterministic; raises `RoutingError`
  when nothing is connected.
- `next_boss` (pure, no I/O): the v1 progress cursor is
  `idx = state.turn_number * state.max_features_per_turn`, clamped into the
  feature list `planner.feature_nodes(order-leaves)`; the cursor feature's first
  leaf gives the kind → `KIND_TO_WORK_TYPE` → `routing["seats"][work_type]`.
  A `"builtin"`/missing seat value (hand-edited file) falls back to rotation:
  `lineup[state.turn_number % len(lineup)]`. Unknown kind → `RoutingError`.
  Docstring documents the cursor as a v1 proxy (task-completion tracking is a
  later phase).
- `save_routing`/`load_routing`: atomic tmp→`os.replace` write and
  missing-file/invalid-JSON errors verbatim in the `save_runners`/`load_runners`
  idiom, with messages pointing at the SETUP tab.

**Steps:**

- [ ] **Step 1: Failing tests:** suggestion fill + determinism + no-connected
  raise; validate rejects (6-runner lineup, unauthenticated member, missing seat
  key, non-lineup seat value, non-conductor "builtin"); `next_boss` table hit,
  rotation fallback, cursor clamp at plan end, unknown-kind raise; save/load
  round-trip + missing-file message.
- [ ] **Step 2:** `python3 -m unittest danzaboss.tests.test_workstation_routing -v` → FAIL.
- [ ] **Step 3:** Implement `routing.py` (module docstring states the why + the
  v1 cursor rule).
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): deterministic seat router + routing.json (P4 T3)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 4: Budgets module

**Scope (pinned):** New `cortex/budgets.py` = single home for `DRIVER_CORTEX`,
`DRIVER_BUDGETS`, floors, and Normal/Full-Power presets; `cortex/driver_context.py`
and `context/pipeline.py` import from it (values byte-identical at Normal);
budgets.json persistence with floor-checked overrides. No server wiring.

**Files:**
- Create: `danzaboss/cortex/budgets.py`
- Modify: `danzaboss/cortex/driver_context.py` (delete local tables, import),
  `danzaboss/context/pipeline.py` (delete local `DRIVER_CORTEX`, import)
- Test: `danzaboss/tests/test_cortex_budgets.py` (new)

**Interfaces:**
- Consumes: current table values (moved verbatim).
- Produces (consumed by Tasks 5, 11):

```python
BUDGETS_RELPATH = Path(".danza") / "runtime" / "budgets.json"
DIALS = ("normal", "full_power")
DRIVER_CORTEX: dict[str, dict]          # moved verbatim
DRIVER_BUDGETS: dict[str, int]          # moved verbatim (= the Normal preset)
FULL_POWER_BUDGETS: dict[str, int]      # 2x Normal per driver
DRIVER_FLOORS: dict[str, int]           # jonathan-builder: 600, all others: 400
DEFAULT_BUDGET = 1200                    # unknown drivers (was _DEFAULT_BUDGET)
MAX_BUDGET = 50_000

class BudgetError(ValueError): ...

def resolve_budget(driver: str, *, dial: str = "normal",
                   override: int | None = None) -> int:
    """max(floor, override or preset[dial][driver]); floors are the
    never-starve guarantee (Decision 4)."""

def validate_budgets(config: object) -> dict: ...
def save_budgets(root, config: dict) -> Path: ...
def load_budgets(root) -> dict:
    """Missing file -> {"version": 1, "dial": "normal", "overrides": {}}
    (the tested defaults ARE the absent-file behavior); corrupt -> BudgetError."""
```

- budgets.json schema: `{"version": 1, "dial": "normal"|"full_power",
  "overrides": {driver_id: int}}`; `validate_budgets` rejects unknown dial,
  override keys not in `DRIVER_BUDGETS`, non-int values, values below the
  driver's floor or above `MAX_BUDGET` (Decision 4: out-of-range rejected).
- `driver_context.py`: `DRIVER_CORTEX`, `DRIVER_BUDGETS` become re-exports from
  `budgets`; `default_budget(driver)` delegates to
  `resolve_budget(driver)` — existing imports in
  `test_cortex_driver_context.py` / `test_cortex_c3_integration.py` keep passing
  unmodified (compat is part of this task's contract).
- `pipeline.py` imports `DRIVER_CORTEX` from `danzaboss.cortex.budgets`
  (module-level import is acceptable there: it is table data, not the store).

**Steps:**

- [ ] **Step 1: Failing tests:** values byte-identical to current tables (assert
  equality against literal copies); floor clamp (`resolve_budget("bonnie-qa",
  override=100) == 400`); full_power doubles; unknown driver → DEFAULT_BUDGET;
  validate rejects bad dial / unknown key / sub-floor / over-max; load defaults
  on missing file; round-trip; re-export compat (`from
  danzaboss.cortex.driver_context import DRIVER_BUDGETS` still works).
- [ ] **Step 2:** `python3 -m unittest danzaboss.tests.test_cortex_budgets -v` → FAIL.
- [ ] **Step 3:** Implement + rewire both importers.
- [ ] **Step 4:** Targeted green: `test_cortex_budgets`,
  `test_cortex_driver_context`, `test_cortex_c3_integration`.
- [ ] **Step 5:** Commit `feat(cortex): budgets.py — single budget home, floors, dial presets (P4 T4)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 5: SETUP API + gate

**Scope (pinned):** `GET /api/setup` (live registry + auth + persisted-or-suggested
seats + dial + setup_complete) and `POST /api/setup` (validated write of
runners.json + routing.json + budgets.json); onboarding POST routes and
`/api/onboarding` gate on setup_complete. No UI.

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_danza_ui.py` (extend)

**Interfaces:**
- Consumes: `build_registry` (T2), `suggest_seats`/`save_routing`/`load_routing`
  (T3), `load_budgets`/`save_budgets` (T4).
- Produces (consumed by Task 6):

```python
def setup_summary(root: str) -> dict:
    # {"agents": [{"name", "display_name", "strengths", "detected", "auth"}...],
    #  "lineup": [...], "seats": {...}, "dial": "normal",
    #  "conductor": "builtin", "floors": {...}, "overrides": {...},
    #  "setup_complete": bool}

def post_setup(root: str, body: dict) -> dict:
    # body: {"lineup": [...], "seats": {...}, "dial": str,
    #        "overrides": {...} (optional, advanced)}

def setup_complete(root: str) -> bool:
    # runners.json + routing.json both load valid AND lineup non-empty.
    # budgets.json may be absent (defaults) — Decision 7 checks (a)+(b);
    # dial/conductor always hold valid values by construction.
```

**Design:**
- Registry probing on GET must not block the dashboard for 5 CLI calls on every
  poll: `setup_summary` caches the `build_registry` result module-level with a
  60s TTL and an injectable clock/build seam (test double); POST always
  re-probes fresh before validating.
- `post_setup`: build fresh registry → apply body's lineup/seats/dial/overrides →
  `save_runners` (boss = `lineup[0]`, session_host preserved or default) →
  `save_routing` → `save_budgets`. Any `RunnerError`/`RoutingError`/`BudgetError`
  → existing 400 path (all are ValueError subclasses). Registered in
  `_POST_ROUTES` as `/api/setup` (CSRF guard + `_POST_LOCK` inherited).
- **The gate (Decision 1):** `post_submit`, `post_followup`, `post_resolve`,
  `post_research`, `post_checkpoint`, `post_approve`, `post_finish` raise
  `GateConflict("finish Setup first — your AI team is not confirmed yet")` when
  `not setup_complete(root)` (409, plain English). `onboarding_summary` gains
  `"setup_complete"` so the UI can render the locked state.
- `overview()` runners block + `snapshot_token` gain `ROUTING_RELPATH` and
  `BUDGETS_RELPATH` (Phase-2 final-review lesson: the SSE token must cover every
  state file the UI renders).

**Steps:**

- [ ] **Step 1: Failing HTTP-level tests** (`serve_in_thread` idiom): GET shape
  with fake registry; suggested seats when routing.json absent; persisted seats
  win once saved; POST happy path writes all three files; POST 400s on 6-runner
  lineup / unauthenticated seat / sub-floor override; onboarding POSTs 409
  before setup, work after; `/api/onboarding` carries `setup_complete`;
  snapshot_token changes when routing.json changes.
- [ ] **Step 2:** `python3 -m unittest danzaboss.tests.test_danza_ui -v` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): /api/setup + hard setup-first gate (P4 T5)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 6: SETUP UI

**Scope (pinned):** MODELS tab becomes SETUP (tab order OVERVIEW · SETUP · ONBOARD ·
BUILD · CORTEX): agent cards with status chips, seat list with suggestions, dial,
conductor choice, collapsed Advanced section, "Your team" summary card + Confirm;
ONBOARD renders a locked state until setup_complete. ADUSON patterns only.

**Files:**
- Modify: `danzaboss/workstation/static/app.js`,
  `danzaboss/workstation/static/index.html`,
  `danzaboss/workstation/static/app.css`
- Test: `danzaboss/tests/test_danza_ui.py` (static-asset assertions, extend)

**Design (plain English throughout — Decision 9):**
- Agent cards: display_name + strengths + chip — `Connected` (ember),
  `Found, not logged in` (crimson, excluded from pickers), `Found` (silver).
- Seats: one row per seat — plain-English seat names (Conductor, Planner,
  Builder, Mapper, Tester, Reviewer, Researcher, Designer, Security Checker),
  one-sentence description, `<select>` of connected agents (Conductor's select
  offers "Built-in (recommended)" first — Decision 2), prefilled from
  `setup_summary.seats`.
- Dial: two large option cards — "Normal (recommended)" / "Full Power" with
  one-sentence plain descriptions (Decision 4/6).
- Advanced (collapsed `<details>`): per-role budget overrides (floor hints
  shown), note that per-seat model/effort overrides arrive with safe flags.
- "Your team" card: generated sentences ("Claude Code will plan and build.
  Gemini will research. The built-in conductor passes finished work to the next
  AI.") + **Confirm team** button → `POST /api/setup` → re-render from response.
- ONBOARD locked state: friendly panel "Set up your AI team first" + button that
  switches to SETUP.
- Client enforces lineup 1–5 (lineup = the set of agents holding seats); the
  server re-validates (server stays authoritative — Phase 3 idiom).

**Steps:**

- [ ] **Step 1:** Failing static tests: index.html tab label SETUP (not MODELS),
  app.js references `/api/setup`, no absolute non-relative URLs beyond the
  Google-Fonts precedent.
- [ ] **Step 2:** Run targeted file → FAIL.
- [ ] **Step 3:** Implement (follow existing `loadModels` → `loadSetup` rewrite;
  keep the render-from-state idiom used by ONBOARD).
- [ ] **Step 4:** Targeted file green. (Live Playwright eyeball deferred to
  Task 13 — no browser work in this task.)
- [ ] **Step 5:** Commit `feat(workstation): SETUP tab UI — team, seats, dial, confirm (P4 T6)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 7: MIDPOINT VERIFICATION (full suite — first of two)

**Scope (pinned):** `./danzaboss/run_tests.sh` full run; fix any regression from
Tasks 1–6. No new features; only what the suite demands.

**Steps:**

- [ ] **Step 1:** `./danzaboss/run_tests.sh` → expect ≥877 + new tests, OK
  (skipped=14). Paste the tail of the output as evidence.
- [ ] **Step 2:** Fix regressions if any (minimal diffs), re-run to green.
- [ ] **Step 3:** Commit fixes if any: `fix(workstation): midpoint suite repairs (P4 T7)`.
- [ ] **Step 4: STOP** for user `/clear`.

---

### Task 8: Conductor routing integration

**Scope (pinned):** Each IGNITE consults `next_boss()` for the routed runner's argv
(+ ignition phrase for argv-activation runners); missing/invalid routing.json →
today's single-boss behavior with a logged `routing_fallback`; ignite event gains
`runner` + `work_type`; loop test ignites two different fake runners across a
handoff. Plus one approved line in the Tony D template.

**Files:**
- Modify: `danzaboss/workstation/conductor.py`
- Modify: `.claude/agents/tony-d-orchestrator.md` (ONE line — user-approved
  Rule-37 edit, Decision table above)
- Test: `danzaboss/tests/test_workstation_conductor.py` (extend)

**Design:**
- `_argv()` becomes `_argv_for(runner_name: str) -> list[str]`: the named entry's
  headless argv in headless mode (empty → `RunnerError`, existing fail-closed
  rule), else interactive argv; in attachable modes with
  `entry["activation"] == "argv"` AND active routing, append `"Who's the Boss?"`
  so the ignited session actually starts its turn (today's no-routing path keeps
  the bare argv — zero behavior change for existing users).
- `tick()` IGNITE branch:

```python
runner, work_type = self._route(state)   # (boss, None) when no routing.json
argv = self._argv_for(runner)
self._host.ignite(self._name, self._root, argv)
...
self.log("ignite", session=self._name, argv=argv,
         turn_number=state.turn_number, boss=state.current_boss,
         runner=runner, work_type=work_type)
```

- `_route(state)`: `load_routing` + plan.json read each ignite (fresh — setup
  edits apply from the next turn, Decision 7). `RoutingError`/missing plan →
  `self.log("routing_fallback", reason=...)` then `(config["boss"], None)` —
  the relay never dies on a hand-edited config (flagged, not silent).
- Tony D template: one line in its handoff section — "Name the next boss from
  `.danza/runtime/routing.json` (the seat of the next planned work); if the file
  is absent, keep the current alternation." No other `.claude/` changes.
- Acceptance (spec §8): loop test with stub host + two-runner routing table and a
  two-feature plan; simulate turn advance between deaths; assert the two ignite
  events carry the two different runners' argvs.

**Steps:**

- [ ] **Step 1: Failing tests:** routed argv on ignite; ignition phrase appended
  only when routing active + argv-activation + attachable mode; fallback event
  logged on corrupt routing.json; two-runner handoff acceptance test.
- [ ] **Step 2:** Run targeted file → FAIL.
- [ ] **Step 3:** Implement + the one Tony D line.
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): conductor routes each turn via next_boss (P4 T8)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 9: BUILD tab API

**Scope (pinned):** `POST /api/build/start|stop` manage a `danza conduct` subprocess
(pidfile-aware, 409 on double-start); `GET /api/build` returns running-state +
team-state + session tail + conductor tail; `/api/conductor` limit clamps to
1..1000 else 400 (deferred Phase-2 minor). No UI.

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_danza_ui.py` (extend)

**Design:**
- `post_build_start(root, body, popen=subprocess.Popen)`: read
  `conductor.PIDFILE_RELPATH`; live pid → `GateConflict` ("the build crew is
  already running"). Else spawn
  `[sys.executable, "-m", "danzaboss.cli", "conduct", root]` detached
  (`start_new_session=True`, stdout/stderr → `.danza/runtime/conduct-ui.log`).
  The conductor's own `acquire_pidfile` remains the single-instance authority —
  the dashboard check is a fast-path courtesy, not a second lock.
- `post_build_stop`: pidfile pid → `os.kill(pid, SIGTERM)`; no pidfile/dead pid →
  409 ("the build crew is not running"). SIGTERM only — the conductor's `finally`
  releases its own pidfile.
- `build_summary(root)`: `{"running": bool, "team_state": ..., "session":
  {"name", "alive", "tail"}, "conductor": conductor_tail(root, 50)["items"]}` —
  session via `pick_host`-resolved host, `alive`/`tail` guarded so a missing tmux
  degrades to `{"alive": false, "tail": ""}` honestly.
- Injectable `popen`/`kill` seams module-level (the `detect_runners(which=...)`
  idiom) so tests never spawn processes.

**Steps:**

- [ ] **Step 1: Failing tests:** start spawns expected argv (fake popen capture);
  double-start 409 with live-pid fake; stop kills recorded pid; stop-when-dead
  409; GET /api/build shape with fake host; `/api/conductor?limit=0|5000|abc` →
  400.
- [ ] **Step 2:** Run targeted file → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): BUILD tab API — managed relay start/stop (P4 T9)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 10: BUILD tab UI

**Scope (pinned):** BUILD tab gains Start build / Stop build controls wired to
`/api/build/*`, a live team-state strip (who's the boss, turn, status), a session
tail pane, and the conductor event stream — SSE-refreshed. Existing plan-tree
rendering untouched. Plain English labels.

**Files:**
- Modify: `static/app.js`, `static/index.html`, `static/app.css`
- Test: `danzaboss/tests/test_danza_ui.py` (extend)

**Design:** Start button disabled with reason until `setup_complete` and a plan
exists ("Finish Setup and Onboarding to start building"); running state shows
Stop + live panes; conductor events rendered as friendly lines ("Handed the
baton to Claude Code (turn 4)") with the raw JSONL behind an Advanced toggle
(Decision 9). Confirm-before-stop dialog ("Stop the build crew? The current turn
finishes safely.").

**Steps:**

- [ ] **Step 1:** Failing static assertions (app.js references `/api/build/start`,
  `/api/build/stop`; BUILD panel markup present).
- [ ] **Step 2:** Run targeted file → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Targeted file green.
- [ ] **Step 5:** Commit `feat(workstation): BUILD tab UI — relay controls + live state (P4 T10)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 11: Token telemetry

**Scope (pinned):** `CaptureLog` gains `record_context_read` / `context_read_stats`
(sqlite table, NOT the conductor log); `_cmd_driver_context` records each compile;
dashboard OVERVIEW shows per-agent context spend + per-turn counts with CORTEX
savings next to spend. Budget EDITING already shipped in T5 (dial + advanced
overrides) — this task is telemetry only.

**Files:**
- Modify: `danzaboss/cortex/events.py`, `danzaboss/cortex/commands.py`,
  `danzaboss/workstation/server.py`, `static/app.js`
- Test: `danzaboss/tests/test_cortex_events.py` (extend),
  `danzaboss/tests/test_danza_ui.py` (extend)

**Design:**
- `events.py`: new table
  `context_reads(id INTEGER PK, ts TEXT, project TEXT, driver TEXT,
  tokens INTEGER, budget INTEGER)`; `record_context_read(project, driver,
  tokens, budget)`; `context_read_stats(project) -> {driver: {"reads": n,
  "tokens": n}}`. Schema creation follows `_ensure_schema` idiom
  (CREATE TABLE IF NOT EXISTS — old DBs upgrade in place).
- `commands._cmd_driver_context`: after compile,
  `CaptureLog(db_path(root)).record_context_read(project, driver, ctx.used,
  ctx.budget)` — the compile seat is the one place every driver context passes
  through (D10 telemetry point).
- `server.py`: `_cortex_stats` (or a sibling `telemetry(root)` folded into
  `overview()`) adds `per_agent` (context_read_stats) and `per_turn` (count of
  conductor `ignite` events grouped by `turn_number` from `conductor_tail`) —
  savings already present in the stats strip render next to the new spend
  numbers (Decision/D10: cost regressions visible immediately).
- OVERVIEW strip: "Tokens" card — per-agent rows (plain names via catalog
  display_name), savings shown beside spend.

**Steps:**

- [ ] **Step 1: Failing tests:** record + stats round-trip; stats empty on fresh
  DB; old-DB upgrade (open a DB created pre-table, record, no crash); overview
  payload carries `per_agent`/`per_turn`; driver-context CLI records a row
  (in-memory root fixture).
- [ ] **Step 2:** Run targeted files → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Targeted files green.
- [ ] **Step 5:** Commit `feat(cortex): per-agent context-read telemetry on the dashboard (P4 T11)`.
- [ ] **Step 6: STOP** for user `/clear`.

---

### Task 12: Plain-English copy pass

**Scope (pinned):** Words only — no ids, no flow, no logic changes: `tree.py`
wizard question prompts, dashboard labels/buttons/empty-states in the static
assets, and user-visible error strings raised toward the UI (GateConflict /
degraded-mode messages). Dev-facing text (CLI, logs, spec/plan internals, CORTEX
UI) untouched.

**Files:**
- Modify: `danzaboss/workstation/tree.py`, `static/app.js`, `static/index.html`,
  `danzaboss/workstation/server.py` (user-facing message strings only),
  `danzaboss/workstation/interview.py` (user-facing message strings only)
- Test: existing targeted files (`test_workstation_tree`, `test_danza_ui`,
  `test_workstation_interview`) — update ONLY assertions that pin old wording.

**Design rules for the rewrite:** no jargon ("checkpoint verdict" → "review
result"; "headless boss runner not configured" → "no AI agent is connected yet —
open Setup"; "spec compiled" → "your project brief is ready"); questions read as
a friendly interviewer; every error says what to do next. Question `id`s,
`show_if` logic, option VALUES, and API field names are frozen — only
display strings move.

**Steps:**

- [ ] **Step 1:** Inventory pass: grep the four files for user-visible strings;
  produce the old→new table in the commit message body (reviewable record).
- [ ] **Step 2:** Rewrite strings; update only wording-pinned test assertions.
- [ ] **Step 3:** Targeted files green.
- [ ] **Step 4:** Commit `feat(workstation): plain-English copy pass, words only (P4 T12)`.
- [ ] **Step 5: STOP** for user `/clear`.

---

### Task 13: FINAL VERIFICATION (full suite — second of two)

**Scope (pinned):** Full suite green; live Playwright eyeball (SETUP → confirm →
gate unlocks ONBOARD → BUILD controls); CLAUDE.md test-count/module sync; spec §8
amended (decision table + drift note + STATUS COMPLETE); progress.md close-out;
final whole-branch review.

**Steps:**

- [ ] **Step 1:** `./danzaboss/run_tests.sh` → green (paste tail as evidence).
- [ ] **Step 2:** Playwright eyeball on a temp activated repo: SETUP renders
  agents + seats + dial; Confirm writes files and unlocks ONBOARD; ONBOARD
  locked panel shows before confirm; BUILD start button gates on
  setup+plan; 0 console errors.
- [ ] **Step 3:** Docs: CLAUDE.md (test count, workstation/module lines), spec
  `docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md` §8
  STATUS COMPLETE + grilled-decisions table + budget-table drift note.
- [ ] **Step 4:** Commit `docs: Phase 4 complete — spec §8 STATUS, CLAUDE.md sync (P4 T13)`.
- [ ] **Step 5:** Dispatch final whole-branch review (plan-start commit..HEAD);
  triage findings (fix Critical/Important, log minors to progress.md).
- [ ] **Step 6: STOP.** Report Phase 4 complete; user commits/pushes.

---

## Self-Review

- **Spec §8 coverage:** catalog ✅T1 · probe ✅T2 · router ✅T3 · lineup+routing
  surface ✅T5/T6 (as SETUP, per Decision 8) · conductor integration ✅T8 ·
  BUILD tab ✅T9/T10 · budget reconciliation ✅T4 · editable budgets ✅T5/T6 ·
  telemetry ✅T11 · §8 acceptance tests ✅T2 (registry), T3 (router), T8
  (two-runner handoff loop).
- **Grilled decisions coverage:** gate ✅T5/T6 · built-in conductor default ✅T3
  (`"builtin"`)/T6 · 9 seats, no Fast Scaffolder ✅T3 · strengths suggestions
  ✅T1/T3/T6 · dial ✅T4/T5/T6 · models-as-configured ✅ (no model flags
  anywhere; `full_power_extra_argv` empty) · effort-in-dial ✅T4/T6 · setup-done
  definition ✅T5 · SETUP replaces MODELS ✅T6 · copy pass ✅T12.
- **Type consistency:** `entry["auth"] ∈ ("ok","unauthenticated","unprobed")`
  used identically in T2/T3/T5/T6; `next_boss(routing, plan_data, state)`
  signature identical in T3/T8; `resolve_budget(driver, *, dial, override)`
  identical in T4/T5/T11; `ROUTING_RELPATH`/`BUDGETS_RELPATH` names consistent.
- **No placeholders:** every task carries concrete schemas, signatures, test
  names, and commands; no TBDs.
