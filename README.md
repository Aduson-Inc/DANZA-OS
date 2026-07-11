# DANZA-OS

DANZA-OS is currently a real Python-based agent governance and memory toolkit with a functioning CORTEX memory subsystem. It is not yet a finished turnkey app-building OS. The end-to-end multi-agent app-building loop still needs verification and hardening.

## Current Status

- REAL: `danzaboss/` contains executable Python modules for CLI commands, CORTEX memory, governance hooks, kernel state, planning, verification, research seams, and workstation/onboarding libraries.
- REAL: CORTEX has a local SQLite-backed observation store, capture log, retrieval pipeline, graph store, read-only dashboard, and MCP read surface.
- PARTIAL: The full Claude Code multi-agent app-building loop exists mainly through `.claude/` prompts and hooks, and has not been proven as a clean turnkey product path.
- PARTIAL: Workstation/onboarding code exists as tested libraries, but not as a finished product UI.
- SCAFFOLD: Live research lanes and external integrations need provider wiring and real environment validation.
- UNVERIFIED: Clean install, production deployment, and unattended app-building reliability.

See [STATUS.md](STATUS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [CORTEX.md](CORTEX.md), and [ROADMAP.md](ROADMAP.md) for the current truth map.

## Repository Shape

```text
danzaboss/      Python toolkit: CLI, CORTEX, kernel, hooks, planning, research, workstation
.claude/        Claude Code operational prompt/hook layer
.danza/         Runtime state and local CORTEX data for this repo
docs/           Design notes, historical plans, and strategy documents
tools/          Auxiliary research tooling
```

## Quick Verification

The repository currently uses stdlib `unittest` through:

```bash
./danzaboss/run_tests.sh
PYTHONPATH=. python3 -m danzaboss.cli selftest
```

Recent run: `selftest` passed 8/8. The full unittest suite runs **733 tests, green (14 optional skips)** in this environment. Treat exact test counts as current-run evidence, not a hardcoded product claim.

## Installation Reality

Packaging/installability is PARTIAL. There is no confirmed clean install story yet and no package manifest such as `pyproject.toml` in the current repo. Most commands assume running from the repo root with `PYTHONPATH=.`.

## Product Reality

DANZA-OS is useful today as an internal/local toolkit for agent governance, CORTEX memory, verification helpers, and Claude Code orchestration experiments. It is not production-ready and should not be marketed as a finished app-building operating system without those caveats.
