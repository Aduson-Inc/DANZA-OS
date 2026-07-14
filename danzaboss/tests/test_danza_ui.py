"""Phase 2 acceptance: the DANZA dashboard serves every tab's API, mounts the
real CORTEX UI under /cortex/*, and stays read-only outside the mount."""
import json
import os
import signal
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.budgets import BUDGETS_RELPATH
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.workstation import server as server_mod
from danzaboss.workstation.conductor import (PIDFILE_RELPATH as
                                             CONDUCTOR_PIDFILE, session_name)
from danzaboss.workstation.routing import ROUTING_RELPATH, SEAT_WORK_TYPES
from danzaboss.workstation.runners import (KNOWN_RUNNERS, RUNNERS_RELPATH,
                                           SCHEMA_VERSION, default_config)
from danzaboss.workstation.server import (conductor_tail, overview,
                                          serve_in_thread, snapshot_token)


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read())
        e.close()
        return e.code, payload


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
                    "session": "danza-boss", "runner": "claude",
                    "turn_number": 3}) + "\n" +
        json.dumps({"ts": "2026-07-11T00:05:00+00:00", "event": "session_end",
                    "turn_number": 3}) + "\n")
    store = ObservationStore(SqliteBackend(commands.db_path(root)))
    store.upsert(Observation(
        title="Dashboard seed fact", summary="phase 2 fixture",
        type=ObsType.DECISION.value, project=os.path.basename(root),
        importance=Importance.CRITICAL.value, confidence=90,
        reasoning="seeded for HTTP tests", concepts=["dashboard"]))
    CaptureLog(commands.db_path(root)).record_context_read(
        os.path.basename(root), "jonathan-builder", 400, 900)


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

    def test_overview_carries_token_telemetry(self):
        # P4 T11: per-agent context spend + per-turn ignite counts ride the
        # cortex block so the Tokens card renders from one payload.
        status, _, body = get(self.port, "/api/overview")
        self.assertEqual(status, 200)
        c = json.loads(body)["cortex"]
        self.assertEqual(c["per_agent"]["jonathan-builder"],
                         {"reads": 1, "tokens": 400})
        self.assertEqual(c["per_turn"], {"3": 1})

    def test_overview_unactivated_repo_is_honest(self):
        with tempfile.TemporaryDirectory() as bare:
            o = overview(bare)
        self.assertEqual(o["cortex"]["per_agent"], {})
        self.assertEqual(o["cortex"]["per_turn"], {})
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
        # read-only product-state guarantee is now carried by the POST
        # route allowlist: an unrecognized POST route is a plain 404.
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/overview", data=b"{}",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            e.close()

    def test_conductor_endpoint_serves_tail(self):
        _, _, body = get(self.port, "/api/conductor?limit=1")
        items = json.loads(body)["items"]
        self.assertEqual(items[0]["event"], "session_end")

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
        self.assertIsInstance(first["questions"], list)

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


