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
from danzaboss.workstation.server import (conductor_tail, overview,
                                          serve_in_thread, snapshot_token)


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
        # reaches the route handler: {} is missing step_id, an honest 400 —
        # proof the 403 guard let the same-origin request through
        for origin in (f"http://127.0.0.1:{self.port}",
                       f"http://localhost:{self.port}"):
            status, out = self._post("/api/onboard/submit",
                                     headers={"Origin": origin})
            self.assertEqual(status, 400, origin)
            self.assertIn("step_id", out["error"])

    def test_absent_origin_local_host_passes(self):
        # curl/urllib shape: no Origin, loopback Host (urllib adds it)
        status, out = self._post("/api/onboard/submit")
        self.assertEqual(status, 400)
        self.assertIn("step_id", out["error"])

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
