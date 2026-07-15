# DANZA-OS Runbook

## Develop the OS

Work from the source checkout in `OS_DEV`. Confirm the boundary before a task:

```bash
git status --short
python3 -m danzaboss.cli profile
python3 -m danzaboss.cli selftest
```

The profile must be `OS_DEV`. Do not initialize this repository as APP_BUILD
and do not trust root customer `.claude/` or bootstrap `.danza/` files.

Use focused tests first and the full suite before a task commit:

```bash
python3 -m unittest danzaboss.tests.test_product_payload
./danzaboss/run_tests.sh
```

## Operate a target project

```bash
cd /path/to/target-app
danza init .
danza doctor .
danza ui . --port 33100
```

In the dashboard:

1. SETUP detects runner CLIs and maps them to the named DANZABOSS cast.
2. PROJECT discovers or interviews the app, audits an existing codebase,
   obtains scope approval, and decomposes the executable plan.
3. BUILD starts or stops execution and shows team state, unit progress,
   session output, and runtime events.

Tony-D — The Boss selects and spawns the authoritative specialists. The turn
quota is 2–5 verified atomic units. It does not control CORTEX tokens; CORTEX
chooses an adaptive context budget for each agent and task.

Useful diagnostics:

```bash
danza profile
danza runners .
danza cortex stats
danza cortex search "query"
danza tier path/to/changed-file --commit
```

If state is inconsistent, stop BUILD and inspect `.danza/plan.json`,
`.danza/features.json`, `.danza/runtime/team-state.json`, recent logs, and
CORTEX evidence before resuming. Never repair target state by editing the
packaged canonical payload.

Formal browser qualification and release qualification remain future work.