class TestOnboardingDetail(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_questions_carry_render_contract(self):
        from danzaboss.workstation.server import onboarding_summary
        o = onboarding_summary(self.root)
        p0 = next(s for s in o["steps"] if s["id"] == "p0")
        q = p0["questions"][0]
        for key in ("id", "prompt", "kind", "options", "required",
                    "default", "value", "show_if"):
            self.assertIn(key, q)
        self.assertEqual(q["id"], "project_type")
        self.assertIn("saas", q["options"])

    def test_answers_show_as_values_and_interview_rides_along(self):
        from danzaboss.workstation import interview
        from danzaboss.workstation.server import onboarding_summary
        from danzaboss.workstation.wizard import Wizard
        Wizard(self.root).submit("p0", {"project_type": "saas"})
        interview.begin_phase(self.root, "p0")
        interview.run_interview_round(self.root, "p0", None)  # degraded
        o = onboarding_summary(self.root)
        p0 = next(s for s in o["steps"] if s["id"] == "p0")
        self.assertEqual(p0["questions"][0]["value"], "saas")
        self.assertTrue(p0["interview"]["degraded"])
        self.assertTrue(o["app_project"])
        self.assertFalse(o["boss_available"])
        self.assertIsNone(o["blocking_phase"])  # degraded passes the gate

    def test_snapshot_token_moves_on_interview_write(self):
        from danzaboss.workstation import interview
        from danzaboss.workstation.server import snapshot_token
        before = snapshot_token(self.root)
        interview.save_interview(self.root, {"phases": {}})
        self.assertNotEqual(before, snapshot_token(self.root))

    def test_team_state_rule45_violation_surfaces(self):
        from danzaboss.workstation.server import _team_state
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        bad = dict(TEAM_STATE, status="partying")
        (runtime / "team-state.json").write_text(json.dumps(bad))
        data, err = _team_state(self.root)
        self.assertEqual(data["status"], "partying")  # still rendered
        self.assertIn("Rule 45", err)

    def test_valid_team_state_has_no_error(self):
        from danzaboss.workstation.server import _team_state
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "team-state.json").write_text(json.dumps(TEAM_STATE))
        _, err = _team_state(self.root)
        self.assertEqual(err, "")

    def test_team_state_typeerror_surfaces_as_rule45(self):
        # an unhashable mode raises TypeError (not StateError) inside
        # validate() — the except must catch both (Rule 45 read-side honesty)
        from danzaboss.workstation.server import _team_state
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        bad = dict(TEAM_STATE, mode=["relay"])
        (runtime / "team-state.json").write_text(json.dumps(bad))
        data, err = _team_state(self.root)
        self.assertEqual(data["mode"], ["relay"])  # still rendered
        self.assertIn("Rule 45", err)


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

    def test_snapshot_token_moves_on_runners_write(self):
        t1 = snapshot_token(self.root)
        runners_path = Path(self.root) / ".danza" / "runtime" / "runners.json"
        runners_path.write_text("{}")
        self.assertNotEqual(t1, snapshot_token(self.root))


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


