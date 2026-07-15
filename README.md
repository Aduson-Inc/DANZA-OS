# DANZA-OS

DANZA-OS is an unreleased Python application for building software with a
named AI team, governed project state, executable plans, verified work units,
and CORTEX memory. Tony-D — The Boss orchestrates Jonathan, Samantha, Angela,
Bonnie, Carmella, Hank, and Billy.

The repository has three deliberate layers:

- Layer 0 `OS_DEV`: this source checkout, its tests, and contributor guidance.
- Layer 1 packaged DANZA-OS: the `danza-os` package, `danza` CLI, dashboard,
  runners, hooks, schemas, CORTEX, and one canonical APP_BUILD payload.
- Layer 2 `APP_BUILD`: a real target repository initialized with `danza init`.

The source checkout does not ship or activate a root customer-agent roster.
Generated projects receive their `.claude/` runtime and project-scoped
`.danza/` state from `danzaboss/product/templates/scaffold/`.

## Product flow

SETUP connects supported AI CLIs and assigns them to the named cast. PROJECT
discovers or interviews the application, audits existing projects, obtains
scope approval, and creates canonical `features.json` and `plan.json` state.
BUILD executes verified atomic units, displays live progress, and hands work
between configured runners. CORTEX captures and retrieves project memory with
an adaptive budget based on the active task and available evidence.

## Start locally

Python 3.10+ is required.

```bash
python3 -m pip install -e .
danza selftest
danza ui . --no-open
```

To create an activated project, run `danza init` inside a separate target
repository. See [INSTALL.md](INSTALL.md) and [RUNBOOK.md](RUNBOOK.md).

## Development verification

```bash
./danzaboss/run_tests.sh
python3 -m danzaboss.cli selftest
```

DANZA-OS remains under active development. Formal browser qualification,
release qualification, licensing, tags, and public release work are future
steps, not completed product claims.
