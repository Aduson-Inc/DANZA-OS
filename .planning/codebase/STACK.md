# Technology Stack

**Analysis Date:** 2026-07-08

## Languages

**Primary:**
- Python 3.10+ (developed/tested on Python 3.12.3) - all executable code: `danzaboss/` (kernel, CORTEX, hooks, research, orchestration, workstation, 61 test modules), `tools/research-pipeline/yt_search.py`
- Markdown - the majority of the repository by file count: prompts, agent definitions, state files, specs (`.claude/agents/*.md`, `.danza/*.md`, `docs/**/*.md`)
- JSON - state/config files (`.danza/runtime/team-state.json`, `.claude/settings*.json`, CORTEX `ui-settings.json`, `plan_schema.json`)

**Secondary:**
- HTML/CSS/JS (vanilla, no build step) - CORTEX web dashboard static assets, `danzaboss/cortex/ui/static/` (served by `danzaboss/cortex/ui/server.py`)
- Bash - `danzaboss/run_tests.sh`, inline shell command strings referenced by CLAUDE.md and skills

## Runtime

**Environment:**
- Python 3.10+ required (per `CLAUDE.md` coding standards); actual dev environment is Python 3.12.3
- No `.python-version` or `.nvmrc` file present — version is not pinned in-repo, only documented in `CLAUDE.md`

