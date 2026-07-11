# Phase 2 — DANZA-OS Dashboard Implementation Plan

> **STATUS: COMPLETED 2026-07-11** — executed via subagent-driven development,
> commits 72d8b24..0e77395 on main; final whole-branch review READY-TO-MERGE
> (0 Critical; the 1 Important — SSE token coverage for runners/wizard state —
> fixed in 0e77395); suite 821 green.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md` §6 (Phase 2), plus D4 from §3 and the cross-cutting rules in §11.

**Goal:** `danza ui` serves the DANZA-OS product dashboard on `127.0.0.1:33100` — OVERVIEW · ONBOARD · MODELS · BUILD tabs over real repo state, with the entire CORTEX UI mounted at `/cortex/*` in the same process against the same store.

**Architecture:** One new stdlib HTTP server module `danzaboss/workstation/server.py` whose handler **subclasses** `CortexUIHandler` — dashboard routes at `/`, and `/cortex/*` requests get their prefix stripped and delegated to the parent class (one process, one store handle, D4). The CORTEX front-end currently hard-codes absolute `/api/` and `/static/` URLs, so Task 1 makes it origin-relative (it then works both standalone on :33000 and mounted at `/cortex/`). Phase 2 tabs are read-only windows over existing state files; Phases 3–4 make them interactive.

**Tech Stack:** Python 3.10+ stdlib only (`http.server`, `json`, `urllib`, `webbrowser`), vanilla JS/CSS with no build step.

## Global Constraints

- **Stdlib only** in all OS code; no pip installs required to run tests (spec §11).
- **Bind `127.0.0.1` only; default port 33100** (CORTEX keeps 33000) (spec §6).
- **Visual identity: the ADUSON system verbatim** — tokens from `danzaboss/cortex/ui/static/app.css`: `--void #0a0a0c`, `--carbon #141417`, `--gunmetal #3a3d44`, `--silver #9ba1ab`, `--crimson #c8102e`, `--ember #e8354f`, blade clip-path, Chakra Petch / IBM Plex, card + drawer + chip + tab patterns, background artwork treatment (spec §6).
- **Nav tabs: OVERVIEW · ONBOARD · MODELS · BUILD · CORTEX (redirect)** (spec §6).
- **Style is law:** `cortex/ui/server.py` is the reference for the server module; `tests/test_cortex_ui.py` is the reference for HTTP tests (spec §11).
- **Fail closed / never silent:** missing state renders as honest empty-state; corrupt state surfaces as an `error` field, never a crash and never dropped (spec §11).
- **Rule 16:** delete nothing.
- **Suite green at the phase boundary:** finish with `./danzaboss/run_tests.sh` all green.
- Type hints on public functions; module + function docstrings that state *why* (CLAUDE.md coding standards).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `danzaboss/cortex/ui/static/index.html` | modify | origin-relative asset URLs + reciprocal DANZA-OS backlink |
| `danzaboss/cortex/ui/static/app.js` | modify | origin-relative API URLs + backlink reveal when mounted |
| `danzaboss/cortex/ui/static/app.css` | modify | CSS-relative background URL + anchor-chip style |
| `danzaboss/cortex/ui/server.py` | modify | `_static()` gains a `static_dir` parameter (reused by the subclass) |
| `danzaboss/workstation/server.py` | create | dashboard server: handler, overview/conductor/onboarding/plan/runners APIs, SSE, CORTEX mount |
| `danzaboss/workstation/static/index.html` | create | dashboard shell: topbar, 4 tab views + CORTEX link |
| `danzaboss/workstation/static/app.css` | create | copy of CORTEX app.css + dashboard-specific additions |
| `danzaboss/workstation/static/app.js` | create | tab rendering, SSE live refresh |
| `danzaboss/workstation/static/background.png` | create | copy of the CORTEX background artwork |
| `danzaboss/cli.py` | modify | `danza ui [dir] [--port N] [--no-open]` command |
| `danzaboss/tests/test_cortex_ui.py` | modify | mountability tests (Task 1) |
| `danzaboss/tests/test_danza_ui.py` | create | all dashboard tests |
| `pyproject.toml` | modify | package `danzaboss/workstation/static/*` |
| `CLAUDE.md` | modify | dashboard command + test count sync |

Existing data sources consumed (verified 2026-07-11):

- `.danza/runtime/team-state.json` — dict with `current_boss`, `previous_boss`, `turn_number`, `features_completed_this_turn`, `max_features_per_turn`, `handoff_required`, `status` (Rule 45).
- `.danza/runtime/conductor-log.jsonl` — one JSON object per line: `{"ts": iso, "event": str, ...fields}` (`workstation/conductor.py` `log()`, `LOG_RELPATH`).
- `.danza/plan.json` — `{"spec_ref": str, "tasks": [...], "order": [ids]}`; parse with `workstation.planner.parse_plan` (raises `PlanningError`). `Task` fields: `id, description, verification, subtasks, kind, size_est, depends_on, writes, flags`. `VerificationKind` values: `automated_test, command_output, http_check, schema_check, manual_gate`.
- `.danza/runtime/runners.json` — `{"version", "boss", "session_host", "permission_mode", "runners": {name: {..., "detected": bool}}}`; `workstation.runners.load_runners` (raises `RunnerError`); never auto-created here (the CLI/`/models` owns writes).
- Wizard state — `workstation.wizard.Wizard(root)`: `.flow()`, `.status(step_id)`, `.project_type()`, `.answers`, `.is_complete()`, `.current_step()`; works on an empty repo (empty shape).
- Profile — `kernel.profile.active_profile(root)`; heuristic: `team-state.json` exists → APP_BUILD, else OS_DEV; `DANZA_PROFILE` env overrides (tests must pop it).
- CORTEX — `cortex.commands.db_path(root)`, `cortex.identity.resolve_project(root)`, `cortex.events.CaptureLog(db).stats(project)`, `cortex.sqlite_backend.SqliteBackend(db).all(project)`, `cortex.inject.est_tokens(text)`.

---

### Task 1: CORTEX front-end goes origin-relative (mount prerequisite)

The CORTEX front-end hard-codes `/api/...` and `/static/...`. Mounted at `/cortex/`, those would escape the mount and hit dashboard routes. Relative URLs resolve against the page URL (`/` standalone, `/cortex/` mounted), so one front-end serves both. Also adds the reciprocal "DANZA-OS" button (spec §6: "CORTEX UI gains a reciprocal 'DANZA-OS' button"), revealed only when the page is served under `/cortex/`.

**Files:**
- Modify: `danzaboss/cortex/ui/static/index.html` (lines 11, 40–45, 171)
- Modify: `danzaboss/cortex/ui/static/app.js` (all `"/api/` + `` `/api/ `` call sites, line 538 EventSource; add mount detection after the `api()` helper ~line 39)
- Modify: `danzaboss/cortex/ui/static/app.css` (line 29 background URL; append anchor-chip rule)
- Test: `danzaboss/tests/test_cortex_ui.py` (append a class)

**Interfaces:**
- Consumes: nothing new.
- Produces: a CORTEX front-end whose every asset/API reference is origin-relative, and an `<a id="danza-link" class="chip" href="/" hidden>DANZA-OS</a>` element in the topbar. Task 4's mount tests depend on this.

- [ ] **Step 1: Write the failing test**

Append to `danzaboss/tests/test_cortex_ui.py` (before the final `if __name__ == "__main__":` block):

```python
class TestFrontEndMountable(unittest.TestCase):
    """Phase 2 (D4): the CORTEX front-end must be origin-relative so the
    DANZA dashboard can mount it under /cortex/* unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server, cls.port = serve_in_thread(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_no_absolute_static_or_api_references(self):
        _, _, html = get(self.port, "/")
        self.assertNotIn(b'"/static/', html)
        _, _, js = get(self.port, "/static/app.js")
        self.assertNotIn(b'"/api/', js)
        self.assertNotIn(b"`/api/", js)
        _, _, css = get(self.port, "/static/app.css")
        self.assertNotIn(b'url("/static/', css)

    def test_reciprocal_danza_link_ships_hidden(self):
        _, _, html = get(self.port, "/")
        self.assertIn(b'id="danza-link"', html)
        self.assertIn(b"DANZA-OS", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/DANZA-OS && python3 danzaboss/tests/test_cortex_ui.py TestFrontEndMountable -v`
Expected: both tests FAIL (`b'"/static/' unexpectedly found`, `b'id="danza-link"' not found`).

- [ ] **Step 3: Implement — index.html**

In `danzaboss/cortex/ui/static/index.html`:

Line 11: `<link rel="stylesheet" href="/static/app.css">` → `<link rel="stylesheet" href="static/app.css">`

Line 171: `<script src="/static/app.js"></script>` → `<script src="static/app.js"></script>`

In the `<div class="topbar-right">` block (line 40), add the backlink as the first child:

```html
  <div class="topbar-right">
    <a id="danza-link" class="chip" href="/" hidden>DANZA-OS</a>
    <input id="search" class="search" type="search"
           placeholder="Search memory…" autocomplete="off">
```

- [ ] **Step 4: Implement — app.js**

Run: `sed -i 's|"/api/|"api/|g; s|`/api/|`api/|g' danzaboss/cortex/ui/static/app.js`

(This rewrites every fetch call site — lines 151, 158, 175, 240, 310, 319, 345, 361, 371, 480 — and the `EventSource("/api/events?stream=1")` at line 538. Verify with `grep -n '"/api/\|`/api/' danzaboss/cortex/ui/static/app.js` → no matches.)

Then add mount detection directly after the `api()` helper function (after line 39):

```js
/* Mounted under the DANZA dashboard (/cortex/*)? Reveal the way back (D4). */
if (location.pathname.startsWith("/cortex")) $("#danza-link").hidden = false;
```

- [ ] **Step 5: Implement — app.css**

Line 29: `background: url("/static/background.png") center / cover fixed no-repeat, var(--void);` → `background: url("background.png") center / cover fixed no-repeat, var(--void);`

(CSS URLs resolve against the stylesheet location — `/static/app.css` standalone, `/cortex/static/app.css` mounted — so the bare filename is correct in both.)

Append at the end of the file:

```css
/* anchor rendered as a chip (the DANZA-OS backlink) */
a.chip { text-decoration: none; display: inline-flex; align-items: center; }
```

- [ ] **Step 6: Run the whole CORTEX UI test file**

Run: `python3 danzaboss/tests/test_cortex_ui.py -v`
Expected: ALL tests PASS (the pre-existing classes prove standalone mode still works with relative paths).

- [ ] **Step 7: Commit**

```bash
git add danzaboss/cortex/ui/static/ danzaboss/tests/test_cortex_ui.py
git commit -m "feat(cortex-ui): origin-relative front-end + DANZA-OS backlink (mountable under /cortex/)"
```

---

### Task 2: Dashboard server core — static shell + `/api/overview`

Creates `danzaboss/workstation/server.py` mirroring `cortex/ui/server.py` construction, with the OVERVIEW payload assembled by a pure `overview(root)` function. Also generalizes the parent's `_static()` to take a directory so the subclass reuses it (DRY) instead of copying it.

**Files:**
- Modify: `danzaboss/cortex/ui/server.py:101-113` (`_static` signature)
- Create: `danzaboss/workstation/server.py`
- Create: `danzaboss/workstation/static/index.html` (minimal stub this task; Task 6 replaces it)
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: `CortexUIHandler` (its `_json`, `_static`, class attrs `root`/`db_path`/`project`); `active_profile(root) -> Profile` (`.to_dict()`); `parse_plan(data) -> tuple[Task, ...]`; `resolve_project(root) -> str`; `cortex.commands.db_path(root) -> str`; `CaptureLog(db).stats(project) -> dict`; `SqliteBackend(db).all(project)`; `est_tokens(str) -> int`; `TEAM_STATE_RELPATH`, `LOG_RELPATH` from `.conductor`; `PLAN_JSON_RELPATH` from `.planner`; `RUNNERS_RELPATH`, `load_runners`, `RunnerError` from `.runners`.
- Produces (later tasks rely on these exact names):
  - `overview(root: str) -> dict` — keys `project: str`, `root: str`, `profile: dict`, `team_state: dict | None`, `plan: dict | None`, `spec_exists: bool`, `runners: dict | None`, `cortex: dict`, optional `team_state_error: str`.
  - `_plan_summary(root: str) -> dict | None` — `None` if no plan.json; `{"error": str}` on corrupt/invalid; else `{"spec_ref": str, "tasks": int, "leaves": int, "order": list[str]}`.
  - `_runner_summary(root: str) -> dict | None` — `None` if no runners.json; `{"error": str}` on invalid; else `{"boss": str | None, "session_host": str, "detected": list[str]}`.
  - `_read_json(path: Path) -> tuple[object, str]` — `(data, "")`, `(None, "")` if missing, `(None, reason)` if corrupt.
  - `class DanzaUIHandler(CortexUIHandler)` with `_redirect(location: str)`.
  - `make_server(root: str, port: int = 0) -> ThreadingHTTPServer`, `serve(root, port=None, open_browser=True)`, `serve_in_thread(root, port=0) -> tuple[ThreadingHTTPServer, int]`, `DEFAULT_PORT = 33100`.

- [ ] **Step 1: Write the failing test**

Create `danzaboss/tests/test_danza_ui.py`:

```python
"""Phase 2 acceptance: the DANZA dashboard serves every tab's API, mounts the
real CORTEX UI under /cortex/*, and stays read-only outside the mount."""
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.workstation.server import overview, serve_in_thread


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


