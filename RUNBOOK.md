# DANZABOSS Runbook

## Install

Run the branch-pinned installer from an empty folder or target repository:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/Production-DANZABOSS/install.sh | bash
```

The Windows equivalent is:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/Production-DANZABOSS/install.ps1 | iex
```

Review the dependency explanation and approve it. Declining leaves the target
unchanged. An empty folder is initialized as Git only after approval.

## First launch

Open `http://localhost:33000`. In Setup, choose a local client or provider
adapter, launch it when needed, and run connection verification. Do not begin
onboarding until the connection status is verified. If a valid runtime handoff
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

## Optional tmux

tmux can be used manually for operator visibility, for example to keep a local
client session attached. It is not required by the installer or runtime. When
tmux is absent, the native process host remains the supported path.
