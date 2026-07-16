# DANZABOSS

DANZABOSS is a local application-building system that installs into your
project repository. It helps you define what to build, approve the scope,
organize the work into verifiable units, and follow progress in a dashboard.

Tony-D — The Boss is the visible boss and orchestrator. Seven named
specialists support planning, implementation, mapping, auditing, testing,
research, design, and security. CORTEX keeps project memory and context.

## What DANZABOSS Does

DANZABOSS currently:

- initializes DANZABOSS files inside a target application repository;
- guides you through PROJECT discovery, interviews, scope review, approval,
  and decomposition;
- turns the approved product scope into BUILD work made of atomic units;
- tracks acceptance criteria, progress, verification, blockers, turn quota,
  additions, and handoffs;
- stores project observations and context in CORTEX;
- provides a local dashboard for Setup, Project, Build, and CORTEX; and
- installs the prompts for the named DANZABOSS cast into the target project.

## Current Status

DANZABOSS is under active development and is unreleased. It is not yet a
promoted public release.

Phase 4.1 Task 11 is complete. Phase 4.1 Task 12 has not started; formal
whole-product and browser qualification remain part of that task.

## Requirements

- Python 3.10 or newer.
- Python's `venv` module and `pip` for the verified source-checkout install
  below. `pipx` is not required for this method.
- Git. The target application should be a Git repository so `danza doctor`
  can pass its repository check.
- A browser for the local dashboard.
- For connected BUILD runs, at least one installed and signed-in AI command
  line tool recognized by Setup: Claude Code, Codex, Gemini CLI, Grok CLI, or
  OpenCode.

The commands below were verified on Linux with Bash. DANZABOSS does not yet
publish an operating-system support matrix, and formal cross-platform
qualification has not been completed.

## Install DANZABOSS

The current verified installation path is an editable install from this source
checkout. Start in the DANZA-OS source repository:

```bash
cd /path/to/DANZA-OS
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
danza selftest
```

Keep this virtual environment active while using `danza` in a target
application repository.

There is no promoted public-release installation command yet. The repository's
current `install.sh` can fall back to the GitHub `main` branch, so do not use it
to install the current development branch.

## Start a New App

With the DANZABOSS virtual environment active, create a separate target
repository. Do not initialize the DANZA-OS source checkout itself.

```bash
mkdir my-app
cd my-app
git init
danza init .
danza doctor .
danza ui .
```

For an application repository that already exists, enter that directory and
start with `danza init .` instead of creating a new one.

`danza ui .` prints the local address and attempts to open it in your browser.
The default address is:

```text
http://127.0.0.1:33100
```

Open Setup first. Confirm the detected AI tools, their work assignments, and
the number of verified atomic units allowed per turn. PROJECT unlocks after
Setup is confirmed.

## Use PROJECT

Open the Project tab and follow the visible workflow:

1. Choose **Create New** or **Continue Existing**.
2. For a new app, complete the project interview and create the project brief.
   For existing work, continue any saved interview state.
3. When continuing an existing repository, review **Audit results** and
   acknowledge every **Material coverage gap** shown.
4. Review and save the **Draft product scope**.
5. Expand **Acceptance criteria** for each product feature and correct the
   draft when needed.
6. Select **Approve exact revision N** for the exact saved revision displayed.
7. Select **Create internal build units** to decompose the approved scope.

Approval applies only to the displayed revision. Editing an approved scope
creates a new revision that must be reviewed and approved again.

## Use BUILD

Open the Build tab after Setup and PROJECT are complete.

- **Live product progress** shows the approved scope, feature status, and
  completed outcomes.
- Expand **Acceptance criteria · Atomic build units** to inspect the criteria,
  unit status, timing, and verification details.
- Select **Start build** to start the configured local build process. Connected
  runner tools can then work through assigned units and record verification.
- Select **Stop build** to request a safe stop after the current turn.
- Review completed work, the live session, and **Build activity** in the same
  view.
- **Quota this turn** shows verified units completed, the configured limit,
  and the remaining count.
- **Blocked** means a unit cannot proceed and includes its recorded reason.
  **Hard stop** means the work requires explicit attention before continuing.
  A no-work state means there is no ready incomplete unit to start.
- Use **Add to the approved product** to save an additions draft and select
  **Approve exact additions revision N**. Approved additions wait for the next
  safe handoff; they do not replace active work immediately.

BUILD depends on an approved scope, generated build units, and configured
runner tools. The dashboard shows and controls that process.

## Meet the DANZABOSS Team

- **Tony-D — The Boss** — Orchestrates project state, specialist work, and
  handoffs.