TEAM_STATE = {
    "current_boss": "claude", "previous_boss": None, "turn_number": 3,
    "features_completed_this_turn": 1, "max_features_per_turn": 2,
    "handoff_required": False, "status": "in_progress",
}

PLAN = {
    "spec_ref": ".danza/spec.md",
    "tasks": [
        {"id": "1", "description": "Walking skeleton",
         "subtasks": [
             {"id": "1.1", "description": "Health endpoint returns ok",
              "kind": "build", "size_est": 20, "writes": ["app.py"],
              "verification": {"kind": "automated_test",
                               "detail": "pytest -k health"}},
         ]},
        {"id": "2", "description": "Login form renders",
         "kind": "build", "size_est": 25, "writes": ["login.py"],
         "verification": {"kind": "automated_test", "detail": "pytest -k login"}},
    ],
    "order": ["1.1", "2"],
}


def seed_activated_repo(root):
    """A repo that looks post-onboarding: team-state, plan, spec, conductor
    log, one CORTEX observation — every OVERVIEW data source populated."""
    runtime = Path(root) / ".danza" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "team-state.json").write_text(json.dumps(TEAM_STATE))
    (Path(root) / ".danza" / "plan.json").write_text(json.dumps(PLAN))
    (Path(root) / ".danza" / "plan.md").write_text("# Build order\n1. 1.1\n2. 2\n")
    (Path(root) / ".danza" / "spec.md").write_text("# Spec\n")
    (runtime / "conductor-log.jsonl").write_text(
        json.dumps({"ts": "2026-07-11T00:00:00+00:00", "event": "ignite",
                    "session": "danza-boss", "runner": "claude"}) + "\n" +
        json.dumps({"ts": "2026-07-11T00:05:00+00:00", "event": "session_end",
                    "turn_number": 3}) + "\n")
    store = ObservationStore(SqliteBackend(commands.db_path(root)))
    store.upsert(Observation(
        title="Dashboard seed fact", summary="phase 2 fixture",
        type=ObsType.DECISION.value, project=os.path.basename(root),
        importance=Importance.CRITICAL.value, confidence=90,
        reasoning="seeded for HTTP tests", concepts=["dashboard"]))


