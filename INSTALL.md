# DANZABOSS — Install into any app repo

## Copy these into your app's repo root:
- `.claude/`     (agents, constitution, "Who's the Boss?" skill, active hooks)
- `.danza/`      (state + memory)
- `danzaboss/`   (the Python brain)
- `CLAUDE.md`

Optional: `tools/`, `docs/`, `RUNBOOK.md`.

## Requirement
Python 3.10+ on the machine (`python3 --version`). Everything is stdlib-only — no pip installs.

## Run it
In Claude Code, from your app repo, type:  **Who's the Boss?**
- First run (no handoff) → self-checks, scans/learns your app, builds.
- Hooks are already ACTIVE: destructive commands (`rm -rf`, drop table) are denied,
  auth/payment/schema edits escalate to you, `.claude/` + templates are protected.
  Hooks fail OPEN on any error — they can never brick your session.

## Verify before trusting it (optional, 30s)
```
./danzaboss/run_tests.sh                        # 124 tests
PYTHONPATH=. python3 -m danzaboss.cli selftest  # 8/8
```
