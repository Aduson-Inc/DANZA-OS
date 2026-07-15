# Installing DANZA-OS

DANZA-OS is packaged by `pyproject.toml`, requires Python 3.10 or newer, and
installs the `danza` console command. It is unreleased, so install from a local
checkout while developing or evaluating it.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e /path/to/DANZA-OS
danza selftest
```

Optional Neon support is available with `python3 -m pip install -e
'/path/to/DANZA-OS[neon]'`.

## Initialize a target application

Run initialization only inside a real target project or disposable fixture:

```bash
cd /path/to/target-app
danza init .
danza doctor .
danza ui .
```

`danza init` deterministically copies the packaged APP_BUILD payload, adds a
managed block to the target's `CLAUDE.md`, preserves user-modified files, and
records payload hashes in `.danza/.scaffold-version`. The target receives the
eight named character prompts, activation skill, runtime constitution, Claude
settings and hooks, and bootstrap `.danza` files. Mona is retired and is not
installed.

The SessionStart hooks restore DANZA state and inject adaptive CORTEX context.
PostToolUse captures eligible observations and Stop performs CORTEX processing
and runtime checks. These hooks belong to the target APP_BUILD project, never
the Layer 0 OS_DEV checkout.

Supported runner CLIs are detected and configured from the dashboard SETUP
view or with `danza runners`. PROJECT approval and decomposition must complete
before BUILD can start.
