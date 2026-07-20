# Guided AI Connection Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the technical, tmux-first Setup experience with a provider-neutral, provider-native connection wizard that launches clients, verifies real usability, and lets users choose 1–4 bosses only after verification.

**Architecture:** DANZABOSS keeps a single vendor-neutral runner registry, but each adapter declares its own safe installation and authentication probes. The UI owns a four-step project setup flow: choose a client, complete the client’s native sign-in, verify it, and add it to the ordered boss team. Runtime launch uses one project-scoped tmux session with managed panes; tmux commands remain a fallback detail, never the primary user flow.

**Tech Stack:** Python 3.10+ standard library, `unittest`, stdlib HTTP server, vanilla JavaScript/CSS, tmux where available, native provider CLI status/login commands.

## Global Constraints

- Never mark a client connected from `shutil.which` alone; installed, authenticated, and verified are separate states.
- Never expose or copy provider secrets; probes may inspect only provider-native status/doctor exit codes and redacted output.
- A fresh project starts with an empty boss selection; detected clients are never auto-selected.
- Only verified clients may enter the 1–4 boss order.
- Only the active Tony-D client is allowed to execute a turn; waiting clients are not spawned for ordinary setup.
- The UI must use plain language and must not require users to type tmux commands.
- Preserve the existing event contract, project-only CORTEX, handoff state, and runtime authorization boundaries.
- Provider-specific behavior belongs in adapters; the core runtime must remain model-neutral.

### Task 1: Provider-native runner health and authentication

**Files:**
- Modify: `danzaboss/workstation/runners.py`
- Modify: `danzaboss/product/connection.py`
- Test: `danzaboss/tests/test_workstation_runners.py`
- Test: `danzaboss/tests/test_activation.py`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- `KNOWN_RUNNERS` entries gain optional `healthcheck` and `authcheck` argv prefixes.
- `probe_runner(entry, run=subprocess.run) -> dict` returns `state`, `reason`, and redacted `detail`.
- `build_registry()` stores `state` and `auth` using the provider-native check instead of treating an empty headless command as authentication failure.
- Claude uses the documented `claude doctor` check; Codex uses the read-only
  `codex login status` check; Grok uses the documented read-only `grok models`
  catalog command; OpenCode uses `opencode auth list`; Gemini uses its
  documented `-p` mode for a bounded real connection check because it exposes
  no separate local auth-status command. Unsupported adapters remain explicit
  rather than being marked connected from binary presence.

- [x] **Step 1: Write failing tests** for Codex returning `auth="ok"` from a successful `codex login status`, for a nonzero status returning `auth="unauthenticated"`, and for explicit UI states that never treat `unprobed` as verified.
- [x] **Step 2: Run the focused tests**:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
python3 -m unittest \
  danzaboss.tests.test_workstation_runners \
  danzaboss.tests.test_activation \
  danzaboss.tests.test_danza_ui