class TestOverview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the profile env override would defeat the team-state heuristic
        cls._saved_profile = os.environ.pop("DANZA_PROFILE", None)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        seed_activated_repo(cls.root)
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()
        if cls._saved_profile is not None:
            os.environ["DANZA_PROFILE"] = cls._saved_profile

    def test_overview_assembles_every_product_surface(self):
        status, ctype, body = get(self.port, "/api/overview")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        o = json.loads(body)
        self.assertEqual(o["team_state"]["current_boss"], "claude")
        self.assertEqual(o["team_state"]["turn_number"], 3)
        self.assertEqual(o["profile"]["name"], "APP_BUILD")
        self.assertEqual(o["plan"]["tasks"], 3)
        self.assertEqual(o["plan"]["leaves"], 2)
        self.assertEqual(o["plan"]["order"], ["1.1", "2"])
        self.assertTrue(o["spec_exists"])
        self.assertIsNone(o["runners"])  # no runners.json seeded
        self.assertEqual(o["cortex"]["observations_stored"], 1)
        self.assertGreater(o["cortex"]["read_tokens"], 0)
        self.assertTrue(o["project"])

    def test_overview_unactivated_repo_is_honest(self):
        with tempfile.TemporaryDirectory() as bare:
            o = overview(bare)
        self.assertIsNone(o["team_state"])
        self.assertIsNone(o["plan"])
        self.assertIsNone(o["runners"])
        self.assertFalse(o["spec_exists"])
        self.assertEqual(o["profile"]["name"], "OS_DEV")
        self.assertNotIn("team_state_error", o)

    def test_corrupt_team_state_surfaces_not_crashes(self):
        with tempfile.TemporaryDirectory() as bad:
            runtime = Path(bad) / ".danza" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "team-state.json").write_text("{not json")
            o = overview(bad)
        self.assertIsNone(o["team_state"])
        self.assertIn("team_state_error", o)

    def test_index_serves_and_unknown_route_404s(self):
        status, ctype, body = get(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"DANZA-OS", body)
        try:
            status, _, _ = get(self.port, "/api/nope")
        except urllib.error.HTTPError as e:
            status = e.code
            e.close()  # HTTPError carries an open response socket
        self.assertEqual(status, 404)

    def test_post_outside_the_mount_is_rejected(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/overview", data=b"{}",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 405")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)
            e.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'danzaboss.workstation.server'`.

- [ ] **Step 3: Generalize the parent's static helper**

In `danzaboss/cortex/ui/server.py`, change the `_static` method (line 101) from:

```python
    def _static(self, name: str) -> None:
        path = os.path.join(_STATIC_DIR, os.path.basename(name))
```

to:

```python
    def _static(self, name: str, static_dir: str = _STATIC_DIR) -> None:
        path = os.path.join(static_dir, os.path.basename(name))
```

(No other line of the method changes. Existing callers pass no `static_dir`, so behavior is identical; the dashboard subclass passes its own directory.)

- [ ] **Step 4: Create the stub index + the server module**

```bash
mkdir -p danzaboss/workstation/static
```

Create `danzaboss/workstation/static/index.html` (Task 6 replaces this with the real shell; the stub keeps Task 2 independently shippable):

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>DANZA-OS — product dashboard</title></head>
<body><h1>DANZA-OS</h1><p>Dashboard shell lands in Task 6.</p></body>
</html>
```

Create `danzaboss/workstation/server.py`:

