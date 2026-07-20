# DANZABOSS Runbook

## Install

Run the branch-pinned installer from an empty folder or target repository:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.sh | bash
```

The Windows equivalent is:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/codex/production-danzaboss-install-flow/install.ps1 | iex
```

Review the dependency explanation and approve it. Declining leaves the target
unchanged. An empty folder is initialized as Git only after approval.

## First launch

Open `http://localhost:33000` (the installer opens it automatically). In Setup,
choose 1–4 clients, Connect, complete native sign-in, Verify, and set the boss
order. Do not begin onboarding until the connection status is verified. If a valid runtime handoff
exists, resume it; if the handoff is real but its validation sidecar is missing
or invalid, stop and repair the handoff state.

## Runtime checks

```bash
danza doctor .
danza runners .
danza cortex stats
```

The installation record is `.danza/runtime/installation.json`. Connection
proof is `.danza/runtime/connection.json`. Delegations, event capture, and
turn ownership are under `.danza/runtime/`. CORTEX data is under
`.danza/cortex/` and must not be read from a global default during a project
run.

## Verification

Run the repository tests with Python 3.10 or newer:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s danzaboss/tests -p 'test*.py'
```

For an end-to-end target, use a disposable empty folder and an existing Git
repository. Verify the dashboard, local CORTEX database, project state, and an
actual AI connection before calling installation complete.

## Internal session host

The connection flow uses one project-scoped tmux session with managed panes when
tmux is available. DANZABOSS opens the terminal automatically. Users should
not manage tmux; the dashboard exposes a technical attach command only as a
fallback. tmux is not installed automatically.
