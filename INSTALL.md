# Installing DANZABOSS

DANZABOSS is packaged by `pyproject.toml` as the `danza-os` distribution
(Python package `danzaboss`, command `danza`) and requires Python 3.10 or
newer. It has no required runtime dependencies. This temporary guided-flow
test installer is pinned to the `codex/production-danzaboss-install-flow`
branch; the installer rejects any other branch.

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.ps1 | iex
```

The installer:

1. checks for Python 3.10+ and Git, and explains what it will install;
2. requests approval before changing anything (`--yes` or `DANZA_APPROVE=1`
   skips the prompt for automation);
3. initializes an empty folder as a Git repository after approval; a
   non-empty folder that is not already a Git repository is rejected;
4. creates a project-local environment at `<target>/.danza/runtime/venv` and
   installs the pinned `danza-os` package into it from GitHub;
5. runs `danza activate`, which scaffolds the target, creates the project
   CORTEX database, starts the dashboard at `http://localhost:33000`, opens
   the browser, and writes `.danza/runtime/installation.json`.

Installation reports `awaiting_ai_connection` until the dashboard Connect
stage verifies a signed-in AI client; it is `verified` after that. tmux is an
internal session host and is never a user prerequisite or a manual first
step.

## What activation writes into the target

`danza activate .` (and the scaffold-only `danza init .`) deterministically
install the packaged APP_BUILD payload:

- `.claude/agents/` with the eight named character prompts;
- `.claude/rules/constitution.md` and `.claude/skills/danza/SKILL.md`;
- `.claude/settings.json` wiring the PreToolUse guard, SessionStart state and
  CORTEX context restore, PostToolUse capture, and the Stop distillation
  gate;
- bootstrap `.danza/` files (handoff, logs, templates, decision and turn
  logs) and `.danza/agents/definitions.json`, the vendor-neutral roster;
- a managed block in the target's `CLAUDE.md`, maintained only between its
  explicit markers;
- `.danza/.scaffold-version`, a content-hash manifest of every bundled file.

The scaffold is idempotent and preserves user-modified files instead of
overwriting them. Re-running the installer or `danza init` is safe.

## After installation

Supported runner CLIs are detected and verified in the dashboard Connect
stage or inspected with `danza runners .`. The Describe and Approve stages
must complete — an approved exact scope revision plus generated build units —
before the Build stage can start. Check overall health at any time with
`danza doctor .`.