class TestPostGuards(unittest.TestCase):
    """CSRF Origin/Host guard + body-size cap on every POST surface."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def _post(self, path, body=b"{}", headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=body,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            payload = json.loads(e.read())
            e.close()
            return e.code, payload

    def test_foreign_origin_is_rejected(self):
        status, out = self._post("/api/onboard/submit",
                                 headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("cross-origin", out["error"])

    def test_foreign_origin_rejected_on_cortex_passthrough(self):
        status, out = self._post("/cortex/api/settings",
                                 body=json.dumps({"max_full": 9}).encode(),
                                 headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("cross-origin", out["error"])

    def test_foreign_host_is_rejected(self):
        status, out = self._post("/api/onboard/submit",
                                 headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("cross-origin", out["error"])

    def test_local_origin_passes_the_guard(self):
        # reaches the route handler: this root has no confirmed setup, so
        # the Phase 4 gate answers 409 — proof the 403 guard let the
        # same-origin request through (a rejected origin never routes)
        for origin in (f"http://127.0.0.1:{self.port}",
                       f"http://localhost:{self.port}"):
            status, out = self._post("/api/onboard/submit",
                                     headers={"Origin": origin})
            self.assertEqual(status, 409, origin)
            self.assertIn("Setup", out["error"])

    def test_absent_origin_local_host_passes(self):
        # curl/urllib shape: no Origin, loopback Host (urllib adds it)
        status, out = self._post("/api/onboard/submit")
        self.assertEqual(status, 409)
        self.assertIn("Setup", out["error"])

    def test_oversized_content_length_is_400(self):
        status, out = self._post(
            "/api/onboard/submit",
            headers={"Content-Length": str(2_000_000)})
        self.assertEqual(status, 400)
        self.assertIn("exceeds", out["error"])


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
        for marker in (b'data-view="overview"', b'data-view="setup"',
                       b'data-view="onboard"', b'data-view="build"',
                       b'href="cortex/"'):
            self.assertIn(marker, html)
        # MODELS is gone — the tab and its view became SETUP in Phase 4
        self.assertNotIn(b'data-view="models"', html)

    def test_tab_order_setup_before_onboard(self):
        # Phase 4 order: OVERVIEW · SETUP · ONBOARD · BUILD · CORTEX
        _, _, html = get(self.port, "/")
        self.assertLess(html.index(b'data-view="setup"'),
                        html.index(b'data-view="onboard"'))
        self.assertLess(html.index(b'data-view="overview"'),
                        html.index(b'data-view="setup"'))

    def test_front_end_is_origin_relative(self):
        _, _, html = get(self.port, "/")
        self.assertNotIn(b'"/static/', html)
        _, _, js = get(self.port, "/static/app.js")
        self.assertNotIn(b'"/api/', js)
        self.assertNotIn(b"`/api/", js)
        _, _, css = get(self.port, "/static/app.css")
        self.assertNotIn(b'url("/static/', css)

    def test_onboard_form_wiring_present(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/onboard/submit", "api/onboard/followup",
                       "api/onboard/resolve", "api/onboard/research",
                       "api/onboard/checkpoint", "api/onboard/approve",
                       "api/onboard/finish", "showIfMet", "collectAnswers"):
            self.assertIn(marker, js)
        self.assertNotIn("Read-only view — dashboard onboarding forms", js)

    def test_onboard_css_form_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        self.assertIn(".field", body.decode())

    def test_setup_ui_wiring_present(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/setup", "loadSetup", "Confirm team",
                       "Built-in (recommended)", "Connected",
                       "Found, not logged in", "Full Power",
                       "Set up your AI team first"):
            self.assertIn(marker, js)
        # the read-only Phase-2 MODELS view is fully replaced
        self.assertNotIn("loadModels", js)
        self.assertNotIn("lineup selection and the routing table land", js)
        # catalog strengths is a plain sentence (runners.py), not a list —
        # joining it crashes renderSetup (found in the T13 live eyeball)
        self.assertNotIn("a.strengths || []", js)
        self.assertIn("a.strengths || \"\"", js)

    def test_setup_css_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        css = body.decode()
        for token in (".agent-card", ".seat-row", ".dial-card"):
            self.assertIn(token, css)

    def test_build_ui_wiring_present(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/build/start", "api/build/stop", "loadBuild",
                       "Stop the build crew? The current turn finishes safely.",
                       "Finish Setup and Onboarding to start building",
                       "Handed the baton to"):
            self.assertIn(marker, js)
        # the Phase-2 read-only placeholder is fully replaced
        self.assertNotIn("relay start/stop controls land in Phase 4", js)
        _, _, html = get(self.port, "/")
        self.assertIn(b'id="build-controls"', html)

    def test_build_css_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        css = body.decode()
        for token in (".team-strip", ".session-tail"):
            self.assertIn(token, css)


def fake_registry(auth=None, detected=("claude", "gemini")):
    """A build_registry double: no shutil.which, no subprocess, controlled
    detected/auth stamps."""
    config = default_config({name: name in detected for name in KNOWN_RUNNERS})
    for entry in config["runners"].values():
        if entry["detected"]:
            entry["auth"] = "ok"
    for name, value in (auth or {}).items():
        config["runners"][name]["auth"] = value
    return config


def team_seats(runner="claude", **assign):
    """All nine seats: built-in conductor, *runner* everywhere unless
    overridden per work type."""
    seats = {"conductor": "builtin"}
    for work_type in SEAT_WORK_TYPES:
        seats[work_type] = assign.get(work_type, runner)
    return seats


def seed_confirmed_setup(root):
    """runners.json + routing.json for a repo whose team is already
    confirmed — a stub runner with NO headless argv, so nothing the
    onboarding routes do afterwards can spawn a real subprocess."""
    runtime = Path(root) / ".danza" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    config = {"version": SCHEMA_VERSION, "boss": "stub",
              "session_host": "headless", "permission_mode": None,
              "runners": {"stub": {
                  "kind": "cli", "binary": "stub",
                  "display_name": "Stub", "strengths": "",
                  "suggested_seats": [], "activation": "argv",
                  "full_power_extra_argv": [], "interactive": ["stub"],
                  "headless": [], "detected": True, "auth": "unprobed"}}}
    (Path(root) / RUNNERS_RELPATH).write_text(json.dumps(config))
    routing = {"version": 1, "lineup": ["stub"], "seats": team_seats("stub")}
    (Path(root) / ROUTING_RELPATH).write_text(json.dumps(routing))


class TestSetupApi(unittest.TestCase):
    """Phase 4 T5: /api/setup + the hard setup-first gate (Decisions 1, 7)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        # module-level seams (the detect_runners(which=...) idiom): tests
        # must never probe the host's real CLIs
        self._saved = (server_mod._BUILD_REGISTRY, server_mod._REGISTRY_CLOCK)
        server_mod._BUILD_REGISTRY = fake_registry
        server_mod._reset_registry_cache()
        self.addCleanup(self._restore_seams)
        self.server, self.port = serve_in_thread(self.root)
        self.addCleanup(self.server.shutdown)

    def _restore_seams(self):
        server_mod._BUILD_REGISTRY, server_mod._REGISTRY_CLOCK = self._saved
        server_mod._reset_registry_cache()

    def test_get_setup_reports_agents_and_suggested_seats(self):
        status, _, raw = get(self.port, "/api/setup")
        self.assertEqual(status, 200)
        o = json.loads(raw)
        names = [a["name"] for a in o["agents"]]
        # five real catalog entries; the generic copy-me template is no card
        self.assertEqual(names, ["claude", "codex", "gemini", "grok",
                                 "opencode"])
        claude = o["agents"][0]
        self.assertEqual(claude["display_name"], "Claude Code")
        self.assertTrue(claude["detected"])
        self.assertEqual(claude["auth"], "ok")
        codex = o["agents"][1]
        self.assertFalse(codex["detected"])
        self.assertEqual(codex["auth"], "unprobed")
        # routing.json absent -> strengths-based suggestion fills the seats
        self.assertEqual(o["lineup"], ["claude", "gemini"])
        self.assertEqual(o["seats"]["conductor"], "builtin")
        self.assertEqual(o["seats"]["build"], "claude")
        self.assertEqual(o["seats"]["research"], "gemini")
        self.assertEqual(o["seats"]["map"], "gemini")
        self.assertEqual(o["dial"], "normal")
        self.assertEqual(o["conductor"], "builtin")
        self.assertEqual(o["overrides"], {})
        self.assertEqual(o["floors"]["jonathan-builder"], 600)
        self.assertEqual(o["floors"]["bonnie-qa"], 400)
        self.assertFalse(o["setup_complete"])

    def test_post_setup_writes_all_three_files(self):
        body = {"lineup": ["claude", "gemini"],
                "seats": team_seats("claude", research="gemini",
                                    map="gemini"),
                "dial": "full_power", "overrides": {"bonnie-qa": 1000}}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200, out)
        self.assertTrue(out["ok"])
        self.assertTrue(out["setup"]["setup_complete"])
        for rel in (RUNNERS_RELPATH, ROUTING_RELPATH, BUDGETS_RELPATH):
            self.assertTrue((Path(self.root) / rel).exists(), rel)
        saved = json.loads((Path(self.root) / RUNNERS_RELPATH).read_text())
        self.assertEqual(saved["boss"], "claude")  # boss = lineup[0]

    def test_persisted_seats_win_over_suggestion(self):
        body = {"lineup": ["claude", "gemini"],
                "seats": team_seats("gemini", plan="claude"),
                "dial": "normal"}
        status, _ = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200)
        _, _, raw = get(self.port, "/api/setup")
        o = json.loads(raw)
        self.assertEqual(o["seats"], body["seats"])
        self.assertEqual(o["lineup"], ["claude", "gemini"])
        self.assertTrue(o["setup_complete"])

    def test_post_rejects_six_runner_lineup(self):
        body = {"lineup": ["claude", "codex", "gemini", "grok", "opencode",
                           "generic"],
                "seats": team_seats("claude"), "dial": "normal"}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("1-5", out["error"])

    def test_post_rejects_unauthenticated_seat(self):
        server_mod._BUILD_REGISTRY = \
            lambda: fake_registry(auth={"claude": "unauthenticated"})
        server_mod._reset_registry_cache()
        body = {"lineup": ["claude"], "seats": team_seats("claude"),
                "dial": "normal"}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("not logged in", out["error"])

    def test_post_rejects_sub_floor_override_and_writes_nothing(self):
        body = {"lineup": ["claude"], "seats": team_seats("claude"),
                "dial": "normal", "overrides": {"bonnie-qa": 100}}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("floor", out["error"])
        # every payload validates BEFORE anything is written: a rejected
        # confirm must leave no torn multi-file state
        for rel in (RUNNERS_RELPATH, ROUTING_RELPATH, BUDGETS_RELPATH):
            self.assertFalse((Path(self.root) / rel).exists(), rel)

    def test_registry_cache_ttl_and_post_reprobes(self):
        calls = []
        clock = {"now": 1000.0}

        def counting_build():
            calls.append(1)
            return fake_registry()

        server_mod._BUILD_REGISTRY = counting_build
        server_mod._REGISTRY_CLOCK = lambda: clock["now"]
        server_mod._reset_registry_cache()
        server_mod.setup_summary(self.root)
        server_mod.setup_summary(self.root)
        self.assertEqual(len(calls), 1)   # second read inside the TTL: cached
        clock["now"] += 61.0
        server_mod.setup_summary(self.root)
        self.assertEqual(len(calls), 2)   # TTL expired: rebuilt
        server_mod.post_setup(self.root, {
            "lineup": ["claude"], "seats": team_seats("claude"),
            "dial": "normal"})
        self.assertEqual(len(calls), 3)   # POST always re-probes fresh

    def test_onboarding_posts_409_until_setup_confirmed(self):
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0",
                            "answers": {"project_type": "saas"}})
        self.assertEqual(status, 409)
        self.assertIn("Setup", out["error"])
        seed_confirmed_setup(self.root)
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0",
                            "answers": {"project_type": "saas"}})
        self.assertEqual(status, 200, out)  # degraded grill: no headless argv

    def test_onboarding_summary_carries_setup_complete(self):
        _, _, raw = get(self.port, "/api/onboarding")
        self.assertFalse(json.loads(raw)["setup_complete"])
        seed_confirmed_setup(self.root)
        _, _, raw = get(self.port, "/api/onboarding")
        self.assertTrue(json.loads(raw)["setup_complete"])

    def test_overview_runners_block_carries_team(self):
        seed_confirmed_setup(self.root)
        runners = overview(self.root)["runners"]
        self.assertEqual(runners["lineup"], ["stub"])
        self.assertEqual(runners["seats"]["build"], "stub")
        self.assertEqual(runners["dial"], "normal")

    def test_snapshot_token_moves_on_routing_and_budgets_writes(self):
        t0 = snapshot_token(self.root)
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (Path(self.root) / ROUTING_RELPATH).write_text("{}")
        t1 = snapshot_token(self.root)
        self.assertNotEqual(t0, t1)
        (Path(self.root) / BUDGETS_RELPATH).write_text("{}")
        self.assertNotEqual(t1, snapshot_token(self.root))


