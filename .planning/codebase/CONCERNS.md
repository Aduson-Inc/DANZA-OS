# Codebase Concerns

**Analysis Date:** 2026-07-08

**Scope note:** DANZA-OS distinguishes "the OS" (this repo, `danzaboss/` + `.claude/` + `.danza/`)
from an "activated" target repo where the OS is deployed to build someone else's app. Findings
below are about the OS itself (694 tests, all green as of this analysis: `./danzaboss/run_tests.sh`
→ `Ran 694 tests ... OK (skipped=14)`). Several concerns are already self-documented in
`.danza/memory/gaps-watchlist.md` and `.danza/memory/v2-upgrades.md` — cited explicitly below
so this file doesn't duplicate discovery, only confirms/extends it with fresh evidence.

## Tech Debt

**Governance modules built but not fully wired into the live Claude Code hook path:**
- Issue: `danzaboss/hooks/dispatcher.py`'s `HookDispatcher.pre_tool_use()` runs all six
  PreToolUse guards (`capability_guard`, `hard_stop_guard`, `turn_lock_guard`,
  `file_protection_guard`, `scope_guard`, `context_budget_guard`). The actual live wiring in
  `.claude/settings.json` → `danzaboss.cli hook pretooluse` (`danzaboss/cli.py:83-133`,
  `_cmd_hook`) hand-rolls its own subset and only calls `file_protection_guard` and
  `hard_stop_guard`. It never constructs a `HookDispatcher` or a `CapabilityRegistry`.
- Files: `danzaboss/cli.py:83-133`, `danzaboss/hooks/dispatcher.py:19-48`,
  `danzaboss/security/capabilities.py`
- Impact: role separation (Rule 42 — "only jonathan-builder writes code"), turn-lock
  enforcement at the tool layer (Rule 38/45 defense-in-depth), scope guard (anti gold-plating),
  and context-budget guard are all unit-tested but **not enforced during a real Claude Code
  session**. Only the hard-stop domain patterns (auth/payment/schema/destructive) and file
  protection (templates/`.claude/`/logs) are live. `HookDispatcher` itself is only exercised by
  `danzaboss/runtime/runner.py` (a batch/offline runner) and `danzaboss/tests/test_hooks.py`.
