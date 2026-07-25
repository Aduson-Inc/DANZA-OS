# DANZABOSS Runbook

## Install

Run the branch-pinned installer from an empty folder or the root of an
existing Git repository:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.sh | bash
```

The Windows equivalent is:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.ps1 | iex
```

Review the dependency explanation and approve it. Declining leaves the target
unchanged. An empty folder is initialized as Git only after approval; a
non-empty folder that is not a Git repository is rejected.

## First launch

Open `http://localhost:33000` (the installer opens it automatically). The
dashboard is one linear flow. In the Connect stage, choose your installed AI
clients, launch each provider's native sign-in, and verify. Later stages stay
locked until the connection is verified. Then describe the app, approve the
exact scope revision, and start the build from the Build stage.

## Runtime checks

```bash
danza doctor .
danza runners .
danza cortex stats
```

The installation record is `.danza/runtime/installation.json`. Connection
proof is `.danza/runtime/connection.json`. Runner detection and lineup are
`.danza/runtime/runners.json` and `.danza/runtime/routing.json`; team state
is `.danza/runtime/team-state.json`, and the current turn brief is
`.danza/runtime/turn-brief.md`. CORTEX data is under `.danza/cortex/` and
must not be read from a global default during a project run.

## Operating a build

Start and stop the build from the dashboard Build stage. Stop requests a safe
stop after the current turn. An assigned runner records its work with the
unit commands:

```bash
danza unit start . <unit-id> --actor <runner>
danza unit verify . <unit-id> --actor <runner>
danza unit block . <unit-id> --actor <runner> --reason "<why>"
danza unit conclude . --actor <runner>
```

## Verification

Run the repository tests with Python 3.10 or newer from the source checkout:

```bash
PYTHONPATH=$PWD python3 -m unittest discover -s danzaboss/tests -p 'test_*.py'
```

For an end-to-end target, use a disposable empty folder and an existing Git
repository. Verify the dashboard, the project CORTEX database, project state,
and an actual AI connection before calling installation complete.

## Frontier scout (source repository only)

The weekly scout runs only in the canonical DANZABOSS source repository and
only when `TAVILY_API_KEY` is present; customer installs never run it. Keep
the key outside every repository in a private environment file (for example
`~/.config/danza/tavily.env` with mode 0600) and source it into the
environment for a live run. Never commit or echo the key. The scout is
throttled to one run per seven days, is triggered by dashboard polls, and
writes proposals to `.danza/frontier/`. Approvals route to the additions
backlog; nothing auto-builds.

## Internal session host

Turns open in one project-scoped tmux session with managed panes when tmux is
available, and in headless subprocesses otherwise. DANZABOSS opens the
terminal automatically; users should not manage tmux. tmux is optional and is
never installed automatically.