class TestBuildApi(unittest.TestCase):
    """Phase 4 T9: /api/build — managed relay start/stop + live state.

    The seam tests call the handlers directly (popen/kill/alive keyword
    seams) so no test ever spawns or signals a real process; the HTTP
    tests double the module-level _SESSION_HOST factory the same way
    TestSetupApi doubles _BUILD_REGISTRY."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _pidfile(self, pid):
        path = Path(self.root) / CONDUCTOR_PIDFILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n")

    def _pass_start_gate(self):
        """Confirmed setup + a plan — the two server-side start conditions."""
        seed_confirmed_setup(self.root)
        (Path(self.root) / ".danza" / "plan.json").write_text(json.dumps(PLAN))

    def _get(self, port, path):
        try:
            return get(port, path)[0]
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def test_start_spawns_the_managed_conduct_subprocess(self):
        self._pass_start_gate()
        calls = {}

        class Proc:
            pid = 4242

        def fake_popen(argv, **kwargs):
            calls["argv"] = argv
            calls["kwargs"] = kwargs
            return Proc()

        out = server_mod.post_build_start(self.root, {}, popen=fake_popen)
        self.assertTrue(out["ok"])
        self.assertEqual(out["pid"], 4242)
        self.assertEqual(calls["argv"], [sys.executable, "-m",
                                         "danzaboss.cli", "conduct",
                                         self.root])
        self.assertTrue(calls["kwargs"]["start_new_session"])
        # the detached conductor's output lands in a tailable log file
        log = Path(self.root) / ".danza" / "runtime" / "conduct-ui.log"
        self.assertTrue(log.exists())

    def test_start_gates_on_setup_and_plan(self):
        def exploding_popen(*a, **k):
            raise AssertionError("a gated start must not spawn")

        # no setup at all -> the setup-first gate refuses
        with self.assertRaises(server_mod.GateConflict):
            server_mod.post_build_start(self.root, {}, popen=exploding_popen)
        # setup confirmed but no plan yet -> still refused
        seed_confirmed_setup(self.root)
        with self.assertRaises(server_mod.GateConflict):
            server_mod.post_build_start(self.root, {}, popen=exploding_popen)

    def test_double_start_is_a_conflict(self):
        self._pass_start_gate()
        self._pidfile(1234)

        def exploding_popen(*a, **k):
            raise AssertionError("must not spawn a second conductor")

        with self.assertRaises(server_mod.GateConflict):
            server_mod.post_build_start(self.root, {},
                                        popen=exploding_popen,
                                        alive=lambda pid: True)

    def test_stale_pidfile_does_not_block_start(self):
        self._pass_start_gate()
        self._pidfile(1234)

        class Proc:
            pid = 4242

        out = server_mod.post_build_start(self.root, {},
                                          popen=lambda *a, **k: Proc(),
                                          alive=lambda pid: False)
        self.assertTrue(out["ok"])

    def test_stop_sigterms_the_recorded_pid(self):
        self._pidfile(4242)
        killed = []
        out = server_mod.post_build_stop(
            self.root, {}, kill=lambda pid, sig: killed.append((pid, sig)),
            alive=lambda pid: True)
        self.assertTrue(out["ok"])
        self.assertEqual(killed, [(4242, signal.SIGTERM)])

    def test_stop_when_not_running_is_a_conflict(self):
        with self.assertRaises(server_mod.GateConflict):  # no pidfile at all
            server_mod.post_build_stop(self.root, {})
        self._pidfile(4242)  # pidfile holding a dead pid
        with self.assertRaises(server_mod.GateConflict):
            server_mod.post_build_stop(self.root, {},
                                       alive=lambda pid: False)

    def test_build_endpoint_reports_running_state_and_tails(self):
        seed_activated_repo(self.root)
        self._pidfile(os.getpid())  # a live pid: the relay reads as running

        class FakeHost:
            def alive(self, name):
                return True

            def tail(self, name, lines=40):
                return "boss output"

        saved = server_mod._SESSION_HOST
        server_mod._SESSION_HOST = lambda root: FakeHost()
        self.addCleanup(lambda: setattr(server_mod, "_SESSION_HOST", saved))
        server, port = serve_in_thread(self.root)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        status, _, raw = get(port, "/api/build")
        self.assertEqual(status, 200)
        o = json.loads(raw)
        self.assertTrue(o["running"])
        self.assertEqual(o["team_state"]["current_boss"], "claude")
        self.assertEqual(o["session"]["name"], session_name(self.root))
        self.assertTrue(o["session"]["alive"])
        self.assertEqual(o["session"]["tail"], "boss output")
        self.assertEqual(o["conductor"][0]["event"], "session_end")

    def test_build_summary_degrades_without_a_host(self):
        # no runners.json -> no resolvable host; every piece renders as
        # honest absence, never a crash
        o = server_mod.build_summary(self.root)
        self.assertFalse(o["running"])
        self.assertEqual(o["session"], {"name": session_name(self.root),
                                        "alive": False, "tail": ""})
        self.assertIsNone(o["team_state"])
        self.assertEqual(o["conductor"], [])

    def test_conductor_limit_rejects_out_of_range(self):
        server, port = serve_in_thread(self.root)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for bad in ("0", "5000", "abc", "-3"):
            self.assertEqual(self._get(port, f"/api/conductor?limit={bad}"),
                             400, bad)
        self.assertEqual(self._get(port, "/api/conductor?limit=5"), 200)


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

    def test_ui_bind_failure_exits_2(self):
        import socket

        from danzaboss.cli import _cmd_ui
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        taken_port = sock.getsockname()[1]
        try:
            self.assertEqual(
                _cmd_ui([".", "--port", str(taken_port), "--no-open"]), 2)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
