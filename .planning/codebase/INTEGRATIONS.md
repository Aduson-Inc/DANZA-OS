# External Integrations

**Analysis Date:** 2026-07-08

## APIs & External Services

**Web Research:**
- Tavily Search API - direct HTTPS API used by the workstation "Reality Check" research feature to validate a proposed app idea against live web results
  - Endpoint: `https://api.tavily.com/search` - `danzaboss/workstation/research.py:22`
  - SDK/Client: none — raw `urllib.request` POST with JSON payload (`danzaboss/workstation/research.py:75-90`)
  - Auth: `TAVILY_API_KEY` env var (`TAVILY_ENV` constant) - `danzaboss/workstation/research.py:23,172`
  - Invocation is gated: `TavilyProvider` is only constructed when the env var is present and non-empty (`danzaboss/workstation/research.py:172-173`); if absent, the provider falls back to a headless-boss-with-web CLI command instead
  - Constitution requirement: this is "external research" and per `.claude/rules/constitution.md` scope note, requires explicit user approval in every profile — the code enforces this by design ("Research is NEVER automatic — run_reality_check is only invoked from an explicit user click")

**Video/Content Discovery:**
- YouTube (via `yt_dlp` library, unofficial) - 5-tier video search used to seed the research pipeline
  - Client: `yt_dlp.YoutubeDL` - `tools/research-pipeline/yt_search.py:18,59`
  - Auth: none required (public search)
  - Not part of `danzaboss/`; standalone script under `tools/research-pipeline/`, invoked as `python yt_search.py <query>` per `tools/research-pipeline/SKILL.md`

**Research Synthesis:**
- Google NotebookLM (via external `notebooklm` CLI binary, not a Python API/SDK) - ingests curated YouTube sources and answers distillation queries
  - Invocation: shell commands `notebooklm create`, `notebooklm use`, `notebooklm source add`, `notebooklm source list`, `notebooklm ask` - `tools/research-pipeline/SKILL.md:45-62`
  - Auth: presumed to be handled by the external `notebooklm` tool's own login/session (not managed by this repo)
  - Constraint: max 20 sources per notebook (NotebookLM free-tier limit), enforced by pipeline logic in `tools/research-pipeline/yt_search.py` (`MIN_RESULTS = 7`, `MAX_RESULTS = 20`)

## Data Storage

**Databases:**
- SQLite (always-on, project-scoped) - CORTEX cognitive memory store
  - Connection: file path `<repo>/.danza/cortex/cortex.db` - `danzaboss/cortex/factory.py:24-25`
  - Client: stdlib `sqlite3`, custom `SqliteBackend` adapter with FTS5 (porter stemming) virtual tables - `danzaboss/cortex/sqlite_backend.py`
- SQLite (global default) - cross-project L4/L5 CORTEX store
  - Connection: `~/.danza/cortex/global.db` by default, overridable via `DANZA_CORTEX_GLOBAL_DB` env var - `danzaboss/cortex/factory.py:28-30`
- PostgreSQL / Neon (optional, cloud-managed) - alternate backend for the global L4/L5 CORTEX store, intended for future VPS/shared-agent deployment
  - Connection: DSN string via `DANZA_CORTEX_GLOBAL_DSN` env var, e.g. `postgresql://user:pass@host/dbname?sslmode=require` - `danzaboss/cortex/factory.py:18,38-40`, `danzaboss/cortex/neon_backend.py:33`
  - Client: `psycopg` (v3, optional dependency, lazily imported) with `dict_row` row factory - `danzaboss/cortex/neon_backend.py:33-38`
  - Schema: auto-created on first connect (`observations` table + generated `tsvector` column + GIN index for full-text search, `usage_log` table) - `danzaboss/cortex/neon_backend.py:44-63`
  - Fails closed with a clear `RuntimeError` if `psycopg` is not installed when a DSN is configured - `danzaboss/cortex/neon_backend.py:34-38`
  - Test-only DSN: `DANZA_TEST_PG_DSN` env var used to run adapter-parity tests against a real Postgres instance when available

**File Storage:**
- Local filesystem only. No S3/GCS/Azure Blob or any cloud file storage integration detected anywhere in the codebase.

**Caching:**
- None. No Redis, Memcached, or in-process cache framework detected. SQLite WAL mode + `busy_timeout` is used for concurrency control on the shared store instead of a separate caching layer (`docs/superpowers/specs/2026-07-03-cortex-design.md` design note on federation concurrency).

## Authentication & Identity

**Auth Provider:**
- None. This is a developer-tooling / CLI-agent system, not an end-user application — no login, session, or identity provider exists in the codebase. "Auth" only appears as a Constitution hard-stop concern (Rule 13: "Touching auth or security logic → Stop. Notify user.") governing what Jonathan (the builder agent) is allowed to touch in a *target* application, not as something implemented in this repo.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Rollbar, or similar service integration detected).