**Package Manager:**
- None. There is no `package.json`, `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, or lockfile anywhere in the repo.
- The core OS package (`danzaboss/`) is intentionally **standard-library-only** — no install step is needed to run its 694 tests (per `CLAUDE.md`: "Python 3.10+, standard library only in OS-level code").
- A small number of *optional* third-party packages are used outside the core engine (see Key Dependencies below) and are expected to be installed ad hoc by the operator; none are currently importable in this environment (verified: `yt_dlp` and `psycopg` both raise `ModuleNotFoundError` / `pip show` reports "not found").
- Lockfile: missing (by design — no package manager is in use)

## Frameworks

**Core:**
- None. `danzaboss/` uses no web framework, no ORM, no dependency-injection framework. It is invoked as a CLI module (`python3 -m danzaboss.cli ...`) and as Claude Code hook commands.
- `http.server.BaseHTTPRequestHandler` / `ThreadingHTTPServer` (stdlib) power the CORTEX dashboard - `danzaboss/cortex/ui/server.py`
- `argparse`-style manual dispatch (hand-rolled, not `argparse` itself in all cases — check `danzaboss/cli.py` for the `_cmd_*` dispatch table) drives the `danza` CLI - `danzaboss/cli.py`

**Testing:**
- `unittest` (stdlib) - test runner for all 694 tests; discovered via `python3 -m unittest discover -s tests -p 'test_*.py' -v` in `danzaboss/run_tests.sh`
- `unittest.mock` - used throughout `danzaboss/tests/` for injectable seams (subprocess, urlopen, time)
- No pytest, no coverage.py config detected

**Build/Dev:**
- None. No bundler, no transpiler, no Docker, no CI config detected (no `.github/workflows/`, no `Dockerfile`, no `docker-compose.yml` found in repo root or subdirectories explored).

## Key Dependencies

**Critical (core engine — must be stdlib per design constraint D7 in CORTEX design doc):**
- `sqlite3` (stdlib) - CORTEX default storage backend with FTS5 virtual tables - `danzaboss/cortex/sqlite_backend.py`
- `http.server` (stdlib) - CORTEX dashboard + MCP-adjacent local serving
- `subprocess` (stdlib) - tmux session control (`danzaboss/workstation/hosts.py`), checkpoint runner, verify/runner modules
- `urllib.request` (stdlib) - all outbound HTTP (Tavily API calls, CORTEX UI test clients) — no `requests` library anywhere in the codebase

**Optional / external (not stdlib, lazily imported, not currently installed in this environment):**
- `yt_dlp` - YouTube search/metadata extraction for the research pipeline - `tools/research-pipeline/yt_search.py:18` (hard `import yt_dlp` at module top — this script is NOT part of the stdlib-only `danzaboss/` package; it is a standalone tool)
- `psycopg` (with `psycopg[binary]` and `psycopg.rows.dict_row`) - Postgres/Neon driver for the optional CORTEX L4/L5 global-memory backend - `danzaboss/cortex/neon_backend.py:33-38`. Imported lazily inside `NeonBackend.__init__` and behind a `driver_available()` check so the rest of CORTEX runs without it. Install: `pip install 'psycopg[binary]'`.
- `notebooklm` - external CLI binary (not a Python package; invoked via `Bash(notebooklm *)`) that drives Google NotebookLM for source ingestion and Q&A - referenced throughout `tools/research-pipeline/SKILL.md`. Not vendored; assumed pre-installed on the operator's machine.
- `tmux` - external system binary (not a Python package) required for the `workstation` multi-agent session host; the code degrades gracefully to a `HeadlessHost` fallback when the binary is absent - `danzaboss/workstation/hosts.py:20-21`

**Infrastructure:**
- SQLite (bundled via Python's `sqlite3` stdlib module, no separate install) - project-scoped CORTEX store at `.danza/cortex/cortex.db`, and default global store at `~/.danza/cortex/global.db`
- Optional Neon/Postgres (managed cloud Postgres) - only activated when `DANZA_CORTEX_GLOBAL_DSN` env var is set; see INTEGRATIONS.md

## Configuration

**Environment:**
- No `.env` file present in the repo (verified: none found; `.gitignore` does not reference `.env` either, meaning secrets are managed purely via shell-exported environment variables, not a dotenv file)
- Config is driven by environment variables read directly via `os.environ.get(...)`:
  - `DANZA_CORTEX_GLOBAL_DSN` - Postgres/Neon connection string for the shared L4/L5 CORTEX store - `danzaboss/cortex/factory.py:18,38`
  - `DANZA_CORTEX_GLOBAL_DB` - override path for a SQLite-backed global store (also used to sandbox test runs) - `danzaboss/cortex/factory.py:19,29`, `danzaboss/run_tests.sh:6`
  - `TAVILY_API_KEY` - Tavily search API key for the workstation "Reality Check" research feature - `danzaboss/workstation/research.py:23,172`
  - `DANZA_CLAUDE_APPROVAL` - governance flag gating external research approval
  - `DANZA_LIVE_TMUX` - flag controlling live-vs-mocked tmux behavior in the workstation host layer
  - `DANZA_TEST_PG_DSN` - test-only DSN used to run Postgres parity tests against a real database when available
- `CLAUDE_PROJECT_DIR` - set by the Claude Code runtime itself and referenced in hook commands (`.claude/settings.json`) to compute `PYTHONPATH`

**Build:**
- No build config exists — there is no compilation, bundling, or transpilation step anywhere in the repo. Code runs directly via `python3 -m danzaboss.cli ...` with `PYTHONPATH` set to the repo root.
- `danzaboss/run_tests.sh` is the closest thing to a build script: it sets `PYTHONPATH`, sandboxes the global CORTEX DB path, and invokes `unittest discover`.

## Platform Requirements

**Development:**
- POSIX-like shell (bash) environment; Linux confirmed as dev platform (`Linux 6.17.0-35-generic`)
- Python 3.10+ interpreter on `PATH`
- `tmux` binary recommended (optional — workstation degrades to headless mode without it) for multi-agent pane orchestration - `danzaboss/workstation/hosts.py`
- `git` for version control (repo is a git repository)
- Optional: `notebooklm` CLI binary and Google account access for the research pipeline
- Optional: `yt_dlp` and `psycopg` pip packages for research pipeline / Neon backend features respectively

**Production:**
- No deployment target is currently configured in-repo (no Dockerfile, no `Procfile`, no cloud config files found).
- Design intent documented in `docs/superpowers/specs/2026-07-03-cortex-design.md` (decision D5): the OS is expected to eventually run under "Hermes Agent on a Hostinger VPS," which is why the CORTEX engine keeps a stdlib-only core with an optional Neon/Postgres adapter for VPS portability — this is a forward-looking design constraint, not a currently-deployed target.
- CORTEX dashboard binds to `127.0.0.1:33000` by default (localhost-only, not intended for public exposure) - `danzaboss/cortex/ui/server.py:12,35`

---

*Stack analysis: 2026-07-08*