```python
"""DANZA-OS product dashboard — stdlib HTTP server on 127.0.0.1:33100 (Phase 2).

One process serves the whole product shell (design decision D4): the DANZA
dashboard at `/` and the complete CORTEX UI mounted under `/cortex/*` against
the same store. The dashboard is a read-only window over an activated repo's
product state — profile, team-state, plan progress, conductor log, runner
registry, wizard status. Later phases plug interactive surfaces into this
shell (/onboard forms in Phase 3, /models + BUILD controls in Phase 4), which
is why the read APIs live in module-level functions the handler only wires up.

Stdlib only. No build step; static assets live next to this file.
`cortex/ui/server.py` is the style reference (spec section 11).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from ..cortex import commands as cortex_commands
from ..cortex.events import CaptureLog
from ..cortex.identity import resolve_project
from ..cortex.inject import est_tokens
from ..cortex.sqlite_backend import SqliteBackend
from ..cortex.ui.server import CortexUIHandler
from ..kernel.profile import active_profile
from .conductor import LOG_RELPATH, TEAM_STATE_RELPATH
from .planner import PLAN_JSON_RELPATH, PlanningError, parse_plan
from .runners import RUNNERS_RELPATH, RunnerError, load_runners

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DEFAULT_PORT = 33100  # CORTEX keeps 33000 (D4)


# -- read-side assemblers (pure functions of root, unit-testable) -----------

def _read_json(path: Path) -> tuple[object, str]:
    """(data, "") on success, (None, "") if missing, (None, reason) if corrupt.

    Missing state is not an error — the dashboard renders absence honestly;
    corruption is reported, never silently dropped (spec section 11)."""
    if not path.exists():
        return None, ""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), ""
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def _team_state(root: str) -> tuple[Optional[dict], str]:
    data, err = _read_json(Path(root) / TEAM_STATE_RELPATH)
    if data is not None and not isinstance(data, dict):
        return None, "team-state.json is not a JSON object"
    return data, err


def _plan_summary(root: str) -> Optional[dict]:
    """Plan progress for the home screen. Validation goes through the real
    planner parser so the dashboard can never present a plan the conductor
    would refuse."""
    data, err = _read_json(Path(root) / PLAN_JSON_RELPATH)
    if data is None:
        return {"error": err} if err else None
    try:
        tasks = parse_plan(data)
    except PlanningError as e:
        return {"error": str(e)}

    def walk(ts) -> tuple[int, int]:
        total = leaves = 0
        for t in ts:
            total += 1
            sub_total, sub_leaves = walk(t.subtasks)
            total += sub_total
            leaves += sub_leaves if t.subtasks else 1
        return total, leaves

    total, leaves = walk(tasks)
    order = data.get("order", []) if isinstance(data, dict) else []
    return {"spec_ref": data.get("spec_ref", ""), "tasks": total,
            "leaves": leaves, "order": list(order)}


def _runner_summary(root: str) -> Optional[dict]:
    if not (Path(root) / RUNNERS_RELPATH).exists():
        return None
    try:
        config = load_runners(root)
    except RunnerError as e:
        return {"error": str(e)}
    return {"boss": config.get("boss"),
            "session_host": config.get("session_host"),
            "detected": sorted(n for n, e in config.get("runners", {}).items()
                               if e.get("detected"))}


def _cortex_stats(root: str) -> dict:
    """The home-screen CORTEX strip — the same numbers the CORTEX stats view
    computes, so the two UIs can never disagree."""
    db = cortex_commands.db_path(root)
    project = resolve_project(root)
    s = CaptureLog(db).stats(project)
    count = read_tokens = 0
    for o in SqliteBackend(db).all(project):
        count += 1
        read_tokens += est_tokens(o.summary + o.reasoning)
    s.update({"observations_stored": count, "read_tokens": read_tokens})
    return s


def overview(root: str) -> dict:
    """Everything the OVERVIEW screen needs in one payload (spec section 6)."""
    team, team_err = _team_state(root)
    out = {"project": resolve_project(root),
           "root": os.path.abspath(root),
           "profile": active_profile(root).to_dict(),
           "team_state": team,
           "plan": _plan_summary(root),
           "spec_exists": (Path(root) / ".danza" / "spec.md").exists(),
           "runners": _runner_summary(root),
           "cortex": _cortex_stats(root)}
    if team_err:
        out["team_state_error"] = team_err
    return out


# -- handler -----------------------------------------------------------------

class DanzaUIHandler(CortexUIHandler):
    """Dashboard routes at `/`; inherited CORTEX routes under `/cortex/*`.

    Subclassing (not wrapping) keeps D4 honest: one process, one handler
    hierarchy, one store handle — the mount strips the path prefix and lets
    the parent class do exactly what it does standalone."""

    server_version = "DanzaUI/1.0"

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                self._static("index.html", static_dir=_STATIC_DIR)
            elif route.startswith("/static/"):
                self._static(route[len("/static/"):], static_dir=_STATIC_DIR)
            elif route == "/api/overview":
                self._json(overview(self.root))
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 — surface as JSON, never crash the server
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def do_POST(self):
        self._json({"error": "read-only: product state is CLI-governed"}, 405)


# -- lifecycle ----------------------------------------------------------------

def make_server(root: str, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only. port=0 -> ephemeral (tests)."""
    handler = type("BoundHandler", (DanzaUIHandler,), {
        "root": root,
        "db_path": cortex_commands.db_path(root),
        "project": resolve_project(root),
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(root: str, port: Optional[int] = None,
          open_browser: bool = True) -> None:
    server = make_server(root, DEFAULT_PORT if port is None else port)
    host, bound = server.server_address[0], server.server_address[1]
    url = f"http://{host}:{bound}"
    print(f"DANZA-OS dashboard: {url}  (CORTEX at {url}/cortex/ — Ctrl-C to stop)")
    if open_browser:
        # after bind, before serve_forever blocks — the timer fires once the
        # loop is accepting, so the first page load never races the socket
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def serve_in_thread(root: str, port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """Test/daemon helper: start on an ephemeral port, return (server, port)."""
    server = make_server(root, port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v` — expected: all 5 PASS.
Run: `python3 danzaboss/tests/test_cortex_ui.py -v` — expected: all PASS (the `_static` signature change is backwards-compatible).

- [ ] **Step 6: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/workstation/static/index.html danzaboss/cortex/ui/server.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): DANZA dashboard server core with /api/overview"
```

---

### Task 3: Conductor log tail + SSE change token

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: `LOG_RELPATH`, `TEAM_STATE_RELPATH`, `PLAN_JSON_RELPATH` (already imported).
- Produces: `conductor_tail(root: str, limit: int = 100) -> dict` (`{"items": [event dicts, newest first]}`); `snapshot_token(root: str) -> str`; GET `/api/conductor?limit=N`; GET `/api/events` (SSE).

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_danza_ui.py` (before `if __name__ == "__main__":`), and extend the imports line:

```python
from danzaboss.workstation.server import (conductor_tail, overview,
                                          serve_in_thread, snapshot_token)
```

```python
class TestConductorTail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        seed_activated_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tail_is_newest_first(self):
        tail = conductor_tail(self.root)
        self.assertEqual([e["event"] for e in tail["items"]],
                         ["session_end", "ignite"])

    def test_limit_keeps_the_newest(self):
        tail = conductor_tail(self.root, limit=1)
        self.assertEqual([e["event"] for e in tail["items"]], ["session_end"])

    def test_missing_log_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as bare:
            self.assertEqual(conductor_tail(bare), {"items": []})

    def test_unparseable_line_surfaces(self):
        log = Path(self.root) / ".danza" / "runtime" / "conductor-log.jsonl"
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("{broken\n")
        items = conductor_tail(self.root)["items"]
        self.assertEqual(items[0]["event"], "unparseable")

    def test_snapshot_token_moves_on_state_write(self):
        t1 = snapshot_token(self.root)
        state_path = Path(self.root) / ".danza" / "runtime" / "team-state.json"
        updated = dict(TEAM_STATE, turn_number=4)
        state_path.write_text(json.dumps(updated))
        self.assertNotEqual(t1, snapshot_token(self.root))
```

Also add one HTTP assertion inside `TestOverview`:

```python
    def test_conductor_endpoint_serves_tail(self):
        _, _, body = get(self.port, "/api/conductor?limit=1")
        items = json.loads(body)["items"]
        self.assertEqual(items[0]["event"], "session_end")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: FAIL at import — `cannot import name 'conductor_tail'`.

- [ ] **Step 3: Implement**

In `danzaboss/workstation/server.py`, add after `overview()`:

```python
def conductor_tail(root: str, limit: int = 100) -> dict:
    """Last `limit` conductor JSONL events, newest first. Unparseable lines
    surface as {"event": "unparseable"} — never dropped silently (Rule 33:
    this log is the one surface the human gets)."""
    path = Path(root) / LOG_RELPATH
    if not path.exists():
        return {"items": []}
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()[-limit:]
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"event": "unparseable", "raw": line[:200]})
    items.reverse()
    return {"items": items}


def snapshot_token(root: str) -> str:
    """Cheap change token for SSE: mtime+size of the product state files
    (same role snapshot_version() plays for the CORTEX store)."""
    parts = []
    for rel in (TEAM_STATE_RELPATH, LOG_RELPATH, PLAN_JSON_RELPATH):
        try:
            st = (Path(root) / rel).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)
```

In `DanzaUIHandler.do_GET`, add two branches before the final `else`:

```python
            elif route == "/api/conductor":
                limit = int((q.get("limit") or ["100"])[0])
                self._json(conductor_tail(self.root, limit))
            elif route == "/api/events":
                self._danza_events()
```

Add the SSE method to `DanzaUIHandler` (same loop shape as the parent's `_api_events`):

```python
    def _danza_events(self) -> None:
        """SSE: refresh signal when any product state file changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = snapshot_token(self.root)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(2)
                now = snapshot_token(self.root)
                if now != last:
                    last = now
                    self.wfile.write(b'data: {"type": "refresh"}\n\n')
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): conductor log tail + SSE change token on the dashboard"
```

---

### Task 4: CORTEX mount under `/cortex/*`

Requires Task 1 (origin-relative CORTEX front-end). `/cortex` redirects to `/cortex/` so the browser resolves the page's relative URLs under the mount; every `/cortex/<rest>` request has the prefix stripped and is handled by the inherited `CortexUIHandler` code against the same `root`/`db_path`/`project`.

**Files:**
- Modify: `danzaboss/workstation/server.py` (`do_GET` + `do_POST`)
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: `CortexUIHandler.do_GET` / `.do_POST` (dispatch on `self.path`); `DanzaUIHandler._redirect` (Task 2).
- Produces: `/cortex` → 302 `/cortex/`; `/cortex/` → CORTEX index; `/cortex/api/*`, `/cortex/static/*` → the real CORTEX routes; POST `/cortex/api/settings` → CORTEX settings write.

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_danza_ui.py`:

```python
class TestCortexMount(unittest.TestCase):
    """D4: one process, one store — /cortex/* is the REAL CORTEX UI."""

    @classmethod
    def setUpClass(cls):
        cls._saved_profile = os.environ.pop("DANZA_PROFILE", None)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        seed_activated_repo(cls.root)
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()
        if cls._saved_profile is not None:
            os.environ["DANZA_PROFILE"] = cls._saved_profile

    def test_bare_cortex_redirects_to_slash(self):
        # urlopen follows the 302; the final URL proves the redirect happened
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/cortex", timeout=5) as r:
            self.assertTrue(r.geturl().endswith("/cortex/"))
            self.assertIn(b"CORTEX", r.read())

    def test_mounted_index_and_assets(self):
        status, ctype, body = get(self.port, "/cortex/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"CORTEX", body)
        for asset in ("/cortex/static/app.css", "/cortex/static/app.js"):
            status, _, _ = get(self.port, asset)
            self.assertEqual(status, 200, asset)

    def test_mounted_api_reads_the_same_store(self):
        _, _, body = get(self.port, "/cortex/api/observations")
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "Dashboard seed fact")

    def test_mounted_settings_write_still_works(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/cortex/api/settings",
            data=json.dumps({"max_full": 7}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(json.loads(r.read())["max_full"], 7)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 danzaboss/tests/test_danza_ui.py TestCortexMount -v`
Expected: 4 FAIL (404s — no `/cortex` routes yet).

- [ ] **Step 3: Implement**

In `DanzaUIHandler.do_GET`, add the mount branches FIRST (before the `route in ("/", "/index.html")` branch):

```python
            if route == "/cortex":
                query = f"?{parsed.query}" if parsed.query else ""
                self._redirect(f"/cortex/{query}")
            elif route.startswith("/cortex/"):
                # the mount (D4): strip the prefix, let the parent class serve
                self.path = self.path[len("/cortex"):]
                CortexUIHandler.do_GET(self)
            elif route in ("/", "/index.html"):
```

(The existing `if route in ("/", "/index.html"):` becomes an `elif`.)

Replace `do_POST` with:

```python
    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        if route.startswith("/cortex/"):
            self.path = self.path[len("/cortex"):]
            CortexUIHandler.do_POST(self)
            return
        self._json({"error": "read-only: product state is CLI-governed"}, 405)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: all PASS (including the earlier classes — the mount branches must not break `/` or `/api/*`).

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): mount the CORTEX UI under /cortex/* (D4: one process, one store)"
```

---

### Task 5: Read-only tab APIs — onboarding, plan, runners

ONBOARD/MODELS/BUILD render real state in Phase 2 and gain their interactive surfaces in Phases 3–4. These endpoints are the anchor points those phases extend.

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: `Wizard(root)` — `.flow() -> tuple[Step, ...]` (Step: `id`, `kind`, `title`, `questions`), `.status(step_id) -> str`, `.project_type() -> str | None`, `.answers -> dict`, `.is_complete() -> bool`, `.current_step() -> Step | None`; `PLAN_MD_RELPATH` from `.planner`; `_plan_summary`, `_runner_summary`, `_read_json` (Task 2).
- Produces:
  - `onboarding_summary(root: str) -> dict` — `{"project_type", "complete", "current_step", "answered", "steps": [{"id","kind","title","status","questions"}]}`.
  - `plan_detail(root: str) -> dict` — `{"plan": <_plan_summary result>, "tree": [task nodes], "plan_md": str}`; task node: `{"id","description","kind","size_est","writes","verified_by","subtasks"}`.
  - GET `/api/onboarding`, `/api/plan`, `/api/runners` (the last returns `{"runners": <_runner_summary result>}`).

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_danza_ui.py` (inside `TestOverview`, which already has a seeded server):

```python
    def test_onboarding_summary_reflects_wizard_state(self):
        _, _, body = get(self.port, "/api/onboarding")
        o = json.loads(body)
        self.assertFalse(o["complete"])          # nothing answered yet
        self.assertIsNone(o["project_type"])
        self.assertEqual(o["answered"], 0)
        self.assertTrue(o["steps"])              # the wizard FLOW renders
        first = o["steps"][0]
        for key in ("id", "kind", "title", "status", "questions"):
            self.assertIn(key, first)
        self.assertEqual(first["status"], "pending")

    def test_plan_detail_carries_tree_and_md(self):
        _, _, body = get(self.port, "/api/plan")
        p = json.loads(body)
        self.assertEqual(p["plan"]["leaves"], 2)
        self.assertIn("# Build order", p["plan_md"])
        top = p["tree"][0]
        self.assertEqual(top["id"], "1")
        self.assertEqual(top["subtasks"][0]["verified_by"], "pytest -k health")

    def test_runners_endpoint_reports_absence(self):
        _, _, body = get(self.port, "/api/runners")
        self.assertIsNone(json.loads(body)["runners"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 danzaboss/tests/test_danza_ui.py TestOverview -v`
Expected: the 3 new tests FAIL with HTTP 404.

- [ ] **Step 3: Implement**

In `danzaboss/workstation/server.py`, extend the planner import and add the wizard import:

```python
from .planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH, PlanningError,
                      parse_plan)
from .wizard import Wizard
```

Add after `conductor_tail`:

```python
def onboarding_summary(root: str) -> dict:
    """Wizard progress, read-only — Phase 3 turns this into /onboard forms."""
    wiz = Wizard(root)
    current = wiz.current_step()
    return {"project_type": wiz.project_type(),
            "complete": wiz.is_complete(),
            "current_step": current.id if current else None,
            "answered": len(wiz.answers),
            "steps": [{"id": s.id, "kind": s.kind, "title": s.title,
                       "status": wiz.status(s.id),
                       "questions": len(s.questions)}
                      for s in wiz.flow()]}


def plan_detail(root: str) -> dict:
    """BUILD tab payload: the validated task tree plus the human plan.md."""
    summary = _plan_summary(root)
    md_path = Path(root) / PLAN_MD_RELPATH
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    tree: list[dict] = []
    if summary is not None and "error" not in summary:
        data, _ = _read_json(Path(root) / PLAN_JSON_RELPATH)

        def node(t) -> dict:
            return {"id": t.id, "description": t.description, "kind": t.kind,
                    "size_est": t.size_est, "writes": list(t.writes),
                    "verified_by": (t.verification.detail
                                    if t.verification else None),
                    "subtasks": [node(s) for s in t.subtasks]}

        tree = [node(t) for t in parse_plan(data)]
    return {"plan": summary, "tree": tree, "plan_md": md}
```

In `DanzaUIHandler.do_GET`, add three branches before `elif route == "/api/events":`:

```python
            elif route == "/api/onboarding":
                self._json(onboarding_summary(self.root))
            elif route == "/api/plan":
                self._json(plan_detail(self.root))
            elif route == "/api/runners":
                self._json({"runners": _runner_summary(self.root)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): read-only onboarding/plan/runners APIs for the dashboard tabs"
```

---

### Task 6: Dashboard front-end (ADUSON identity)

Replaces the Task 2 stub with the real shell. The CSS is the CORTEX file copied verbatim (tokens, topbar, tabs, chips, console-log, sessions-table — spec §6 says "tokens copied from `cortex/ui/static/app.css`") plus an appended dashboard section. All URLs origin-relative, same discipline as Task 1.

**Files:**
- Create (replace stub): `danzaboss/workstation/static/index.html`
- Create: `danzaboss/workstation/static/app.css`, `danzaboss/workstation/static/app.js`, `danzaboss/workstation/static/background.png`
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: GET `api/overview`, `api/conductor?limit=40`, `api/onboarding`, `api/plan`, `api/runners`, `api/events` (SSE) — shapes from Tasks 2, 3, 5.
- Produces: the served dashboard; Task 8's acceptance run exercises it.

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_danza_ui.py`:

```python
class TestDashboardStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server, cls.port = serve_in_thread(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_index_and_assets_served(self):
        status, ctype, body = get(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"DANZA-OS", body)
        for asset in ("/static/app.css", "/static/app.js",
                      "/static/background.png"):
            status, _, _ = get(self.port, asset)
            self.assertEqual(status, 200, asset)

    def test_all_five_tabs_present(self):
        _, _, html = get(self.port, "/")
        for marker in (b'data-view="overview"', b'data-view="onboard"',
                       b'data-view="models"', b'data-view="build"',
                       b'href="cortex/"'):
            self.assertIn(marker, html)

    def test_front_end_is_origin_relative(self):
        _, _, html = get(self.port, "/")
        self.assertNotIn(b'"/static/', html)
        _, _, js = get(self.port, "/static/app.js")
        self.assertNotIn(b'"/api/', js)
        self.assertNotIn(b"`/api/", js)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 danzaboss/tests/test_danza_ui.py TestDashboardStatic -v`
Expected: FAIL — app.css/app.js/background.png 404, no tab markers in the stub.

- [ ] **Step 3: Copy the design system**

```bash
cp danzaboss/cortex/ui/static/app.css danzaboss/workstation/static/app.css
cp danzaboss/cortex/ui/static/background.png danzaboss/workstation/static/background.png
```

Append to `danzaboss/workstation/static/app.css`:

```css
/* ---------- DANZA-OS dashboard additions (Phase 2) ---------- */
/* Everything above is the CORTEX design system verbatim (spec section 6);
   only dashboard-specific layout lives below this line. */