**Logs:**
- Structured JSONL spans written to local files, not shipped to any external log aggregator - `danzaboss/observability/trace.py` (Upgrade #5 in `CLAUDE.md`'s module table)
- Append-only Markdown logs for agent decisions/turns, stored under `.danza/logs/`, `.danza/decision-log.md`, `.danza/turn-log.md` — local only, governed by Constitution Rules 34-40

## CI/CD & Deployment

**Hosting:**
- None currently configured. No Dockerfile, no `Procfile`, no cloud deploy config found in the repo.
- Forward-looking design intent only: `docs/superpowers/specs/2026-07-03-cortex-design.md` (decision D5) names "Hermes Agent on a Hostinger VPS" as the eventual runtime target, which is why the Neon/Postgres adapter and MCP stdio server exist — no VPS deployment scripts exist yet.

**CI Pipeline:**
- None. No `.github/workflows/`, `.gitlab-ci.yml`, or other CI config found. Tests are run manually via `./danzaboss/run_tests.sh`.

## Environment Configuration

**Required env vars:**
- `DANZA_CORTEX_GLOBAL_DSN` - optional, enables Postgres/Neon global CORTEX store instead of local SQLite
- `DANZA_CORTEX_GLOBAL_DB` - optional, overrides the global SQLite store path (also used by test harness to sandbox test runs away from the developer's real store)
- `TAVILY_API_KEY` - optional, enables live Tavily web search for the workstation Reality Check feature; absent = falls back to headless CLI-based research path
- `DANZA_CLAUDE_APPROVAL` - governance/approval flag consulted by hook logic
- `DANZA_LIVE_TMUX` - toggles live vs. mocked tmux behavior
- `DANZA_TEST_PG_DSN` - test-only, points parity tests at a real Postgres instance
- `CLAUDE_PROJECT_DIR` - supplied by the Claude Code runtime; used to compute `PYTHONPATH` in hook commands (`.claude/settings.json`)

**Secrets location:**
- No `.env` file exists in the repo. Secrets (Tavily key, Postgres DSN) are expected to be exported directly into the shell environment by the operator; nothing is committed or vendored.
- `.gitignore` excludes local-only runtime artifacts (`.danza/runtime/claude-approval`, `.claude/settings.local.json`, CORTEX SQLite DB files, `.playwright-mcp/`) but does not reference any dotenv pattern, confirming no dotenv-based secret file convention is in use.

## Webhooks & Callbacks

**Incoming:**
- None. The CORTEX dashboard exposes local HTTP endpoints (`/api/settings`, `/api/events?stream` via Server-Sent Events) but these are same-machine developer UI endpoints, not external webhook receivers - `danzaboss/cortex/ui/server.py`

**Outgoing:**
- `TelegramChannel` - a defined-but-not-wired-up "reference live adapter" for sending research-squad proposals to a remote messaging channel and parsing approve/deny replies
  - Location: `danzaboss/research/messaging.py:28-36`
  - Status: explicitly marked `# pragma: no cover - needs bot token/network` — this is a documented integration surface/port, not an active integration. Requires an external `bot` client object (e.g., a Telegram bot library) and `chat_id` to be supplied by the caller; raises `RuntimeError` if unconfigured.
  - The only currently-active channel implementation is `ConsoleChannel`, a deterministic in-memory stub used for tests/offline mode (`danzaboss/research/messaging.py:21-26`)

## MCP (Model Context Protocol) Servers

**Provided by this repo:**
- `danza cortex mcp` - stdio JSON-RPC 2.0 MCP server exposing CORTEX memory to external MCP clients (Claude Code, IDEs, or a future "Hermes on the VPS" agent)
  - Implementation: `danzaboss/cortex/mcp_server.py` (stdlib only — hand-rolled newline-delimited JSON-RPC, no MCP SDK dependency)
  - Protocol version: `2025-06-18` - `danzaboss/cortex/mcp_server.py:23`
  - Read-only tool surface (4 tools): `cortex_search`, `cortex_get`, `cortex_retrieve`, `cortex_context` - `danzaboss/cortex/mcp_server.py:26-83`
  - Design intent: external clients consume memory; only in-session agents write it (via capture/observe, not MCP)

**Consumed by this repo (local dev tooling, not code dependencies):**
- Playwright MCP - browser automation tool permitted in `.claude/settings.local.json` (`mcp__plugin_playwright_playwright__browser_navigate/click/evaluate/take_screenshot`); artifacts of past sessions are visible in `.playwright-mcp/` (console logs, page snapshots) — used for manual/agent-driven UI verification of the CORTEX dashboard, not invoked from any Python code.
- `context-mode` MCP plugin - `mcp__plugin_context-mode_context-mode__ctx_execute_file` permitted in `.claude/settings.local.json`; referenced as a comparison/prior-art system in `docs/superpowers/specs/2026-07-03-cortex-design.md:26` ("context-mode 1.0.168 (\"CTX\"): MCP sandbox + FTS5 (porter/BM25) knowledge base") but not integrated into `danzaboss/` code.

## Claude Code Hook Integration

Not a network integration but a first-class external-tool integration point: `.claude/settings.json` wires Claude Code's hook lifecycle directly into the `danza` CLI —
- `SessionStart` → `python3 -m danzaboss.cli cortex hook session-start`
- `PreToolUse` (matcher: `Write|Edit|MultiEdit|Bash`) → `python3 -m danzaboss.cli hook pretooluse`
- `PostToolUse` (matcher: `Write|Edit|Bash`) → `python3 -m danzaboss.cli cortex hook post-tool-use`
- `Stop` → `python3 -m danzaboss.cli cortex hook stop`

All hook commands are prefixed with `PYTHONPATH="${CLAUDE_PROJECT_DIR}"`, making the Claude Code runtime environment variable `CLAUDE_PROJECT_DIR` a required integration point for the hooks to resolve the `danzaboss` package. An example/reference wiring (untested against current hook contract) also exists at `.claude/settings.example.json`.

---

*Integration audit: 2026-07-08*
