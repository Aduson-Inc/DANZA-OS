# Installing DANZA-OS

DANZA-OS is packaged by `pyproject.toml` and requires Python 3.10 or newer.
The supported public installer is pinned to the `Production-DANZABOSS` branch.
It works from an empty folder or an existing Git repository.

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/Production-DANZABOSS/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/Production-DANZABOSS/install.ps1 | iex
```

The installer checks mandatory dependencies, explains them, requests approval
before installing, writes the packaged payload, initializes project-local
CORTEX, starts the dashboard on `http://localhost:33000`, and reports the AI
connection as pending until Setup verifies it. tmux is optional and is not
installed by the installer.

## Initialize a target application

Run activation only inside a real target project or disposable fixture:

```bash
cd /path/to/target-app
danza activate .
```

`danza activate` deterministically copies the packaged APP_BUILD payload, adds
a managed block to the target's `CLAUDE.md`, preserves user-modified files,
and records payload hashes in `.danza/.scaffold-version`. The target receives
the eight named character prompts, activation skill, runtime constitution,
Claude settings and hooks, canonical agent definitions, and bootstrap `.danza`
files.

The SessionStart hooks restore DANZA state and inject adaptive CORTEX context.
PostToolUse captures eligible observations and Stop performs CORTEX processing
and runtime checks. These hooks belong to the target APP_BUILD project, never
the product source checkout.

Supported runner CLIs are detected and configured from the dashboard SETUP
view or with `danza runners`. PROJECT approval and decomposition must complete
before BUILD can start.

The runtime task gate is available to connected agent adapters through
`danza cortex task-start`; it seeds the first task and injects relevant
project-local memory into later tasks.
