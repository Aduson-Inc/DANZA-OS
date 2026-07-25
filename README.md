# DANZABOSS

DANZABOSS is a local, model-neutral mission control that builds applications
with the AI command-line tools you already have (Claude Code, Codex, Gemini
CLI, Grok CLI, and others). It installs into your project repository,
interviews you about what to build, gets your approval on an exact scope, and
then relays your connected AI tools through sequential boss turns of 2–5
verified atomic build units. Every turn starts from a compiled CORTEX memory
brief so models stop re-reading the repository, and the whole journey is
presented in one simple linear dashboard.

Tony-D — The Boss is the visible boss and orchestrator. Seven named
specialists cover building, mapping, auditing, QA, research, design, and
security.

## What DANZABOSS Does

- installs DANZABOSS files into a target application repository;
- detects and verifies the AI CLI tools already signed in on your machine;
- interviews you about the app, researches reality checks, recommends a vetted
  stack template, and compiles a spec;
- turns the approved product scope into atomic build units with acceptance
  criteria and real verification commands;
- relays connected AI tools through boss turns — 2–5 verified units per turn,
  then a handoff to the next tool in the lineup;
- briefs every turn from CORTEX project memory and measures the tokens saved;
- shows everything in a one-page dashboard.

## Current Status

DANZABOSS is under active development and is unreleased. There is no promoted
public release, release tag, or release policy.

## Requirements

- Python 3.10 or newer with the `venv` module.
- Git. Existing targets must be Git repositories; empty folders are
  initialized automatically after approval.
- A browser for the local dashboard.
- At least one installed and signed-in AI command line tool: Claude Code,
  Codex, Gemini CLI, Grok CLI, or another supported client.
- tmux is optional and is never installed automatically.

## Install the temporary guided-flow branch

The test installer is pinned to `codex/production-danzaboss-install-flow`. Run
it from an empty folder or from the root of an existing Git repository.

On Linux or macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.sh | bash
```

On Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.ps1 | iex
```

The installer detects Python 3.10+ and Git, explains what it will do, and
requests approval before changing anything. After approval it creates a
project-local environment at `.danza/runtime/venv`, installs the `danza-os`
package into it, activates the project, and opens the dashboard at
`http://localhost:33000`. Installation reports "pending" until the Connect
stage verifies an AI connection. See [INSTALL.md](INSTALL.md) for details.

## The One Flow

The dashboard is a single page with five stages. Completed stages collapse,
the current stage is open, and later stages stay locked until their turn.

1. **Connect** — choose up to four installed AI clients, launch each
   provider's native sign-in, and verify the connection. DANZABOSS opens the
   provider client in a project terminal; you do not type tmux commands.
2. **Describe** — answer the interview: project type, your idea, concept,
   features, stack, design, and practicalities. Tony-D grills unclear answers
   (up to three rounds per phase), runs a reality-check research pass, and
   pauses at review checkpoints. The stack step shows "Our pick for this
   idea" from a curated catalog of vetted stacks with proven build orders.
   Finishing compiles your spec.
3. **Approve** — this is the PROJECT workflow: review the draft product
   scope, acknowledge any audit gaps found in an existing repository, and
   select **Approve exact revision N**. Approval binds to that exact revision;
   editing an approved scope creates a new revision that must be approved
   again. Then create the internal build units.
4. **Build** — start the build and watch live progress: verified units,
   quota this turn, token savings, and any blocked or hard-stop states with
   their recorded reasons. Use additions to grow the approved product; they
   activate at the next safe handoff, never mid-work. Stop requests a safe
   stop after the current turn.
5. **Done** — every unit in the approved scope is verified complete.

The **Advanced** drawer holds project info, CORTEX memory stats, internal
plan artifacts, and the raw activity log. In the DANZABOSS source repository
only, it also shows the FRONTIER research panel.

## Meet the DANZABOSS Team

- **Tony-D — The Boss** — Orchestrates project state, specialist work, and
  handoffs. Reads the turn brief first and dispatches only the specialists a
  unit actually needs.
- **Jonathan — Builder** — Writes application code for the assigned atomic
  unit. The only code writer.
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

CORTEX is the canonical DANZABOSS memory and context system. Each project has
its own store under `.danza/cortex/`; one project can never read another's
memory.

Before every turn, DANZABOSS compiles a brief for the incoming boss: the turn
goal and quota, the assigned units with their verification commands, what the
previous boss completed, and a role-budgeted package of what the team already
knows. Context budgets are adaptive per role — they expand only when the
evidence justifies it. Agents pull more on demand with `danza cortex search`,
`danza cortex get`, and `danza cortex context`, or through the read-only MCP
server (`danza cortex mcp`). The Build stage's token-savings meter is computed
from recorded brief telemetry, never estimated after the fact. See
[ARCHITECTURE.md](ARCHITECTURE.md).

## Continue Existing Work

To resume an initialized project, enter the target repository, activate its
project environment, check health, and start the dashboard:

```bash
cd /path/to/existing-app
. .danza/runtime/venv/bin/activate
danza doctor .
danza ui .
```

The dashboard reloads the saved flow at its current stage. To continue an AI
work turn, open a configured AI command line tool in the target repository and
say `Who's the Boss?`.

## Useful Commands

The flow is driven from the dashboard. There are no standalone `danza project`
or `danza build` commands.

Core commands:

```bash
danza init .
danza activate .
danza doctor .
danza ui .
danza ui . --no-open --port 33001
danza runners .
danza profile
danza selftest
```

`danza init` scaffolds the DANZABOSS files and runs the health check;
`danza activate` scaffolds and also starts CORTEX and the dashboard.

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

Activate the project environment created by the installer, then confirm which
executable your shell sees:

```bash
. .danza/runtime/venv/bin/activate
command -v danza
```

### Wrong Python environment

```bash
python3 --version
command -v python3
command -v danza
```

Python must be 3.10 or newer. Reactivate `.danza/runtime/venv` if the paths
point somewhere else.

### Running from the DANZABOSS source repository

Stop and move to a separate target application repository. The source
checkout is the product source; it is not an activated APP_BUILD project and
must not be initialized as one.

### Dashboard does not open automatically

Open the address printed by `danza ui .` in a browser, or run
`danza ui . --no-open` to disable automatic opening explicitly.

### Port 33000 is already in use

```bash
danza ui . --port 33001
```

### `danza doctor` reports missing setup

Read each `[FAIL]` line. Confirm that you are in the target Git repository,
then rerun the scaffold and health check:

```bash
git status --short
danza init .
danza doctor .
```

The scaffold preserves user-modified files instead of overwriting them. If
doctor reports a missing or modified file, inspect that file before changing
it.

### Stop the local dashboard

Return to the terminal running `danza ui` and press `Ctrl-C`.

## Development and Architecture

Most users can stay in the dashboard. For implementation and operational
details, see:

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [INSTALL.md](INSTALL.md)
- [RUNBOOK.md](RUNBOOK.md)
- [CLAUDE.md](CLAUDE.md)

Contributors work in the DANZABOSS source repository. End users initialize
APP_BUILD inside a separate target application repository. The source
repository must never be treated as an activated application project.

## License and Release Status

No license has been selected, and the repository does not currently include a
license file. DANZABOSS is unreleased: no promoted public release, release
tag, or release policy has been established.
