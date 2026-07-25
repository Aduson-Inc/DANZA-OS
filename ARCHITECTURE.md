# DANZABOSS Architecture

DANZABOSS has two boundaries: the product source repository (profile
`OS_DEV`) and an activated target application repository (profile
`APP_BUILD`). The installer operates in the target and copies the packaged
payload into it. The target's `.danza/` directory is the runtime boundary;
project memory, plans, team state, and installation proof stay there. The
source checkout is never activated as an application project.

## Activation path

`install.sh` and `install.ps1` detect Python 3.10+ and Git, explain mandatory
dependencies, request approval, create a project-local environment at
`.danza/runtime/venv`, install the pinned `danza-os` package, and call
`danza activate`. Activation requires Git, scaffolds the target, creates the
project CORTEX database, starts the dashboard on `127.0.0.1:33000`, and
records `.danza/runtime/installation.json`. The result is `verified` only
after the Connect stage proves an AI connection; until then it is
`awaiting_ai_connection`.

The scaffold is idempotent: each file is created, skipped as up to date, or
skipped as user-modified, and `.danza/.scaffold-version` records a content
hash for every bundled file. A managed block in the target's `CLAUDE.md` is
maintained between explicit markers; the rest of that file is untouched.

## Sequential relay execution

One boss at a time. `.danza/runtime/routing.json` holds the lineup of one to
four connected, authenticated runner tools and `features_per_turn`, the turn
quota of 2–5 verified units — the one user-facing turn-size knob. The
execution ledger lives in `.danza/plan.json`.

A turn is governed by a turn lock: only the current boss may start work, and
only on the exact next dependency-ready unit. A unit counts as complete only
through a passing verification run with recorded evidence and timing; each
completion is counted once and feeds estimate-versus-actual calibration. A
turn concludes as: continue, quota reached, no work left, blocked (with a
recorded reason), or hard stop (a flagged unit needs explicit attention).
When the quota is reached, the next turn is routed to the next runner in the
lineup and recorded as a handoff. Approved additions wait at a safe boundary;
they never replace active work mid-turn.

Built-in runtime automation watches team state, compiles the turn brief, and
starts each turn in a project terminal — a tmux pane when tmux is available,
a headless subprocess otherwise — with the ignition phrase "Who's the Boss?".
It is a deterministic postman: it never makes build decisions and never kills
a live session.

## Memory: CORTEX

CORTEX is project-scoped at `.danza/cortex/cortex.db`; a project run never
reads a global store. Before each turn the compiled brief is written to
`.danza/runtime/turn-brief.md` with four sections: the turn goal, quota, and
stop rule; the assigned units with their verification commands; what the
previous boss completed; and a role-budgeted package of what the team already
knows. Specialists get their own role-budgeted context. Budgets are adaptive
per role — a base allocation with one qualified expansion up to a ceiling —
and are internal constants, not user settings. If memory compilation fails,
the brief degrades to its deterministic sections and the build proceeds;
memory never blocks a turn.

Session start injects only a pointer to the live turn brief, or a compact
titles-and-ids index when no turn is active. Full observation bodies are
pulled on demand with `danza cortex get`, `search`, `retrieve`, and
`context --driver <agent-id>`, or through the read-only MCP server
(`danza cortex mcp`). Every brief compilation records what the injected
context replaced; the dashboard token-savings meter aggregates only those
recorded telemetry rows.

## Hooks

The scaffold wires Claude Code hooks in the target: PreToolUse runs
`danza hook pretooluse`, SessionStart restores state and injects CORTEX
context, PostToolUse captures eligible observations, and Stop runs the CORTEX
distillation gate. Guards fail closed where the constitution binds
(APP_BUILD): destructive commands are denied in every profile, oversized
dispatch payloads are blocked, and protected files are immutable. The Stop
gate requires a session with pending events to record observations
(`danza cortex observe`, or `--nothing-meaningful`) before it ends.

## Dashboard

One local process on `127.0.0.1:33000` serves the one-flow single-page app.
Stage state (connect, describe, approve, build, done) is derived server-side
from real project state; the PROJECT workflow endpoints (discover, scope,
approve, decompose) and BUILD endpoints sit behind it. The full CORTEX UI is
mounted at `/cortex/` in the same process. All POST routes are origin-checked
and serialized.

## Frontier scout

The weekly frontier scout runs only in the canonical product source
repository: the check requires the `OS_DEV` profile and fails closed, so
customer installs never run it and never need API keys. When `TAVILY_API_KEY`
is present and at least seven days have passed since the last run, dashboard
polls opportunistically trigger a research pass and a local code-health pass.
Proposals land in `.danza/frontier/` with per-item approve/dismiss decisions;
approved items go to the additions backlog. Nothing auto-builds.

## Model-neutral roster

`danzaboss/agents/definitions.json` is the vendor-neutral roster identity
source; the scaffold copies it to `.danza/agents/definitions.json`, and the
character prompts and dashboard resolve names, roles, and responsibilities
from it. Tony-D orchestrates and delegates, Jonathan is the only code writer,
Bonnie verifies completed work, and specialists are dispatched selectively by
unit type — never the full roster by reflex.