- Fix approach: either extend `_cmd_hook` to build a `CapabilityRegistry` + full
  `HookDispatcher` (needs an actor identity, which the comment at `cli.py:100` notes Claude
  Code's PreToolUse payload does not expose — `actor=""` is hardcoded), or explicitly document
  that capability/turn-lock/scope enforcement is currently advisory-only at the hook layer and
  relies on the LLM following the constitution voluntarily.

**Kernel scheduler and orchestration/observability modules are dormant in production:**
- Issue: `danzaboss/kernel/scheduler.py` (`Scheduler.decide`/`Scheduler.run` — Upgrade #1,
  "dual-mode execution kernel") has exactly one production import site,
  `danzaboss/selftest/harness.py:18`, used only for the cold-start self-test. The actual relay
  loop that runs in an activated repo is `danzaboss/workstation/conductor.py`'s own `decide()`
  (line 56) — a **second, independently written decision table** that duplicates (does not
  reuse) the kernel scheduler's state-machine logic.
- Files: `danzaboss/kernel/scheduler.py`, `danzaboss/workstation/conductor.py:56-76`,
  `danzaboss/selftest/harness.py:18-19`
- Further confirmed dormant (zero callers outside their own `tests/test_*.py`):
  `danzaboss/orchestration/parallel.py` (Upgrade #9, parallel dispatch planner — only
  `danzaboss/tests/test_parallel.py` imports it), `danzaboss/observability/trace.py`
  (Upgrade #5, structured JSONL spans — only `danzaboss/tests/test_trace.py` imports it, despite
  `docs/superpowers/specs/2026-07-03-cortex-design.md:206` claiming "engine errors log to the
  JSONL trace (`observability/trace.py`)" — that claim does not match the code), and
  `danzaboss/context/pipeline.py` (Upgrade #8, context-engineering pipeline — only
  `danzaboss/tests/test_context.py` imports it). `danzaboss/memory/store.py` (Upgrade #7,
  layered memory) is reachable only through `context/pipeline.py`, so it is transitively dormant
  too.
- Impact: four of the ten "v2 upgrades" (`.danza/memory/v2-upgrades.md`) are tested libraries
  with no production caller. This was already flagged by the project itself: `v2-upgrades.md:24`
  — *"Consensus round-2 priority: WIRE modules into live dispatch (they are built+tested but not
  yet called by the orchestrator)"* (dated 2026-07-01). As of this analysis (2026-07-08) that
  priority item is still open for `scheduler.py`, `parallel.py`, `trace.py`, and `pipeline.py`
  specifically (`planning/decompose.py` and `security/capabilities.py`'s core check path via
  guards ARE wired now, so partial progress has been made).
- Fix approach: either wire `conductor.py` to delegate its decision table to
  `kernel.scheduler.Scheduler.decide` (removing the duplicate logic), or retire
  `kernel/scheduler.py` in favor of the conductor's purpose-built version and mark Upgrade #1 as
  superseded rather than "BUILT+TESTED" (currently implies production use). Do the same audit
  for `trace.py`, `parallel.py`, `pipeline.py`/`memory/store.py` — either wire them into
  `cli.py`/`conductor.py`/`hooks/` or update `v2-upgrades.md` to reflect their actual (dormant)
  status.

**Stale references to the retired Mona (Historian) agent:**
- Issue: `.claude/agents/mona-historian.md:2` explicitly renames the agent to
  `mona-historian-RETIRED` and states "Do not spawn `mona-historian`. Removed from Tony D's tool
  grants and the constitution roster." But `danzaboss/security/capabilities.py:50` still grants
  `"mona-historian": {Capability.READ}` in `DEFAULT_GRANTS`, and
  `danzaboss/context/pipeline.py:98` and `danzaboss/observability/trace.py:5` still reference
  Mona by name in code/comments. CLAUDE.md's 8-agent roster table and
  `.claude/rules/constitution.md`'s Agent Roster table both correctly omit Mona.
- Files: `danzaboss/security/capabilities.py:50`, `danzaboss/context/pipeline.py:98`,
  `danzaboss/observability/trace.py:5`, `.claude/agents/mona-historian.md`
  (contrast with `CLAUDE.md`'s 8-row Agent Roster table)
  - Impact: low (Mona's grant is read-only and Mona is never spawned), but it is a latent
  landmine — if `DEFAULT_GRANTS` is ever iterated to auto-generate agent docs or a spawn
  allowlist, the retired agent would silently reappear as grantable.
- Fix approach: remove the `mona-historian` entry from `DEFAULT_GRANTS` and drop the stray
  comment references, or keep it but add a `RETIRED — read-only, never spawned` comment
  co-located with the constant so the two sources of truth can't drift further.

**Dangling ADR-002 reference:**
- Issue: `docs/superpowers/specs/2026-07-03-cortex-design.md:214` references "Spec §16 Q1
  (ADR-002 vector binding)" but no `ADR-002` (or any ADR-numbered) document exists anywhere
  under `docs/`.
- Files: `docs/superpowers/specs/2026-07-03-cortex-design.md:214`
- Impact: low — cosmetic, but this doc already had one dangling reference fixed in commit
  `f6deddb docs: correct test count, record build-order feature, fix dangling ref`; this second
  one was missed by that pass.
- Fix approach: either write the ADR-002 doc (vector-embedding binding decision) or replace the
  citation with the actual decision text inline.

**Legacy `.danza/memory/` vs CORTEX (`.danza/cortex/`) — two memory systems coexist:**
- Issue: DANZA-OS has both a prose-file memory system (`.danza/memory/*.md`:
  `architecture.md`, `overview.md`, `working-style.md`, `danza-lexicon.md`,
  `cortex-memory-system.md`, `gaps-watchlist.md`, `v2-upgrades.md`, `INDEX.md`) and the newer
  SQLite-backed CORTEX cognitive memory (`.danza/cortex/cortex.db`, `danzaboss/cortex/`, C1–C6
  complete per CLAUDE.md's module table). A same-day cleanup-then-restore cycle happened in this
  repo's history (legacy memory docs were deleted, then restored from git — see recent commits
  around 2026-07-08 in `.danza/memory/`).
- Files: `.danza/memory/*.md`, `.danza/cortex/`, `danzaboss/cortex/`
- Impact: unclear single source of truth for "what does the OS know about itself" — a session
  reading only CORTEX via `danza cortex context` could miss facts still living only in the
  prose files, and vice versa. `CLAUDE.md`'s required-reading-order (step 5) still points at
  `.danza/system-map.md`, `feature-list.md`, `decision-log.md` (prose) rather than a CORTEX
  query, suggesting the prose files remain load-bearing even after CORTEX shipped.
- Fix approach: decide explicitly (and document in CLAUDE.md) whether `.danza/memory/*.md` is
  now legacy/historical-only or still authoritative alongside CORTEX, and if legacy, fold any
  still-relevant content into CORTEX observations and mark the directory read-only/archival.

## Known Bugs

**None currently reproducible in the promoted `danzaboss/` package.** The one previously-known
bug (W1 fail-open turn lock in `kernel/state.py` — actor omitted could bypass ownership) is
fixed and regression-tested per `.danza/memory/v2-upgrades.md:20-23` ("FIXED same round:
ownership fields now fail-closed; +6 regression tests") and confirmed present in the current
`StateManager.transition` (`danzaboss/kernel/state.py:126-163`, see the `touched` /
`_PROTECTED_FIELDS` fail-closed check at lines 139-147).

## Security Considerations

**`run_verification()` uses `subprocess.run(..., shell=True)` on a free-text command string:**
- Risk: `danzaboss/runtime/verify.py:23-28` runs `subprocess.run(command, cwd=cwd, shell=True,
  ...)` where `command` is caller-supplied (`danza verify "<test cmd>" <dir>`, wired at
  `danzaboss/cli.py:50` `_cmd_verify`). The docstring claims "No shell-injection surprises: the
  command is the app's own configured test command, run in its own dir" — but `shell=True` with
  an interpolated string IS the classic shell-injection primitive if `command` is ever populated
  from a less-trusted source (a target app's config file, a value proposed by an LLM plan, or
  copy-pasted user input containing `; rm -rf ~` etc.), not just a human typing a known-safe
  `npm test`.
- Files: `danzaboss/runtime/verify.py:23-28`, caller `danzaboss/cli.py:50`
- Current mitigation: none beyond "trust the caller"; there is no allowlist, no `shlex.split`
  + `shell=False` path, no confirmation step distinct from the Rule 16 destructive-command
  guard (which only pattern-matches `rm -rf`, `git push --force`, `drop table`, `truncate` —
  see `danzaboss/hooks/guards.py:29` — and is not applied to `verify`'s command at all).
- Recommendations: either document explicitly that `verify`'s command argument must always come
  from a static, user-authored config (never from agent-proposed text) and add that as an
  explicit hard-stop-guard pattern, or switch to `shell=False` with `shlex.split` for the common
  case and only fall back to `shell=True` for commands that need shell features (pipes/&&),
  gated behind an explicit flag.

**Capability/turn-lock/scope guards not enforced at the live hook boundary (see Tech Debt above):**
- Risk: Constitution Rule 42 ("only jonathan-builder writes code") and Rule 38/45 (turn lock) are
  enforced by `capability_guard` / `turn_lock_guard`, but as shown above these are not called by
  the actual `.claude/settings.json`-wired hook path. In a live session, an orchestrator or any
  other role could in principle issue a `Write`/`Edit` and only be stopped if it happens to also
  match a hard-stop domain pattern or a protected file path — role separation itself is
  unenforced at the tool layer.
- Files: `danzaboss/cli.py:83-133`, `danzaboss/hooks/guards.py:45-59`,
  `danzaboss/security/capabilities.py`
- Current mitigation: relies on the constitution being loaded into context and the LLM
  self-policing (Rule 1-2, "no assumptions, no workarounds"), plus the `capability_guard`/
  `CapabilityRegistry` machinery existing and being tested for when it IS wired (e.g. via
  `danzaboss/runtime/runner.py` batch mode).
- Recommendations: treat this as the top-priority "wire the modules" item — resolving the
  `actor=""` gap (`cli.py:100`, "CC hooks don't expose the acting sub-agent") is the blocker;
  Claude Code's current PreToolUse payload has no sub-agent identity field, so capability
  enforcement at that layer may be architecturally infeasible until Claude Code exposes actor
  identity in hook payloads — document this as a known platform limitation rather than a simple
  TODO.

**CORTEX web dashboard and MCP server have no authentication (low risk, by design):**
- Risk: `danzaboss/cortex/ui/server.py:405` binds `ThreadingHTTPServer` to `127.0.0.1` only
  (loopback, confirmed no `0.0.0.0` binding anywhere in the file) with no auth token — anyone
  with local shell access to the machine can hit `http://127.0.0.1:33000`.
  `danzaboss/cortex/mcp_server.py` is a stdio-only JSON-RPC server (`run(stdin, stdout)` at
  line 204-209), never opens a network socket.
- Files: `danzaboss/cortex/ui/server.py:398-424`, `danzaboss/cortex/mcp_server.py:204-239`
- Current mitigation: loopback-only binding is itself the mitigation; this is standard for a
  local dev dashboard.
- Recommendations: none required for current design; flag if the dashboard is ever made to bind
  a non-loopback interface (e.g. for the "VPS-readiness" C6 federation work) — at that point it
  needs auth.

**SQL query construction in `cortex/graph.py` uses f-strings for clause assembly:**
- Risk: `danzaboss/cortex/graph.py:116-124` (`find`), `:139-147` (`neighbors`),
  `:149-` (`_closure`) build SQL with f-string-interpolated `IN (...)` placeholder counts and
  `WHERE`/`ESCAPE` clause fragments, but all actual **values** go through `?` parameter binding
  (verified: `params.append(...)`, `[nid] + rel_params`, etc.) — the f-string parts only ever
  interpolate a fixed count of `?` characters or trusted internal column/relation vocab, not
  user-controlled string values. No SQL injection found in the sampled queries.
- Files: `danzaboss/cortex/graph.py:114-124, 138-147`
- Current mitigation: parameterized values; this is safe as implemented.
- Recommendations: none required; noting this here because the pattern (f-string SQL) looks
  alarming on casual grep and is worth a maintainer note ("f-strings here only ever splice
  placeholder counts / trusted column names, never values") so a future contributor doesn't
  "fix" it into an actual vulnerability by splicing a value in in the same style.

## Performance Bottlenecks

**No vector/embedding retrieval — CORTEX relies on FTS5 + hand-tuned RRF fusion:**
- Problem: per `docs/superpowers/specs/2026-07-03-cortex-design.md:39` (decision D7), embeddings
  are explicitly deferred as "an optional port adapter, never a hard dependency," consistent with
  the stdlib-only constraint. This is a deliberate tradeoff, not a bug, but it means retrieval
  quality is bounded by SQLite FTS5 + the C3/C4 hybrid RRF + knowledge-graph signal
  (`danzaboss/cortex/retrieve.py`, `danzaboss/cortex/graph.py`) rather than semantic similarity.
- Files: `danzaboss/cortex/retrieve.py`, `danzaboss/cortex/graph.py`,
  `docs/superpowers/specs/2026-07-03-cortex-design.md:39,214`
- Cause: architectural constraint (VPS portability, no external dependency), not an oversight.
- Improvement path: the pluggable vector-adapter seam is already named in the design doc (Q1,
  "unchanged — pluggable, off by default; decide with a retrieval eval once C3 exists" — C3 has
  since shipped per the module table, so this decision point is now actionable but undecided).

## Fragile Areas

**`danzaboss/workstation/conductor.py` and `danzaboss/workstation/hosts.py` — high recent churn:**
- Files: `danzaboss/workstation/conductor.py` (302 lines), `danzaboss/workstation/hosts.py`
  (352 lines)
- Why fragile: git history shows five consecutive "W1-P4 review" fix commits immediately after
  the initial feature commits (`21f8349`, `cda8751`, `57eaeb4`, `4365f05`, plus the original
  build commits `e927406`/`5ac96dc`/`6ea60d3`), fixing a relay deadlock, an orphaned-turn
  surface, a `TypeError` guard, pidfile `O_EXCL` races, tmux exact-match target bugs, and
  headless pid persistence — all within days of the initial implementation. This is the newest,
  least-battle-tested subsystem in the repo (subprocess/tmux integration is inherently harder to
  get right than pure-function kernel code, and it shows in the fix cadence).
- Safe modification: the code now has extensive inline comments explaining *why* each edge case
  is handled the way it is (e.g. `conductor.py:56-66` explains ordering of human-needed vs valve
  vs ignite; `conductor.py:104-111` explains tmux session-name sanitization) — read those
  comments before changing decision order or session-naming logic; they encode fixes for bugs
  that already bit this code once.
- Test coverage: good breadth (`danzaboss/tests/test_workstation_conductor.py`,
  `test_workstation_conductor_loop.py` — 257 lines, `test_workstation_hosts.py` — 466 lines),
  but one test class is explicitly gated behind a live-environment flag
  (`danzaboss/tests/test_workstation_hosts.py:435`,
  `@unittest.skipUnless(os.environ.get("DANZA_LIVE_TMUX") == "1", ...)`), meaning the real tmux
  integration path is **not exercised by default CI/local runs** — only the fake-subprocess
  seam is.

**`danzaboss/cli.py` `_cmd_hook` fail-open-on-exception design:**
- Files: `danzaboss/cli.py:71-133`
- Why fragile: the comment at line 71 states policy explicitly: "FAIL OPEN on any internal error
  (exit 0, allow) so a hook bug never bricks the session. FAIL CLOSED only on a real policy hit."
  This is a deliberate, documented tradeoff (usability over strict safety), but it means any bug
  in guard evaluation — a `KeyError`, a malformed `tool_input`, an exception inside
  `active_profile()` — silently degrades to "allow everything," including for the hard-stop
  guard that is supposed to protect auth/payment/schema/delete actions. The `except Exception`
  at line 131 is a broad catch-all with only a stderr print, no audit trail entry.
- Safe modification: if extending `_cmd_hook`, keep new failure paths narrow and prefer raising
  a specific, caught exception type over letting broad exceptions reach the catch-all — every
  new code path added inside the `try` block silently becomes part of the "fail open" surface.
- Test coverage: `danzaboss/tests/test_hooks.py` exists but the analysis did not confirm it
  specifically exercises the `_cmd_hook` fail-open path with a forced exception (verify before
  relying on it as a regression guard for this specific behavior).

## Scaling Limits

**Single SQLite file per project for CORTEX; global store is also SQLite by default:**
- Current capacity: `.danza/cortex/cortex.db` per project, `~/.danza/cortex/global.db` (or Neon
  via `DANZA_CORTEX_GLOBAL_DSN`) for L4/L5. SQLite WAL mode + `busy_timeout` handles the
  concurrency case documented at `docs/superpowers/specs/2026-07-03-cortex-design.md:225-227`
  ("safe because evolution history is append-only and merges are monotonic. No locking layer in
  C6; revisit only if real multi-agent write contention appears").
- Limit: this is explicitly a "revisit if it becomes a problem" deferred decision, not a hard
  limit measured against real load — no benchmark or concurrency test found under sustained
  multi-writer conditions (single-writer SQLite contention could serialize writers under real
  multi-agent parallel dispatch, if/when `orchestration/parallel.py` is ever wired in — see Tech
  Debt above).
- Scaling path: the Postgres/Neon adapter (`danzaboss/cortex/neon_backend.py`) already exists as
  a swap-in backend (parity-tested per `danzaboss/tests/test_cortex_backend_parity.py`, though
  that test is gated `@unittest.skipUnless(NeonBackend and _PG_DSN and driver_available(), ...)`
  — i.e. it only runs when a live Postgres DSN + `psycopg` driver are present, so this parity
  guarantee is **not exercised in a default test run**).

## Dependencies at Risk

**`psycopg` is an optional, lazily-imported dependency for the Neon backend — correctly isolated:**
- Risk: none for the stdlib-only core; `danzaboss/cortex/neon_backend.py:25-46` lazy-imports
  `psycopg` inside `driver_available()` and the connect path, raising a clear `ImportError`-derived
  message ("NeonBackend requires the optional 'psycopg' driver...") rather than crashing at
  module import time. This correctly preserves the "stdlib only" claim for the OS core.
- Impact: none currently; noting only that the Neon backend test path is skipped by default (see
  Scaling Limits above), so a regression in `neon_backend.py` would not be caught by
  `./danzaboss/run_tests.sh` in a typical environment without `DANZA_CORTEX_GLOBAL_DSN` set and
  `psycopg` installed.
- Migration plan: not applicable; this is working as designed. Consider adding a lightweight
  "does it at least import without crashing" smoke test that runs unconditionally (distinct from
  the full DSN-gated parity suite).

**`yt_search.py` depends on unpinned `yt_dlp`; no `requirements.txt`:**
- Risk: self-documented in `.danza/memory/gaps-watchlist.md:11` — "yt_search.py depends on
  unpinned yt_dlp; no requirements.txt." This is in `tools/research-pipeline/` (the external
  YouTube→NotebookLM research pipeline), not `danzaboss/`, and is consistent with
  `docs/danza-adaptive-governance-and-research.md:65` — "NotebookLM summarizer ⚠️ could not
  verify here — no CLI, no yt_dlp, Google network blocked (403)."
- Files: `tools/research-pipeline/` (per gaps-watchlist reference)
- Impact: the research pipeline's YouTube lane is unverified/fragile by the project's own
  admission; already marked "fallback, not the star" in the design (multi-source collector
  treats YouTube as one lane among several).
- Migration plan: pin `yt_dlp` and add a `requirements.txt` scoped to `tools/research-pipeline/`
  only (must not affect `danzaboss/`'s stdlib-only guarantee), or replace with a paid
  cited-answer API as already recommended in
  `docs/danza-adaptive-governance-and-research.md:53-57` ("pay for the summarizer... Perplexity
  Sonar").

## Missing Critical Features

**Procedural/build-order memory (Mona's retired responsibility) — explicitly not built:**
- Problem: `docs/superpowers/specs/2026-07-03-cortex-design.md:231-244` (section 11) documents
  this as a known, intentional gap: CORTEX stores observations (what happened, why) but not
  best-practice build sequences per app archetype (SaaS: auth → data model → billing → core
  feature → dashboard). This was Mona (Historian)'s hand-run job before she was retired; the doc
  states "Not yet built; recorded here so it is not lost."
- Blocks: onboarding currently re-derives build order judgment from scratch every project rather
  than recalling what sequence worked best previously — the "gets smarter every build" promise is
  only fulfilled for the observation/what-happened dimension, not the how-to-build dimension.

**`team-state.json` (Rule 45) does not exist in the live `.danza/runtime/` at time of analysis:**
- Problem: `.danza/runtime/` currently contains only `profile.json` and `claude-approval`
  (confirmed via directory listing) — no `team-state.json`. `.danza/handoff.md` reads "No
  handoff yet." which, per Constitution Rule 39, correctly signals NEW PROJECT MODE for this
  repo's own `.danza/` state (this repo is Layer 0/OS source, not an activated target repo, so
  this is expected — the constitution's turn-lock/team-state machinery binds Layers 2-3, not
  Layer 0 per the constitution's own Scope section). Still self-flagged as a gap in
  `.danza/memory/gaps-watchlist.md:3-4`: "team-state.json (Rule 45) did not exist -> now
  implemented in sandbox (Upgrade #2); still needs promotion into live .danza/runtime/."
- Blocks: nothing for OS_DEV work on this repo itself; matters the moment this `.danza/` is used
  to actually activate/drive a build session in relay/continuous mode rather than being edited
  as OS source.

**`AGENTS.md` absent at repo root:**
- Problem: CLAUDE.md's own "required reading order" model assumes parallel `CLAUDE.md`/
  `AGENTS.md` files so any AI environment (Claude Code, Codex, etc.) has an entry point; `ls
  AGENTS.md` at repo root returns no such file (confirmed). `.danza/memory/gaps-watchlist.md:5`
  already flags this: "CLAUDE.md/AGENTS.md missing at root -> CLAUDE.md now authored
  (2026-07-01); AGENTS.md still absent." A `.codex/skills/danza-forensic-auditor/` directory
  exists (added in commit `3734b8c`), suggesting Codex-environment support is being built out,
  but the root-level `AGENTS.md` entry point itself is still missing.
- Blocks: a Codex (or other non-Claude) session starting fresh in this repo has no guaranteed
  first-file to read equivalent to `CLAUDE.md`, unless it happens to also check `.claude/rules/`
  or discover `.codex/skills/` on its own.

## Test Coverage Gaps

**Live tmux integration path skipped by default:**
- What's not tested: `danzaboss/tests/test_workstation_hosts.py:435`'s
  `@unittest.skipUnless(os.environ.get("DANZA_LIVE_TMUX") == "1", ...)`-gated class — the real
  `TmuxHost` behavior against an actual tmux server, as opposed to the fake-subprocess seam used
  by the rest of the 466-line test file.
- Files: `danzaboss/tests/test_workstation_hosts.py:435` onward,
  `danzaboss/workstation/hosts.py`
- Risk: tmux-specific bugs (target syntax, pane lifecycle, session naming edge cases) could
  regress without the default test run catching them — consistent with the fact that this exact
  subsystem needed a live-smoke-verified fix as recently as commit `4365f05` ("pane-taking tmux
  commands need '=name:' target — live smoke verified" — i.e. found via manual live testing, not
  the automated suite).
- Priority: Medium — the fake-seam tests cover logic/control-flow well; only the tmux-protocol
  specifics are unverified by default CI.

**Neon/Postgres backend parity suite requires live credentials, skipped by default:**
- What's not tested: `danzaboss/tests/test_cortex_backend_parity.py:173`'s
  `@unittest.skipUnless(NeonBackend and _PG_DSN and driver_available(), ...)`-gated tests — the
  SQLite/Postgres behavioral parity guarantee central to the "VPS-readiness" C6 milestone.
- Files: `danzaboss/tests/test_cortex_backend_parity.py:173`
- Risk: a change to `cortex/store.py`'s shared codec/query logic could silently break Postgres
  parity without the default `./danzaboss/run_tests.sh` run catching it.
- Priority: Medium — low day-to-day risk (Postgres path is opt-in), but high risk the one time
  someone actually deploys the federated global store without first running the gated suite
  locally with a real DSN.

**Constitution-mandated append-only logs are unpopulated:**
- What's not tested/exercised: `.danza/self-assessment-log.md` and `.danza/onboarding-misses.md`
  contain only their template headers (confirmed by reading both files) — no actual turn
  self-assessments or onboarding-miss entries have ever been appended, despite Rule 9
  (self-audit before every handoff) and Rule 31 (state-update gate) requiring them to be kept
  current, and despite substantial feature work having happened (694 tests, dozens of commits).
- Files: `.danza/self-assessment-log.md`, `.danza/onboarding-misses.md`
- Risk: this isn't a code test gap but a process-adherence gap — it suggests the constitution's
  self-audit ceremony has not actually been exercised end-to-end in this repo's own history
  (consistent with this repo being primarily OS_DEV/Layer-0 work, where the constitution's
  runtime law does not bind per its own Scope section — but it means the *first* real activated
  run will be the first real test of whether these logs get populated correctly).
- Priority: Low for this repo (Layer 0 exempt), High for the first real activated target-repo
  run — verify these logs actually get written before trusting Rule 9/31 enforcement in
  practice.

---

*Concerns audit: 2026-07-08*
