# Shared AI Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one project-owned tmux workspace hold every selected AI client in saved boss order, open one terminal surface, and route only the active Tony-D turn into its pane.

**Architecture:** A project-local workspace sidecar records the exact tmux session and stable pane IDs. Connection setup creates or reconciles that workspace; the conductor reuses it instead of creating a second session. The browser reports pane order, active/waiting state, attach instructions, and explicit fallback status.

**Tech Stack:** Python standard library, tmux CLI on POSIX, existing vanilla JavaScript/CSS dashboard, `unittest`.

## Global Constraints

- One exact project tmux session per activated project; no second conductor session.
- One pane per selected runner, ordered by the saved lineup.
- Only the active runner receives ignition and work; waiting runners remain idle.
- Provider authentication stays inside native clients; secrets never enter shell strings or durable logs.
- Unverified runners cannot be selected or used for onboarding.
- tmux remains optional; no-tmux fallback is explicit and never claims pane support.
- Unknown tmux sessions are never killed or repurposed automatically.

---

### Task 1: Add the project-local workspace contract

**Files:**

- Create: `danzaboss/workstation/workspace.py`
- Test: `danzaboss/tests/test_workstation_workspace.py`

**Interfaces:** `WORKSPACE_RELPATH`, `session_name(root)`, `load_workspace(root)`, `save_workspace(root, data)`, and `workspace_summary(root)`.

- [ ] Write failing tests for sanitized shared session names, stable pane-ID round trips, atomic saves, and invalid sidecar rejection.
- [ ] Run `python3 -m unittest test_workstation_workspace -v` and confirm the new tests fail because the module is absent.
- [ ] Implement schema version 1 validation for `session`, `host`, `order`, `panes`, `active_runner`, and `terminal_opened`; write JSON through a sibling temporary file and `replace()`.
- [ ] Rerun `python3 -m unittest test_workstation_workspace -v`; all tests must pass.
- [ ] Commit with `git commit -m "Add project AI workspace state contract"`.

### Task 2: Reconcile connection panes and save the ordered workspace

**Files:**

- Modify: `danzaboss/product/connection.py`
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_activation.py`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:** Preserve `launch_runner(...) -> dict`; add `prepare_workspace(root, lineup, config) -> dict` and return its result under the setup API's `workspace` key.

- [ ] Add failing tests proving the first runner opens one terminal, later runners only add panes, and `prepare_workspace` returns the saved order with the first runner active.
- [ ] Run the focused activation/setup tests and confirm those assertions fail before implementation.
- [ ] Implement one exact project session, stable runner-to-pane mapping, missing-pane creation, safe pane reordering with `swap-pane`, and one-time terminal attach. Never send credentials through tmux.
- [ ] Call `prepare_workspace` only after routing validation and return explicit native-terminal fallback data when tmux is unavailable.
- [ ] Run `python3 -m unittest test_activation.ActivationContract test_danza_ui.TestSetupApi -v`.
- [ ] Commit with `git commit -m "Reconcile selected AI clients in one project workspace"`.

### Task 3: Route the conductor into the active workspace pane

**Files:**

- Modify: `danzaboss/workstation/hosts.py`
- Modify: `danzaboss/workstation/conductor.py`
- Test: `danzaboss/tests/test_workstation_hosts.py`
- Test: `danzaboss/tests/test_workstation_conductor_loop.py`

**Interfaces:** Extend `SessionHost.ignite(name, cwd, argv, runner=None)`. `TmuxHost` targets the stored pane for `runner`; `HeadlessHost` ignores the optional runner.

- [ ] Add a failing test proving active ignition sends `Who's the Boss?` to the mapped pane and does not issue `new-session`.
- [ ] Run `python3 -m unittest test_workstation_hosts test_workstation_conductor_loop -v` and confirm the new test fails.
- [ ] Make conductor and TmuxHost use the shared `session_name`; fail closed when the workspace or active pane is absent; preserve existing no-auto-kill behavior.
- [ ] Pass the routed runner from `Conductor.tick` to `host.ignite`.
- [ ] Run `python3 -m unittest test_workstation_hosts test_workstation_conductor test_workstation_conductor_loop -v`.
- [ ] Commit with `git commit -m "Route active boss turns into the shared workspace pane"`.

### Task 4: Make the browser explain the workspace clearly

**Files:**

- Modify: `danzaboss/workstation/static/app.js`
- Modify: `danzaboss/workstation/static/app.css`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:** Setup renders one concise `AI WORKSPACE` block with session name, ordered panes, active/waiting labels, and one `OPEN WORKSPACE` action or exact fallback command.

- [ ] Add failing static assertions for `AI WORKSPACE`, `OPEN WORKSPACE`, active/waiting labels, and removal of duplicate-terminal instructions.
- [ ] Run the focused static UI test and confirm it fails before implementation.
- [ ] Render the workspace below connection cards and above boss order. Keep all mutation feedback in the existing live-update area.
- [ ] Add the single open/attach action and show explicit no-tmux status without pretending panes exist.
- [ ] Run the focused UI/API tests, `node --check danzaboss/workstation/static/app.js`, and `git diff --check`.
- [ ] Commit with `git commit -m "Explain shared AI workspace in setup"`.

### Final verification

- [ ] Run the workstation connection, host, conductor, and UI test slice.
- [ ] Rerun stale-port cleanup and project-root UI identity tests.
- [ ] Verify a fresh repository has no selected lineup before user action.
- [ ] Verify a two-runner lineup creates one session, two panes, one terminal attach, and correct active/waiting order.
- [ ] Verify unavailable runners and unknown occupied ports fail safely.
- [ ] Record final branch, commits, tests, and any full-suite limitation.
