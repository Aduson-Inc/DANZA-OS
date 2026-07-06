# CORTEX Build Design — Wiring the Cognitive Memory into DANZA-OS

**Date:** 2026-07-03
**Status:** LEGACY approved design. This file preserves the starting point for the CORTEX build; it is not the current state of CORTEX.
**Supersedes nothing; implements:** `docs/cognitive-memory-architecture.md` (spec v0.1)
**Approach:** A — vertical slice with VPS-readiness tweaks (user-approved)

Current baseline: CORTEX is now REAL/PARTIAL. It has local SQLite observations, capture logs, retrieval, graph, dashboard, MCP read tools, and existing repo memory data. The starting-state bullets below have been rewritten to preserve history without presenting stale claims as current reality.

---

## 1. Context — verified starting state

- LEGACY STARTING STATE: at the start of this design, only the first CORTEX slice existed
  in code (`danzaboss/cortex/`: `observation.py`, `store.py`, `ports.py`,
  `sqlite_backend.py`, `app_profile.py`). Later slices now exist in the repository.
- DOCUMENTATION DRIFT RESOLVED: CORTEX is no longer accurately described as dead code.
  Current source includes write/read paths through CLI commands, hooks, retrieval, UI,
  graph, and MCP surfaces.
- `memory/store.py` (Upgrade #7) and `context/pipeline.py` (Upgrade #8) are separate,
  simpler systems; the pipeline compiles per-driver context from `MemoryStore` only.
- Reference implementations verified locally:
  - **claude-mem 13.3.0** (`~/.claude/plugins/cache/thedotmack/claude-mem/13.3.0`):
    5 Claude Code hooks → Node worker on port **37700** → Haiku-based summarization →
    SQLite (WAL, FTS5) + optional Chroma → static SPA viewer + MCP search server.
  - **context-mode 1.0.168** ("CTX"): MCP sandbox + FTS5 (porter/BM25) knowledge base,
    session-events DB, pure lexical, no LLM summarization.

## 2. Decisions made during brainstorm (all user-approved)

| # | Decision |
|---|---|
| D1 | **Write path = both loops.** Claude Code lifecycle hooks capture live sessions AND DANZA agents write observations during turns. Store is repo-scoped so all agents "reduce tokens greatly and gain full and current context." |
| D2 | **Three-tier extraction.** Tier 1: agent-mediated distillation enforced by a Stop-gate (default brain). Tier 2: deterministic floor extractor (always runs, silent). Tier 3: background-LLM worker as an optional `ExtractorPort` adapter, off by default. |
| D3 | **Coexist with claude-mem during build.** CORTEX writes to its own store in parallel; user flips the switch after CORTEX injection is proven better. |
| D4 | **UI = read-only dashboard, default port 33000** (user-chosen; configurable). Claude-mem-parity feed plus CORTEX-only views. Stdlib `http.server`, no npm, no build step. |
| D5 | **Approach A (vertical slice) with VPS tweaks.** Portable core first, UI second, retrieval brain third, graph fourth; MCP wrapper prioritized and Neon adapter committed because the OS will later run under Hermes Agent on a Hostinger VPS. |
| D6 | **Constitution stance.** The constitution governs the finished, running OS. While building the OS, use the best engineering path; ask approval whenever a rule would be bent (the `.claude/` edits below are approved by the user's approval of this design). |
| D7 | **Stdlib-only engine retained** — for VPS portability, not rule-worship. Anything better-but-external (tree-sitter, embeddings, LLM compression) is an optional port adapter, never a hard dependency. |

## 3. Architecture

### 3.1 Package layout

```
danzaboss/cortex/
  observation.py store.py ports.py sqlite_backend.py app_profile.py   # existing P1, kept as-is
  events.py        # raw event capture: sessions + events tables, redaction filter
  extract.py       # ExtractorPort + adapters: deterministic / agent-mediated / llm-worker
  inject.py        # SessionStart context block + per-driver slices; reads ui-settings.json
  intent.py        # deterministic intent classifier (12 intents, keyword+workspace signals)
  retrieve.py      # hybrid multi-signal retrieval + RRF fusion + anti-relevance penalty
  assemble.py      # per-intent category budgets (spec §9 tables as data), marginal-value trim
  quality.py       # package scoring (relevance/coverage/redundancy/efficiency) + one re-plan
  compress.py      # deterministic extractive trimming; reasoning never compressed away
  explain.py       # formats per-item reason chains accumulated in the data path
  graph.py         # typed nodes/edges, recursive-CTE traversal, impact closure   (C4)
  repo_intel.py    # LanguageAnalyzerPort; stdlib default (ast for Python, regex others) (C4)
  git_intel.py     # commit history → observation links, change summaries          (C4)
  learn.py         # usage → weight/importance updates; aging scheduler            (C5)
  neon_backend.py  # Postgres/Neon StorageBackend adapter, parity-tested           (C6)
  mcp_server.py    # stdio MCP wrapper: search/get/retrieve/context                (C6)
  ui/server.py     # ThreadingHTTPServer on 127.0.0.1:33000 + JSON API + SSE       (C2)
  ui/static/       # single-page vanilla JS + CSS, DANZA visual identity           (C2)
```

### 3.2 Data locations

- **L2 project store:** `.danza/cortex/cortex.db` — SQLite, WAL, FTS5. One per repo.
- **L4/L5 global store:** `~/.danza/cortex/global.db` — bound in C6.
- **UI settings:** `.danza/cortex/ui-settings.json` — display + injection knobs; read by `inject.py`.
- **L0/L1:** in-memory / session-scoped tables inside the project store.

### 3.3 New tables (alongside the existing `observations` table)

- `sessions(id, project, environment, started_at, ended_at, prompt_count, status)`
- `events(id, session_id, ts, tool, file_path, command, outcome, excerpt, processed)`
- `observations_fts` — FTS5 (porter unicode61) over title/summary/tags/concepts, synced by triggers.
- C4 adds `graph_nodes(id, kind, name, project, attrs)` and
  `graph_edges(src, dst, relation, weight, evidence)`.

## 4. Write path — capture, gate, extraction

1. **Capture (thin, deterministic, fail-open).** Claude Code hooks call
   `danza cortex hook <event>`: SessionStart opens a session; PostToolUse appends one
   event row. Every event passes a **redaction filter** (regex for API keys, tokens,
   passwords, connection strings) before storage — secrets never become memory
   (spec §13). Any internal error → log to stderr, allow (a CORTEX bug never bricks a
   session; same discipline as the existing `cli.py` hook handler). On hookless
   environments (Hermes/VPS), capture falls back to turn artifacts the DANZA protocol
   produces anyway: decision-log entries, `verify` results, git commits.
2. **Stop-gate (Tier 1 enforcement).** New gate in `hooks/gates.py`: if the session has
   unprocessed events and zero new observations → **block** with reason
   "N events pending — distill via `danza cortex observe` or mark `--nothing-meaningful`."
   The in-session agent (full conversational context — better placed than claude-mem's
   transcript-replaying Haiku worker) writes structured observations as JSON: title,
   summary, type, reasoning, evidence, when_relevant/when_not_relevant, confidence
   source. `store.upsert()` merges near-duplicates (already built and tested).
   **Loop safety:** the gate blocks at most once per session; after a distillation
   attempt or an explicit nothing-meaningful marker it passes (Rule 18 spirit).
3. **Tier 2 — deterministic floor (always, silent).** Sessions that end un-distilled
   still yield draft observations: git commit → `impl_detail` from the message;
   `verify` result → `bug_fix`/`limitation`; an edit cluster on one module →
   low-confidence `impl_detail`. Drafts carry `confidence_source=speculation` (20) so
   retrieval ranks them low; nothing is ever fully lost.
4. **Tier 3 — LLM worker (optional, off).** `ExtractorPort` adapter shelling out to a
   configurable command (`claude -p` today) with pending events + a distillation
   prompt; parses JSON observations back; upserts. One config knob enables it.

## 5. Read path — injection & retrieval intelligence

1. **SessionStart injection** (`danza cortex context`): a semantic index (one line per
   observation: ID, type glyph, title, read-cost) + top-K full observations selected by
   relevance to current repo state (recent commits, changed files, feature list) — not
   recency alone + a token-economics line. K and token ceiling read from
   `ui-settings.json`, defaults conservative. Fetch-by-ID: `danza cortex get <ids>`.
2. **Per-driver injection** — the DANZA-native differentiator. `context/pipeline.py`
   gains a CORTEX source; driver profiles map to observation types and intents
   (Jonathan: convention/decision/impl_detail scoped to target files; Bonnie:
   bug_fix/root_cause/limitation; Billy: security/dependency; Angela: decision history).
   Every spawn carries a purpose-built, budget-capped CORTEX slice.
3. **Intent detection**: deterministic keyword/pattern scoring + workspace signals
   (branch name, recent tool mix); 12 spec intents; unknown → balanced profile. Each
   intent binds a signal-weight profile and a budget profile. No LLM on the hot path.
4. **Hybrid retrieval + RRF**: signals — FTS5/BM25, tag/concept match, `when_relevant`
   intent match, recency, importance, confidence, usage history, observation-link
   expansion, and a **graph-traversal slot that returns empty until C4** (RRF is
   indifferent to absent signals; the adapter binds later with no rewrite).
   Fusion `Σ w_intent[s]·1/(k+rank_s)` × importance/confidence/recency/usage
   multipliers × **anti-relevance penalty** (`when_not_relevant` ∩ intent → hard
   suppression). Reason strings accumulate on items as they flow — explainability is
   in the data path; `explain.py` only formats.
5. **Assemble → budget → quality**: category allocation per intent (spec §9 fractions
   as data), marginal-value trimming to fit, then quality scoring
   (relevance/coverage/redundancy/token-efficiency); below threshold → **one** re-plan
   (widen retrieval, drop weakest category) before shipping. Compression is
   deterministic extractive trimming; evidence and reasoning are preserved verbatim;
   LLM compression is an optional port adapter.

## 6. Web UI — `127.0.0.1:33000`

Read-only window (agents govern the store; "never ask the user to curate memory").
Launched by `danza cortex ui [--port N] [--daemon]`. Stdlib `ThreadingHTTPServer`.

**API:** `GET /api/observations` (filters + FTS), `/api/observations/<id>`,
`/api/sessions`, `/api/stats`, `/api/graph?node&depth` (C4), `/api/explain?prompt`,
`/api/events?stream` (SSE). No mutating verbs. Localhost-only bind.

**Views:**
- **Feed** — cards with type/agent/project badges, tag chips, ID+timestamp footer,
  **facts ↔ narrative toggle** (facts = summary + evidence bullets; narrative =
  reasoning prose — both stored natively, no LLM to render). SSE live updates.
- **Detail drawer** — confidence meter + provenance source, importance tier + expiry
  countdown, when_relevant/when_not_relevant chips, evidence links (file:line,
  commits), **evolution timeline** from the append-only history (merges, supersedes,
  confidence bumps).
- **Search** — FTS5 with type/layer/importance/date filters.
- **Explain playground** (flagship) — type a hypothetical prompt → watch the real
  pipeline: detected intent, per-signal rankings, RRF fusion, anti-relevance kills
  (crossed out with trigger term), final package with per-item reasons + token cost.
- **Graph explorer** (C4) — interactive SVG force layout; impact mode = reverse-
  dependency closure.
- **Stats** — token economics over time, observation growth, type/layer distributions,
  top-used observations.
- **Settings** — display + injection knobs → `ui-settings.json` (config, not curation).

Visual identity: DANZA's own dark theme (Hank designs tokens), not a claude-mem clone.

## 7. Integration surface (complete list of files changed outside `danzaboss/cortex/`)

| File | Change |
|---|---|
| `danzaboss/cli.py` | `cortex` command group: `hook <event>`, `observe`, `get`, `search`, `retrieve`, `context`, `ui`, `age`, `stats` |
| `danzaboss/hooks/gates.py` | distillation Stop-gate (§4.2) |
| `danzaboss/context/pipeline.py` | CORTEX source for per-driver compiled contexts (§5.2) |
| `.claude/settings.json` (or promoted `hooks/settings.example.json`) | SessionStart/PostToolUse/Stop entries calling `danza cortex hook ...` **[approved .claude/ edit]** |
| `.claude/agents/*.md` | short CORTEX protocol block per agent: query before working, cite observation IDs as evidence, distill before handoff; Tony D requests per-driver packages **[approved]** |
| `.claude/rules/constitution.md` | one new rule codifying the distillation gate — exact text proposed at implementation time for user sign-off **[approved to propose]** |
| `CLAUDE.md`, `.danza/handoff.md` template | required-reading pointers to CORTEX |

claude-mem remains untouched and running (D3); CORTEX uses its own `.danza/cortex/` store.

## 8. Build phases & acceptance

| Phase | Delivers | Acceptance |
|---|---|---|
| **C1 — Portable core** | sessions/events tables, redaction, FTS5, `cortex` CLI, Stop-gate, deterministic floor extractor, SessionStart injection, hook wiring | A real session in this repo captures events, blocks an un-distilled stop exactly once, and injects context into the next session |
| **C2 — Web UI** | server on 33000; feed/detail/search/stats/settings; SSE | Every route unit-tested; C1 observations visible live in a browser |
| **C3 — Retrieval brain** | intent, hybrid RRF (graph stubbed), assembler, budgets, quality gate, compression, explainability, per-driver contexts, explain playground | Fused ranking beats BM25-alone on a labeled fixture eval; every included item carries reasons |
| **C4 — Knowledge graph** | graph store (recursive CTE), repo intelligence (stdlib analyzers), git intelligence, graph signal live, graph UI view | "What depends on X / what breaks if X changes" returns correct closures on this repo |
| **C5 — Learning & automation** | learning engine, aging scheduler, Tier-3 LLM-worker adapter | Weights shift on a replayed usage log; expiry archives on schedule |
| **C6 — VPS-readiness** | MCP wrapper (stdio: search/get/retrieve/context), Neon/Postgres adapter, L4/L5 global store | External MCP client retrieves a package; identical test suite green on both backends |

C1+C2 = the "alive" milestone (~2–3 working sessions). All later phases run against
real accumulating data. Estimated total: ~10–14 sessions.

## 9. Testing & failure discipline

- Unit tests per module extending the existing 124-test suite; `run_tests.sh` green is
  the done-bar for every phase (CLAUDE.md standard).
- **Adapter parity:** SQLite and Neon backends run the identical suite (C6).
- **Retrieval eval:** labeled fixture set; C3 must beat BM25-alone, C4 must beat C3.
- **Selftest:** `danza selftest` gains a CORTEX cold-start check.
- **UI:** endpoint unit tests against a fixture store + smoke test booting on an
  ephemeral port asserting every route 200s; Playwright eyeball passes during build.
- **Failure rules:** capture hooks fail open; Stop-gate fails closed but blocks at most
  once per session; UI is read-only; engine errors log to the JSONL trace
  (`observability/trace.py`).

## 10. Resolved and remaining questions

- Spec §16 Q3 (extraction confidence threshold): resolved by the tier model — agent
  distillation is authoritative; deterministic drafts enter at speculation(20).
- Spec §16 Q1 (ADR-002 vector binding): unchanged — pluggable, off by default; decide
  with a retrieval eval once C3 exists.
- Spec §16 Q2 (L5-vs-L2 precedence) and Q4 (shared-store concurrency): deferred to C6
  design time.
- Quality threshold value (§16 Q5): set empirically during C3 against the fixture eval;
  re-plan ladder fixed at one step for now.
- **C6 resolutions (2026-07-04, user-approved at the BUILD C6 gate):**
  - Spec §16 Q2 (L5-vs-L2 precedence): **project truth wins.** A global (L4/L5)
    observation that near-duplicates a project (L2) observation — same type, similar
    title or link bag, the same fingerprint upsert uses for merging — is shadowed out
    of every read path (`cortex/federate.py`). Cross-project knowledge surfaces only
    where the project has no counterpart.
  - Spec §16 Q4 (shared-store concurrency): WAL + busy_timeout on the shared SQLite
    global store, native transactions on Postgres, last-writer-wins at row level —
    safe because evolution history is append-only and merges are monotonic. No locking
    layer in C6; revisit only if real multi-agent write contention appears.
