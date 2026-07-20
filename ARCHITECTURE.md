# DANZABOSS Architecture

DANZABOSS has two boundaries: the product source repository and an activated
target application repository. The installer operates in the target and copies
the packaged payload into it. The target's `.danza/` directory is the runtime
boundary; project memory, handoffs, team state, event capture, and installation
proof stay there.

## Activation path

`install.sh` and `install.ps1` detect Python, Git, and the virtual-environment
module, explain mandatory dependencies, request approval, install the pinned
`Production-DANZABOSS` package, and call `danza activate`. Activation requires
Git, scaffolds the target, creates the project CORTEX database, starts the
dashboard on port `33000`, and records a machine-readable installation status.

The final installation gate requires all four paths: packaged files, project
initialization, a reachable dashboard, and a verified AI connection. A target
may be activated while the connection is pending, but it is not reported as
fully verified until Setup proves the selected client or provider path.

## Model-neutral runtime

`danzaboss/agents/definitions.json` is the canonical, vendor-neutral roster.
Claude, Gemini, Grok, Hermes, Codex, OpenCode, and future clients are adapters
that translate their native lifecycle and tool events into the DANZA event
contract. The runtime broker authorizes roles, capabilities, assignments,
scope, secrets, verification, and state transitions. A prompt can explain a
duty, but it cannot grant a capability.

Tony-D orchestrates and delegates. Jonathan is the only code writer. Bonnie
must verify completed work. Spawn receipts, assignments, and event records are
persisted under `.danza/runtime/`, so a claimed delegation without a real
receipt is rejected.

## Memory and events

CORTEX is project-only by default. Existing storage, retrieval, compression,
redaction, indexing, graph, UI, MCP, aging, and context-budget components stay
available. Runtime observations are redacted before they are stored in the
project event stream. The first task seeds memory; spawned tasks from the
second task onward receive relevant project-local context.

The human `.danza/handoff.md` remains compatible with the established handoff
format. `.danza/runtime/handoff-state.json` is a small machine-validation
sidecar: the bootstrap marker means new-project onboarding, a valid sidecar
means continuation, and a missing or corrupt sidecar blocks execution.

## Process hosting

DANZA uses a native subprocess host across platforms. tmux may be used by an
operator when available, but it is optional, never auto-installed, and not a
runtime dependency.
