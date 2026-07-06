# DANZA-OS Architecture

This file describes current repository reality, not the target roadmap.

## Executive Map

DANZA-OS is currently a Python toolkit plus a Claude Code operational prompt layer.

```text
Claude Code layer (.claude/)
        |
        v
Python toolkit (danzaboss/)
        |
        +-- CORTEX memory/context subsystem
        +-- kernel state and profiles
        +-- hooks and gates
        +-- planning and verification helpers
        +-- workstation/onboarding libraries
        +-- research provider seams
```

## Main Modules

| Module | Status | Responsibility |
|---|---|---|
| `danzaboss/cli.py` | REAL | Dispatches CLI commands for scan, verify, selftest, hooks, CORTEX, profile, tier, runners, conduct |
| `danzaboss/cortex/` | REAL/PARTIAL | Local memory, observations, retrieval, graph, dashboard, MCP, optional global federation |
| `danzaboss/kernel/` | REAL | Profiles, team-state, scheduler, verification tiers |
| `danzaboss/hooks/` | REAL/PARTIAL | Guard/gate logic; operational impact depends on Claude Code hook wiring |
| `danzaboss/planning/` | REAL/PARTIAL | Spec/task decomposition helpers |
| `danzaboss/workstation/` | PARTIAL | Onboarding/wizard/planner/conductor libraries; not a complete product UI |
| `danzaboss/research/` | SCAFFOLD/PARTIAL | Research abstractions and stubs; live providers need external setup |
| `danzaboss/memory/` and `danzaboss/context/` | LEGACY/PARTIAL | Older JSONL memory and context pipeline, now overlapping with CORTEX |
| `.claude/` | PARTIAL | Claude Code operational prompts, rules, and hook settings |
| `.danza/` | REAL/PARTIAL | Runtime state and local CORTEX data for this repo |

## Runtime Surfaces

- CLI: `PYTHONPATH=. python3 -m danzaboss.cli ...`
- CORTEX dashboard: local stdlib HTTP server from `danzaboss/cortex/ui/server.py`
- CORTEX MCP: stdio JSON-RPC server from `danzaboss/cortex/mcp_server.py`
- Claude Code hooks: configured through `.claude/settings.json`; not changed by this docs update

## Current Boundaries

- DANZA-OS does not yet provide a packaged installable application.
- DANZA-OS does not itself write app code headlessly as a complete product workflow.
- The Claude Code agent layer remains operational context, not general documentation.
- CORTEX is a real local memory subsystem, but not a full SaaS/product service.
