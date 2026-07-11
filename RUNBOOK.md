# DANZA-OS Runbook

DANZA-OS is currently a real Python-based agent governance and memory toolkit with a functioning CORTEX memory subsystem. It is not yet a finished turnkey app-building OS. The end-to-end multi-agent app-building loop still needs verification and hardening.

This runbook describes the current local toolkit surface. It is not a clean-install or production deployment guide.

## Current Layout

```
CLAUDE.md            Entry doc every AI reads first
.claude/             Live agent layer — 8 agents + constitution + "Who's the Boss?" skill
  settings.json      Current Claude Code hook settings; do not edit casually
.danza/              Runtime state + local CORTEX data
danzaboss/           Python toolkit: CLI, CORTEX, kernel, hooks, planning, research, workstation
  kernel/ planning/ memory/ context/ security/ observability/ orchestration/ selftest/
  cortex/ hooks/ research/ workstation/
  runtime/   scan (learn any repo) · verify (run real tests) · runner
  cli.py     the `danza` command the agents + hooks call
  tests/  run_tests.sh
docs/                Design docs (architecture, ADRs, research)
tools/research-pipeline/   YouTube→NotebookLM research helper
```

## Prove The Local Toolkit Works

```bash
# from the repo root
./danzaboss/run_tests.sh
PYTHONPATH=. python3 -m danzaboss.cli selftest
```

Recent run evidence: `selftest` passed 8/8. The full unittest suite runs **733 tests, green (14 optional skips)** in this environment. Treat test counts as current-run evidence rather than a fixed documentation claim.

## Current CLI Surfaces

```bash
# Learn a target app profile from heuristics
PYTHONPATH=. python3 -m danzaboss.cli scan /path/to/your/app --domain "what it is"

# Run a target app verification command
PYTHONPATH=. python3 -m danzaboss.cli verify "npm test" /path/to/your/app

# Inspect active execution profile
PYTHONPATH=. python3 -m danzaboss.cli profile

# Use CORTEX memory commands
PYTHONPATH=. python3 -m danzaboss.cli cortex <search|get|observe|retrieve|context|age|learn|stats|index|graph|ui|mcp>

# Workstation: runner registry + conductor relay loop (against a project root)
PYTHONPATH=. python3 -m danzaboss.cli runners /path/to/project
PYTHONPATH=. python3 -m danzaboss.cli conduct /path/to/project
```

## Claude Code Agent Loop

The Claude Code operational layer is PARTIAL. The files exist, and `.claude/settings.json` is present in this repository, but the full turnkey app-building loop is still UNVERIFIED from the current audit baseline.

Do not assume this is production-safe or unattended. Treat any real target-app run as a controlled validation exercise.

## Honest Status

- REAL: Python toolkit, CLI, selftest, kernel state, hooks logic, CORTEX local memory.
- REAL: CORTEX dashboard and MCP read surface exist.
- PARTIAL: Packaging and installability.
- PARTIAL: Workstation/onboarding library stack.
- SCAFFOLD: Live research providers.
- UNVERIFIED: Clean install and end-to-end multi-agent app-building reliability.
- DOCUMENTATION DRIFT: Older docs may still contain stale test counts or old CORTEX status claims.