- **Jonathan — Builder** — Writes application code for the assigned atomic
  unit.
- **Samantha — Mapper** — Maintains an evidence-backed map of the codebase,
  dependencies, and data flows.
- **Angela — Auditor** — Tracks decisions, detects loops, and investigates
  root causes without writing code.
- **Bonnie — QA** — Runs the verification gate and checks completed work for
  regressions.
- **Carmella — Researcher** — Gathers approved external evidence and validates
  APIs, libraries, platform rules, and standards.
- **Hank — Designer** — Owns colors, typography, layout, imagery, and the
  application's design system.
- **Billy — Security** — Reviews security risks, authentication, dependencies,
  and secrets at the appropriate build stage.

## CORTEX Memory

CORTEX is the canonical DANZABOSS memory and context system. It stores project
observations and context in project-scoped storage so later work can continue
with relevant evidence instead of starting from nothing.

CORTEX uses adaptive context budgets. The amount of context can change with
the task, role, and available evidence. See [ARCHITECTURE.md](ARCHITECTURE.md)
for the technical design.

## Continue Existing Work

To resume an initialized project, enter the target repository, activate the
same DANZABOSS environment, check health, and start the dashboard:

```bash
cd /path/to/existing-app
. /path/to/DANZA-OS/.venv/bin/activate
danza doctor .
danza ui .
```

The dashboard reloads saved PROJECT, BUILD, runner, CORTEX, and handoff state.
If the repository has not completed discovery, choose **Continue Existing** in
Project. Otherwise, return to Project or Build at the saved stage and review
the current revision, blockers, additions, and next handoff before continuing.

To continue an AI work turn, open a configured AI command line tool in the
target repository and say `Who's the Boss?`.

## Useful Commands

PROJECT and BUILD are dashboard views. There are no standalone `danza project`
or `danza build` commands.

Core commands:

```bash
danza init .
danza doctor .
danza ui .
danza ui . --no-open --port 33101
danza runners .
danza profile
danza selftest
```

CORTEX commands operate on the current project:

```bash
danza cortex stats
danza cortex search "authentication"
danza cortex context
```

These execution commands are intended for an assigned runner or advanced
diagnostics, using real unit IDs and actor names from the active project:

```bash
danza verify "python3 -c 'print(42)'" .
danza unit start . 71-A --actor claude
danza unit verify . 71-A --actor claude
danza unit block . 71-A --actor claude --reason "Missing API key"
danza unit conclude . --actor claude
```

Replace the quoted smoke command with the target application's real test
command when using `danza verify` for BUILD evidence.

## Troubleshooting

### `danza: command not found`

Activate the environment used for the source-checkout install, then confirm
which executable your shell sees:

```bash
. /path/to/DANZA-OS/.venv/bin/activate
command -v danza
```

If it is still missing, repeat `python3 -m pip install -e .` from the current
DANZA-OS source checkout.

### Wrong Python environment

Check the interpreter and executable before reinstalling:

```bash
python3 --version
command -v python3
command -v danza
```

Python must be 3.10 or newer. Reactivate the intended virtual environment if
the paths point somewhere else.

### Running from the DANZA-OS source repository

Stop and move to a separate target application repository. The DANZA-OS source
checkout is `OS_DEV`; it is not an activated `APP_BUILD` project and must not be
initialized as one.

### Dashboard does not open automatically

Open the address printed by `danza ui .` in a browser. To disable automatic
opening explicitly, run:

```bash
danza ui . --no-open
```

### Port 33100 is already in use

Choose another local port:

```bash
danza ui . --port 33101
```

### `danza doctor` reports missing setup

Read each `[FAIL]` line. Confirm that you are in the target Git repository,
then rerun the scaffold and health check:

```bash
git status --short
danza init .
danza doctor .
```

`danza init` preserves user-modified scaffold files instead of overwriting
them. If doctor reports a missing or modified file, inspect that file before
changing it.

### Stop the local dashboard

Return to the terminal running `danza ui` and press `Ctrl-C`.

## Development and Architecture

Most users can stay in the dashboard. For implementation and operational
details, see:

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [INSTALL.md](INSTALL.md)
- [RUNBOOK.md](RUNBOOK.md)
- [CLAUDE.md](CLAUDE.md)
- [docs/OS_DEV.md](docs/OS_DEV.md)

Contributors work in the DANZA-OS source repository under `OS_DEV`. End users
initialize `APP_BUILD` inside a separate target application repository. The
source repository must never be treated as an activated application project.

## License and Release Status

No license has been selected, and the repository does not currently include a
license file. DANZABOSS is unreleased: no promoted public release, release tag,
or release policy has been established.