```

Expected result: the new tests fail because Codex has no native auth probe and the registry has no explicit health state.

- [x] **Step 3: Implement the smallest probe contract** with injectable `run`, bounded timeout, provider-native checks where documented, and redacted failure messages.
- [x] **Step 4: Run the focused tests again** and require all new provider-state assertions to pass.
- [x] **Step 5: Preserve compatibility** by keeping existing `detected` and `auth` fields while adding the explicit state fields used by the new UI.

### Task 2: One project session with managed panes

**Files:**
- Modify: `danzaboss/product/connection.py`
- Modify: `danzaboss/workstation/server.py`
- Modify: `danzaboss/workstation/static/app.js`
- Modify: `danzaboss/workstation/static/app.css`
- Test: `danzaboss/tests/test_activation.py`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- `project_session_name(root) -> str` returns one stable project-scoped session name.
- `launch_runner(root, runner, config, ...) -> dict` returns the shared session, pane/window identity, attach fallback, and actual process health.
- `close_or_focus_runner(root, runner, ...) -> dict` is not required for setup; waiting clients remain unspawned until their turn.

- [x] **Step 1: Write failing tests** requiring two launches for one project to return the same tmux session, distinct pane targets, and a failed launch when the client exits immediately.
- [x] **Step 2: Run the focused activation/UI tests** and confirm the old per-runner session behavior fails the new assertions.
- [x] **Step 3: Implement shared-session launch** using `tmux new-session` for the first client and `tmux split-window` for subsequent explicit connections; retain a copyable fallback command only in the API response.
- [x] **Step 4: Add process/session verification** after launch so a shell wrapper that exits immediately becomes a visible connection failure.
- [x] **Step 5: Run focused tests and `node --check danzaboss/workstation/static/app.js`** before proceeding. When tmux is absent, the selected native client opens directly in a platform terminal.

### Task 3: Four-step Setup wizard with no automatic selection

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Modify: `danzaboss/workstation/static/app.js`
- Modify: `danzaboss/workstation/static/app.css`
- Modify: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- `setup_summary(root)` returns `connection_state`, `selected`, `verified`, `steps`, and persisted-team metadata without suggesting a lineup for a fresh project.
- UI states are `not_installed`, `needs_install`, `ready_to_connect`, `sign_in_required`, `verified`, and `failed`.
- `POST /api/setup` rejects unverified lineup members and does not write a routing file until the user confirms an ordered verified team.

- [x] **Step 1: Write failing UI/API tests** asserting fresh setup returns `lineup=[]`, no active boss, no selected checkboxes, provider-native status copy, and that unverified clients cannot be confirmed.
- [x] **Step 2: Run the focused UI tests** and confirm current auto-suggestion and technical copy fail the assertions.
- [x] **Step 3: Remove server-side auto-selection** from the no-routing fallback; preserve an existing routing file but label it as a saved team that the user can edit.
- [x] **Step 4: Replace the Setup markup** with a large progress header, one primary action per step, provider cards, explicit sign-in instructions, a verified-only boss order, and the 2–5 feature selector.
- [x] **Step 5: Replace raw notices** such as `tmux attach`, `auth=unprobed`, and `Found` with plain-language state and an expandable technical fallback.
- [x] **Step 6: Run UI tests and syntax checks** until the wizard contract is green.

### Task 4: End-to-end verification and handoff

**Files:**
- Modify: `INSTALL.md`
- Modify: `README.md`
- Modify: `RUNBOOK.md`
- Test: `danzaboss/tests/test_install_contract.py`
- Test: `danzaboss/tests/test_product_install_sh.py`

- [x] **Step 1: Add installer documentation tests** requiring the public flow to describe native client sign-in and the browser fallback, not manual tmux attachment.
- [x] **Step 2: Update the user-facing install/run instructions** with the four Setup steps and the explicit rule that installation is pending until a client is verified.
- [x] **Step 3: Run the full suite with localhost socket access** — 1,124
  tests passed with 14 documented skips:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore \
PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
python3 -m unittest discover -s danzaboss/tests -p 'test*.py'
```

Expected result: all tests pass with only the repository’s documented skips.

- [x] **Step 4: Run `node --check danzaboss/workstation/static/app.js` and `git diff --check`.**
- [ ] **Step 5: Test activation in disposable empty and existing Git repositories**, confirm the UI opens automatically, confirm a fresh Setup has no selected clients, and verify at least one real provider through its native login/status path.
- [x] **Step 6: Commit the implementation** and push the temporary branch
  `codex/production-danzaboss-install-flow`.

## Self-review

- Provider auth is adapter-owned and no client is trusted from binary presence alone.
- Setup cannot confirm a team before each selected client reaches verified state.
- The user sees one project session and a browser/native login flow, with tmux retained only as an internal host and fallback.
- Existing CORTEX, event normalization, runtime roles, assignments, handoffs, and redaction remain outside the connection UI changes.
- The final acceptance test exercises empty-repo activation, existing-repo activation, UI readiness, project-local CORTEX, provider verification, and the verified installation gate.
