# CORTEX C6 — VPS-Readiness Pre-Build Report

**Date:** 2026-07-04
**Branch:** `c6-cortex-vps-readiness` (worktree `/home/tre/dev/DANZA-OS-c6`, base `fc178d3`)
**Spec row (design §8):** MCP wrapper (stdio: search/get/retrieve/context), Neon/Postgres
adapter, L4/L5 global store.
**Acceptance:** external MCP client retrieves a package; identical test suite green on
both backends.

---

## 1. Scope evidence (verified from code at fc178d3)

- `ports.py:36-43` — `StorageBackend` Protocol: `put/get/delete/all/log_use/usage_log`.
  **Gap:** `search()` is implemented by `SqliteBackend` and consumed by
  `retrieve.py:85` (via `getattr`) and `commands.py:_cmd_search`, but is missing from
  the Protocol. The Neon adapter must implement it; the Protocol should declare it.
- `sqlite_backend.py` — the only adapter. JSON-encoded TEXT columns, FTS5
  (porter unicode61) synced on `put`, `usage_log` table (C5). **No WAL / busy_timeout**
  (events.py:46 sets WAL; the observation DB does not) — matters once a *shared* global
  DB gets concurrent writers.
- `commands.py` — every command constructs `SqliteBackend(db_path(root))` directly
  (11 sites). Single choke point `db_path()`; no global-store notion anywhere yet.
- `store.py` / `learn.py` / `inject.py` / `retrieve.py` — all talk to `store.backend`
  only through the port methods + `search`. A parity-true adapter slots in with zero
  changes to these modules.
- Design §3.2 — global store location fixed: `~/.danza/cortex/global.db`.
- Spec §16 Q2 (L5-vs-L2 precedence) and Q4 (shared-store concurrency) are explicitly
  deferred to C6 (design §10) — answered in §3 below.
- Environment: no `psycopg`/`psycopg2` installed; `psql` client present, no local
  server; **Neon MCP plugin is available in this session** (can provision a real
  Postgres for live parity verification).

## 2. Smallest architecture that satisfies acceptance

New files (all under `danzaboss/cortex/` unless noted):

| File | Responsibility |
|---|---|
| `neon_backend.py` | `NeonBackend(dsn)` — Postgres adapter implementing the full port incl. `search()`. Lazy `import psycopg` inside `__init__` (optional adapter per design D7 — stdlib engine untouched; missing driver → clear `RuntimeError` with install hint). Schema mirrors SQLite: TEXT columns + JSON encoding reused from a shared codec; FTS via generated `tsvector` column + GIN index, `english` config (porter-equivalent stemming); tokens sanitized and OR-joined (same injection-safety discipline as `sqlite_backend.search`). |
| `factory.py` | `open_backend(root)` (project store, SQLite) and `open_global_backend()` — `DANZA_CORTEX_GLOBAL_DSN` env → NeonBackend (VPS/shared path), else SQLite at `~/.danza/cortex/global.db` (override: `DANZA_CORTEX_GLOBAL_DB`). Kills the 11 direct-constructor sites. |
| `federate.py` | `FederatedStore` — composes project store (L2/L3) + global store (L4/L5). Reads query both and merge; writes route by `layer` (≤3 → project, ≥4 → global). Precedence rule from §3 lives here. |
| `mcp_server.py` | Stdlib-only MCP stdio server: newline-delimited JSON-RPC 2.0. Handles `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Four tools: `cortex_search`, `cortex_get`, `cortex_retrieve`, `cortex_context` — thin wrappers over the same library calls the CLI uses (NOT the `_cmd_*` printers; stdout belongs to the protocol). Errors → JSON-RPC error objects; tool failures → `isError: true` content. |

Modified files:

| File | Change |
|---|---|
| `ports.py` | add `search()` to `StorageBackend` Protocol (codify the de-facto contract) |
| `sqlite_backend.py` | `PRAGMA journal_mode=WAL` + `busy_timeout=5000` (concurrency floor for the shared global DB; harmless for project DB) |
| `commands.py` | use `factory.open_backend`; `observe` routes layer≥4 to global; `search/get/retrieve/context/stats` read federated; new `mcp` subcommand |
| `cli.py` | usage string + `mcp` in the cortex group docs |
| `docs/superpowers/specs/2026-07-03-cortex-design.md` §10 | append Q2/Q4 resolutions (append-only note, no rewrite) |
| `CLAUDE.md` | one line: `danza cortex mcp` exists |

Explicitly **out of scope** (kept minimal): porting `CaptureLog` (sessions/events) and
`GraphStore` to Postgres — the spec's C6 row binds only the `StorageBackend` port;
events/graph stay repo-local by design. No UI changes.

## 3. Proposed answers to the deferred spec questions

- **Q2 — L5-vs-L2 precedence:** *project truth wins.* On a near-duplicate collision
  between a project (L2) and a global (L4/L5) observation (same `link_bag`/title
  similarity used by `store._find_duplicate`), the L2 item is kept and the global item
  is dropped from the package with reason `"suppressed: L2 project observation
  overrides L5"`. Global knowledge still surfaces whenever no project counterpart
  exists. Deterministic, explainable, testable.
- **Q4 — shared-store concurrency:** SQLite global store gets WAL + busy_timeout
  (concurrent readers + serialized writers, no locking layer); Postgres path relies on
  native transaction atomicity. Row-level conflict stance: last-writer-wins is
  acceptable because observation evolution is append-only (`history`) and merges are
  monotonic (confidence/importance climb). No distributed locks in C6; revisit only if
  real multi-agent write contention appears.

## 4. Task list (each with its own verification)

1. **Port hardening** — `search()` into Protocol; WAL+busy_timeout in SqliteBackend.
   *Verify:* full suite green (339).
2. **Backend contract parity harness** — extract a `BackendContractMixin`
   (put/get/delete/all/search/log_use/usage_log/unicode/injection cases) into
   `tests/test_cortex_backend_parity.py`; SQLite class runs always; Neon class is
   env-gated (`DANZA_TEST_PG_DSN`) + skips cleanly without driver/DSN.
   *Verify:* new tests green on SQLite.
3. **`neon_backend.py`** — adapter per §2. *Verify:* parity suite green against a real
   Postgres (Neon MCP-provisioned test DB, pending gate answer) — this is the
   "identical test suite on both backends" acceptance.
4. **Factory + global store + federation** — `factory.py`, `federate.py`, layer
   routing in `observe`, federated reads, Q2 precedence rule.
   *Verify:* new unit tests (tmp-dir HOME, both-store fixtures, precedence case);
   full suite green.
5. **`mcp_server.py` + `danza cortex mcp`** — server per §2.
   *Verify:* unit tests for framing/dispatch + an end-to-end test that spawns
   `python3 -m danzaboss.cli cortex mcp` as a subprocess and drives
   initialize → tools/list → tools/call cortex_retrieve as an external client —
   this is the "external MCP client retrieves a package" acceptance.
6. **Docs + selftest sweep** — spec §10 append, CLAUDE.md line, `danza selftest` and
   full suite green; one milestone observation.

## 5. Open questions (BUILD C6 gate)

1. **Optional psycopg dependency** — approve lazy-import `psycopg` (v3) as the Neon
   driver? Engine stays stdlib-only; driver needed only when the adapter is used.
2. **Live parity verification** — approve provisioning a throwaway Neon test database
   via the Neon MCP plugin + `pip install psycopg` locally, so acceptance is verified
   against real Postgres (recommended)? Alternative: ship env-gated tests unverified
   against live PG.
3. **Q2/Q4 resolutions** — approve the precedence + concurrency stances in §3.
