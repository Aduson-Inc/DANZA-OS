# DANZA-OS Install Reality

DANZA-OS is currently a real Python-based agent governance and memory toolkit with a functioning CORTEX memory subsystem. It is not yet a finished turnkey app-building OS. The end-to-end multi-agent app-building loop still needs verification and hardening.

## Current Install Status

Status: PARTIAL/UNVERIFIED.

There is no confirmed clean install story yet and no package manifest such as `pyproject.toml`. Most commands assume running from the repository root with `PYTHONPATH=.`.

## Local Requirement

Python 3.10+ is expected. The OS-level Python code is intended to stay stdlib-only, though optional adapters and external tools may require separate setup.

## Current Local Command Pattern

From the repo root:

```
PYTHONPATH=. python3 -m danzaboss.cli selftest
PYTHONPATH=. python3 -m danzaboss.cli profile
PYTHONPATH=. python3 -m danzaboss.cli cortex <command>
```

## Claude Code Operational Files

`.claude/`, `.danza/`, and `CLAUDE.md` are operational files for the current Claude Code setup. Treat them as runtime context, not disposable documentation.

This docs-only stabilization did not change Claude Code settings, agent prompts, rules, hooks, runtime state, source code, or tests.

## Verification Reality

Use:

```
./danzaboss/run_tests.sh
PYTHONPATH=. python3 -m danzaboss.cli selftest
```

Do not rely on old hardcoded counts such as 124 or 401. The recent audit discovered 672 unittest cases in this environment; `selftest` passed 8/8. The full suite needs an environment that allows localhost socket binding for CORTEX UI endpoint tests.