a.tab { text-decoration: none; display: inline-flex; align-items: center; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 18px;
  margin-bottom: 26px;
}

.panel {
  background: linear-gradient(180deg, rgba(29, 29, 34, .92), rgba(20, 20, 23, .92));
  border: 1px solid var(--gunmetal);
  padding: 18px 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .45);
}

.panel-title {
  font-family: var(--font-display);
  font-size: 13px;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--silver);
  margin-bottom: 12px;
}

.kv { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.kv td { padding: 4px 0; vertical-align: top; }
.kv td:first-child { color: var(--dim); padding-right: 16px; white-space: nowrap; width: 1%; }

.warn { color: var(--ember); }

.log-line { padding: 3px 0; border-bottom: 1px solid rgba(58, 61, 68, .35); }

.plan-tree { list-style: none; padding-left: 0; }
.plan-tree ul { list-style: none; padding-left: 22px; border-left: 1px solid var(--gunmetal); }
.plan-tree li { padding: 4px 0; }

.plan-md {
  white-space: pre-wrap;
  background: rgba(10, 10, 12, .6);
  border: 1px solid var(--gunmetal);
  padding: 14px 16px;
  font-size: 12.5px;
}
```

(If Task 1 already appended an `a.chip` rule to the CORTEX app.css, the copy carries it — do not duplicate it here.)

- [ ] **Step 4: Write index.html**

Replace `danzaboss/workstation/static/index.html` entirely:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DANZA-OS — product dashboard</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E%3Cpolygon points='24,4 30,16 19,38 10,38' fill='%23c8102e'/%3E%3Cpolygon points='27,18 38,38 30,38 23,26' fill='%23c8102e'/%3E%3Cpolygon points='33,6 44,26 37,26 29,12' fill='%23e8354f'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="static/app.css">
</head>
<body>

<!-- TOP BAR — same chrome as CORTEX; product tabs instead of memory tabs. -->
<header class="topbar">
  <div class="brand">
    <div class="mark" id="mark" title="DANZA-OS">
      <svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true">
        <polygon points="24,4 30,16 19,38 10,38" fill="var(--crimson)"/>
        <polygon points="27,18 38,38 30,38 23,26" fill="var(--crimson)"/>
        <polygon points="33,6 44,26 37,26 29,12" fill="var(--ember)"/>
      </svg>
    </div>
    <h1 class="wordmark">DANZA-OS</h1>
    <div class="live" id="live-dot" title="live — updates as state changes">
      <span class="live-tri"></span><span class="live-label">live</span>
    </div>
  </div>

  <nav class="tabs" aria-label="Views">
    <button class="tab active" data-view="overview">Overview</button>
    <button class="tab" data-view="onboard">Onboard</button>
    <button class="tab" data-view="models">Models</button>
    <button class="tab" data-view="build">Build</button>
    <a class="tab" href="cortex/">CORTEX</a>
  </nav>

  <div class="topbar-right">
    <span class="chip mono" id="profile-chip" title="Active execution profile"></span>
  </div>
</header>

<main class="stage">

  <!-- OVERVIEW — the home screen (spec section 6). -->
  <section class="view" id="view-overview">
    <div class="grid" id="overview-grid"></div>
    <h2 class="section-label">Conductor log</h2>
    <div class="console-log mono" id="conductor-log"></div>
  </section>

  <!-- ONBOARD — read-only window; interactive forms land in Phase 3. -->
  <section class="view" id="view-onboard" hidden>
    <h2 class="section-label">Onboarding wizard</h2>
    <div class="panel" id="onboard-panel"></div>
  </section>

  <!-- MODELS — read-only window; lineup + routing land in Phase 4. -->
  <section class="view" id="view-models" hidden>
    <h2 class="section-label">Runner registry</h2>
    <div class="panel" id="models-panel"></div>
  </section>

  <!-- BUILD — read-only window; relay controls land in Phase 4. -->
  <section class="view" id="view-build" hidden>
    <h2 class="section-label">Plan</h2>
    <div class="panel" id="build-panel"></div>
  </section>
</main>

<script src="static/app.js"></script>
</body>
</html>
```

- [ ] **Step 5: Write app.js**

Create `danzaboss/workstation/static/app.js`:

```js
/* DANZA-OS dashboard — vanilla JS, no build step. Read-only over product
   state in Phase 2: OVERVIEW is live; ONBOARD / MODELS / BUILD render the
   real state files and gain their interactive surfaces in Phases 3-4. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path) {
  const res = await fetch(path);   // origin-relative: no leading slash
  if (!res.ok) throw new Error(`${res.status} on ${path}`);
  return res.json();
}

/* ---------- navigation ---------- */
const state = { view: "overview" };
$$(".tab[data-view]").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  state.view = b.dataset.view;
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  refresh();
}));

/* ---------- shared render helpers ---------- */
const row = (k, v) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`;

const panel = (title, bodyHTML) =>
  `<div class="panel"><h2 class="panel-title">${esc(title)}</h2>${bodyHTML}</div>`;

/* ---------- overview ---------- */
function projectPanel(o) {
  return panel("Project", `<table class="kv">
    ${row("name", `<b>${esc(o.project)}</b>`)}
    ${row("root", `<span class="mono dim">${esc(o.root)}</span>`)}
    ${row("profile", `<span class="chip mono">${esc(o.profile.name)}</span>`)}
    ${row("spec", o.spec_exists ? "spec.md present"
                                : '<span class="dim">no spec.md yet</span>')}
  </table>`);
}

function teamPanel(o) {
  const t = o.team_state;
  if (!t) {
    const err = o.team_state_error
      ? `<p class="warn mono">${esc(o.team_state_error)}</p>` : "";
    return panel("Team state", `<p class="dim">Not activated — no
      team-state.json. Run <code>danza init</code> in this repo.</p>${err}`);
  }
  return panel("Team state", `<table class="kv">
    ${row("boss", `<b>${esc(t.current_boss)}</b>`)}
    ${row("turn", esc(t.turn_number))}
    ${row("status", `<span class="chip mono">${esc(t.status)}</span>`)}
    ${row("features this turn",
          `${esc(t.features_completed_this_turn)} / ${esc(t.max_features_per_turn)}`)}
    ${row("handoff required", t.handoff_required ? "yes" : "no")}
  </table>`);
}

function planPanel(o) {
  const p = o.plan;
  if (!p) return panel("Plan", `<p class="dim">No plan.json yet — finish
    onboarding and planning to arm the build.</p>`);
  if (p.error) return panel("Plan", `<p class="warn mono">${esc(p.error)}</p>`);
  return panel("Plan", `<table class="kv">
    ${row("spec", `<span class="mono dim">${esc(p.spec_ref)}</span>`)}
    ${row("tasks", esc(p.tasks))}
    ${row("dispatchable leaves", esc(p.leaves))}
    ${row("build order",
          `<span class="mono dim">${esc((p.order || []).join(" → "))}</span>`)}
  </table>`);
}

function cortexPanel(o) {
  const c = o.cortex;
  return panel("CORTEX memory", `<table class="kv">
    ${row("observations", `<b>${esc(c.observations_stored)}</b>`)}
    ${row("read tokens", `~${esc(c.read_tokens)}t`)}
    ${row("sessions", esc(c.sessions))}
    ${row("pending events", esc(c.pending_events))}
  </table>
  <p><a class="chip" href="cortex/">open CORTEX →</a></p>`);
}

function logLine(e) {
  const rest = Object.fromEntries(Object.entries(e)
    .filter(([k]) => k !== "ts" && k !== "event"));
  return `<div class="log-line">
    <span class="dim">${esc(e.ts || "")}</span>
    <b>${esc(e.event || "")}</b>
    <span class="dim">${esc(JSON.stringify(rest))}</span>
  </div>`;
}

async function loadOverview() {
  const o = await api("api/overview");
  $("#profile-chip").textContent = o.profile.name;
  $("#overview-grid").innerHTML =
    projectPanel(o) + teamPanel(o) + planPanel(o) + cortexPanel(o);
  const log = await api("api/conductor?limit=40");
  $("#conductor-log").innerHTML = log.items.length
    ? log.items.map(logLine).join("")
    : `<p class="dim">No conductor activity yet — start the relay with
       <code>danza conduct</code>.</p>`;
}

/* ---------- onboard (read-only until Phase 3) ---------- */
async function loadOnboard() {
  const o = await api("api/onboarding");
  const steps = o.steps.map((s) => `<tr>
      <td class="mono dim">${esc(s.id)}</td>
      <td>${esc(s.title)}</td>
      <td class="mono dim">${esc(s.kind)}</td>
      <td><span class="chip mono">${esc(s.status)}</span></td>
    </tr>`).join("");
  $("#onboard-panel").innerHTML = `<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
    ${row("complete", o.complete ? "yes" : "no")}
  </table>
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>
  <p class="dim">Read-only view — dashboard onboarding forms land in Phase 3.</p>`;
}

/* ---------- models (read-only until Phase 4) ---------- */
async function loadModels() {
  const r = (await api("api/runners")).runners;
  if (!r) {
    $("#models-panel").innerHTML = `<p class="dim">No runner registry yet —
      run <code>danza runners .</code> to detect installed AI CLIs.</p>`;
    return;
  }
  if (r.error) {
    $("#models-panel").innerHTML = `<p class="warn mono">${esc(r.error)}</p>`;
    return;
  }
  $("#models-panel").innerHTML = `<table class="kv">
    ${row("boss", `<b>${esc(r.boss ?? "none detected")}</b>`)}
    ${row("session host", esc(r.session_host))}
    ${row("detected", r.detected.length
        ? r.detected.map((n) => `<span class="chip mono">${esc(n)}</span>`).join(" ")
        : '<span class="dim">none</span>')}
  </table>
  <p class="dim">Read-only view — lineup selection and the routing table land in Phase 4.</p>`;
}

/* ---------- build (read-only until Phase 4) ---------- */
function taskHTML(t) {
  const meta = [t.kind, t.size_est ? `${t.size_est}m` : "",
                (t.writes || []).join(", ")].filter(Boolean).map(esc).join(" · ");
  const verify = t.verified_by
    ? `<span class="dim mono">verify: ${esc(t.verified_by)}</span>` : "";
  const subs = (t.subtasks || []).map(taskHTML).join("");
  return `<li><span class="mono">${esc(t.id)}</span> ${esc(t.description)}
    <span class="dim">${meta}</span> ${verify}
    ${subs ? `<ul>${subs}</ul>` : ""}</li>`;
}

async function loadBuild() {
  const p = await api("api/plan");
  if (!p.plan) {
    $("#build-panel").innerHTML = `<p class="dim">No plan yet — the BUILD tab
      arms once onboarding compiles spec.md and planning writes plan.json.</p>`;
    return;
  }
  if (p.plan.error) {
    $("#build-panel").innerHTML = `<p class="warn mono">${esc(p.plan.error)}</p>`;
    return;
  }
  const tree = p.tree.length
    ? `<ul class="plan-tree">${p.tree.map(taskHTML).join("")}</ul>` : "";
  const md = p.plan_md ? `<h2 class="section-label">plan.md</h2>
    <pre class="plan-md mono">${esc(p.plan_md)}</pre>` : "";
  $("#build-panel").innerHTML = tree + md +
    `<p class="dim">Read-only view — relay start/stop controls land in Phase 4.</p>`;
}

/* ---------- refresh + SSE ---------- */
async function refresh() {
  try {
    if (state.view === "overview") await loadOverview();
    else if (state.view === "onboard") await loadOnboard();
    else if (state.view === "models") await loadModels();
    else if (state.view === "build") await loadBuild();
  } catch (e) {
    console.error(e);   // a failed poll must never kill the page
  }
}

function connectSSE() {
  const es = new EventSource("api/events");
  es.onopen = () => $("#live-dot").classList.add("connected");
  es.onerror = () => $("#live-dot").classList.remove("connected");
  es.onmessage = () => refresh();
}

refresh();
connectSSE();
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: all PASS.

- [ ] **Step 7: Eyeball it (manual, 2 minutes)**

Run: `cd /home/tre/dev/DANZA-OS && PYTHONPATH=. python3 -c "
from danzaboss.workstation.server import serve_in_thread
import time
srv, port = serve_in_thread('.')
print(f'http://127.0.0.1:{port}')
time.sleep(120)
"`

Open the printed URL: verify the ADUSON look (dark void background, crimson accents, Chakra Petch wordmark), all four tabs render without console errors, CORTEX tab navigates to the mounted CORTEX feed and its DANZA-OS chip navigates back. Ctrl-C when done. (This repo is OS_DEV so team-state shows "Not activated" — that is the honest empty state, not a bug.)

- [ ] **Step 8: Commit**

```bash
git add danzaboss/workstation/static/ danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): DANZA-OS dashboard front-end (ADUSON identity, 5 tabs)"
```

---

### Task 7: `danza ui` CLI command

**Files:**
- Modify: `danzaboss/cli.py` (docstring line ~17, new `_parse_ui_args` + `_cmd_ui`, `_COMMANDS` dict line ~361, usage string line ~372)
- Test: `danzaboss/tests/test_danza_ui.py`

**Interfaces:**
- Consumes: `workstation.server.serve(root, port=None, open_browser=True)` (Task 2).
- Produces: `_parse_ui_args(argv: list[str]) -> tuple[str, int | None, bool]` (root, port, open_browser; raises `ValueError` on bad input); `danza ui [dir] [--port N] [--no-open]`.

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_danza_ui.py`:

```python
class TestUiCliParsing(unittest.TestCase):
    """danza ui arg parsing is pure so it tests without binding a socket."""

    def test_defaults(self):
        from danzaboss.cli import _parse_ui_args
        self.assertEqual(_parse_ui_args([]), (".", None, True))

    def test_all_flags(self):
        from danzaboss.cli import _parse_ui_args
        self.assertEqual(_parse_ui_args(["/repo", "--port", "4000", "--no-open"]),
                         ("/repo", 4000, False))

    def test_bad_port_and_unknown_flag_raise(self):
        from danzaboss.cli import _parse_ui_args
        with self.assertRaises(ValueError):
            _parse_ui_args(["--port", "abc"])
        with self.assertRaises(ValueError):
            _parse_ui_args(["--bogus"])

    def test_ui_is_a_registered_command(self):
        from danzaboss.cli import _COMMANDS
        self.assertIn("ui", _COMMANDS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 danzaboss/tests/test_danza_ui.py TestUiCliParsing -v`
Expected: FAIL — `cannot import name '_parse_ui_args'`.

- [ ] **Step 3: Implement**

In `danzaboss/cli.py`, add after `_cmd_conduct` (line ~316):

```python
def _parse_ui_args(argv: list[str]) -> tuple[str, int | None, bool]:
    """danza ui [dir] [--port N] [--no-open] -> (root, port, open_browser).

    Pure so it is unit-testable; raises ValueError on bad input."""
    root = "."
    port: int | None = None
    open_browser = True
    i = 0
    while i < len(argv):
        if argv[i] == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                raise ValueError("--port must be an integer") from None
            i += 2
        elif argv[i] == "--no-open":
            open_browser = False
            i += 1
        elif not argv[i].startswith("-"):
            root = argv[i]
            i += 1
        else:
            raise ValueError(f"unknown argument: {argv[i]}")
    return root, port, open_browser


def _cmd_ui(argv: list[str]) -> int:
    """danza ui [dir] [--port N] [--no-open] - serve the product dashboard."""
    from .workstation.server import serve  # local import: UI is optional at runtime
    try:
        root, port, open_browser = _parse_ui_args(argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        print("usage: danzaboss.cli ui [dir] [--port N] [--no-open]",
              file=sys.stderr)
        return 2
    serve(root, port=port, open_browser=open_browser)
    return 0
```

Register it — in `_COMMANDS` (line ~361) add `"ui": _cmd_ui,` after `"conduct": _cmd_conduct,`. In the `main()` usage string (line ~372) change `|runners|conduct|init|doctor>` to `|runners|conduct|init|doctor|ui>`. In the module docstring command list (after the `danzaboss.cli doctor` line) add:

```
  danzaboss.cli ui [dir] [--port N] [--no-open]  DANZA-OS product dashboard on 127.0.0.1:33100
                                                (CORTEX UI mounted at /cortex/)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 danzaboss/tests/test_danza_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Smoke the real command**

Run: `cd /home/tre/dev/DANZA-OS && timeout 3 python3 -m danzaboss.cli ui --port 33199 --no-open; test $? -eq 124 && echo SMOKE-OK`
Expected: prints `DANZA-OS dashboard: http://127.0.0.1:33199  (CORTEX at http://127.0.0.1:33199/cortex/ — Ctrl-C to stop)` then `SMOKE-OK` (timeout kills the server; exit 124 proves it was serving, not crashed).

- [ ] **Step 6: Commit**

```bash
git add danzaboss/cli.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(cli): danza ui command (dashboard on 33100, --port/--no-open)"
```

---

### Task 8: Packaging + docs + phase-boundary green suite

**Files:**
- Modify: `pyproject.toml:31` (workstation package-data)
- Modify: `CLAUDE.md` (workstation layout line, module table, "How to run" section, test counts)

**Interfaces:**
- Consumes: everything above.
- Produces: an installable package that ships the dashboard assets; docs matching reality.

- [ ] **Step 1: Package the static assets**

In `pyproject.toml`, change:

```toml
"danzaboss.workstation" = ["templates/stacks/*.json"]
```

to:

```toml
"danzaboss.workstation" = ["templates/stacks/*.json", "static/*"]
```

- [ ] **Step 2: Verify the wheel carries the assets**

Run: `cd /home/tre/dev/DANZA-OS && python3 -m pip wheel --no-deps -w /tmp/claude-1000/-home-tre-dev-DANZA-OS/bad8b4bb-5c9d-420d-96a3-8002f5fb585b/scratchpad/wheel . >/dev/null && python3 -c "
import glob, zipfile
w = glob.glob('/tmp/claude-1000/-home-tre-dev-DANZA-OS/bad8b4bb-5c9d-420d-96a3-8002f5fb585b/scratchpad/wheel/*.whl')[0]
names = zipfile.ZipFile(w).namelist()
for a in ('index.html', 'app.css', 'app.js', 'background.png'):
    assert f'danzaboss/workstation/static/{a}' in names, a
print('wheel carries dashboard assets')
"`
Expected: `wheel carries dashboard assets`.

- [ ] **Step 3: Run the full suite**

Run: `./danzaboss/run_tests.sh`
Expected: ALL green. Note the printed total test count (was 792 before this phase).

- [ ] **Step 4: Sync CLAUDE.md**

In `CLAUDE.md`:

1. Project-layout block, `workstation/` line — change to:
   `workstation/               Onboarding + conductor relay + product dashboard: runner registry, session hosts, event loop, danza ui server ('danza runners' / 'danza conduct' / 'danza ui')`
2. "How to run the OS" section — add after the CORTEX bullet:
   `- **Product dashboard:** \`PYTHONPATH=. python3 -m danzaboss.cli ui [dir] [--port N] [--no-open]\` — DANZA-OS dashboard on 127.0.0.1:33100 with the CORTEX UI mounted at \`/cortex/\` (D4).`
3. Module table — extend the `workstation/` row's responsibility with: `; product dashboard server (danza ui, Phase 2)`
4. Replace every occurrence of the old test count (792) with the new total from Step 3 (three occurrences: intro paragraph, project layout, "Run the test suite" bullet).

- [ ] **Step 5: Final commit**

```bash
git add pyproject.toml CLAUDE.md
git commit -m "chore(product): package dashboard assets; sync CLAUDE.md to Phase 2"
```

---

## Acceptance check (spec §6)

- `danza ui` in an activated repo serves all tabs — Tasks 6–7 (+ Task 5 APIs). ✅
- `/cortex` renders the real CORTEX feed — Task 4 (`test_mounted_api_reads_the_same_store` uses the real store). ✅
- HTTP-level tests in the `test_cortex_ui.py` style — `test_danza_ui.py` mirrors its `serve_in_thread` + `urllib` pattern. ✅
- ThreadingHTTPServer, static beside module, JSON API, SSE heartbeat, `127.0.0.1`, port 33100, browser auto-open — Tasks 2–3, 7. ✅
- ADUSON identity verbatim + reciprocal buttons — Tasks 1, 6. ✅
- Home screen: identity, profile, team-state, plan progress, conductor tail, CORTEX stats strip — Task 2/3/6. Token telemetry beyond the CORTEX read-token strip is Phase 4 (§8 D10) and lands with the conductor telemetry aggregation there. ✅
