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
from unittest.mock import patch

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.workstation import server as server_mod
from danzaboss.workstation import execution as execution_mod
from danzaboss.workstation import product_scope as product_scope_mod
from danzaboss.workstation import project as project_mod
from danzaboss.workstation import routing as routing_mod
from danzaboss.workstation.conductor import (PIDFILE_RELPATH as
                                             CONDUCTOR_PIDFILE, session_name)
from danzaboss.workstation.routing import (ROUTING_RELPATH,
                                           SCHEMA_VERSION as ROUTING_SCHEMA_VERSION,
                                           SEAT_WORK_TYPES)
from danzaboss.workstation.runners import (KNOWN_RUNNERS, RUNNERS_RELPATH,
                                           SCHEMA_VERSION, default_config,
                                           save_runners as save_runners_config)
from danzaboss.workstation.server import (conductor_tail, overview,
                                          serve_in_thread, snapshot_token)
from danzaboss.workstation.workspace import save_workspace


STALE_BUDGETS_RELPATH = Path(".danza") / "runtime" / "budgets.json"


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
    "spec_ref": ".danza/features.json#revision-1",
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
        self.assertEqual(o["roster"][0]["name"], "Tony-D")
        self.assertEqual(o["roster"][0]["role"], "The Boss")
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

    def test_superseded_get_endpoints_are_removed(self):
        # P T8b: /api/runners and /api/connection existed only for the old
        # 4-tab UI (which never actually fetched them — both were already
        # dead weight); the one-flow SPA has no consumer for either, and
        # their data rides along inside /api/overview, /api/setup,
        # /api/onboarding, and /api/flow instead.
        for path in ("/api/runners", "/api/connection"):
            try:
                status, _, _ = get(self.port, path)
            except urllib.error.HTTPError as e:
                status = e.code
                e.close()
            self.assertEqual(status, 404, path)


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
                      "/cortex/static/background.png"):
            status, _, _ = get(self.port, asset)
            self.assertEqual(status, 200, asset)
        _, _, css = get(self.port, "/static/app.css")
        self.assertIn(b'url("../cortex/static/background.png")', css)
        local_background = (Path(__file__).resolve().parents[1] /
                            "workstation" / "static" / "background.png")
        self.assertFalse(local_background.exists())

    def test_one_flow_shell_present_no_tabs(self):
        # P T8b: the 4-tab SPA became one linear journey — no tab nav, no
        # data-view attributes, one flow rail + one team strip + one stage
        # list + one Advanced drawer.
        _, _, html = get(self.port, "/")
        for marker in (b'id="flow-rail"', b'id="team-strip"',
                       b'id="stages"', b'id="advanced-drawer"',
                       b'id="advanced-toggle"', b'href="cortex/"'):
            self.assertIn(marker, html)
        for removed in (b'data-view=', b'class="tabs"', b'id="view-overview"',
                        b'id="view-setup"', b'id="view-project"',
                        b'id="view-build"'):
            self.assertNotIn(removed, html)

    def test_front_end_is_origin_relative(self):
        _, _, html = get(self.port, "/")
        self.assertNotIn(b'"/static/', html)
        _, _, js = get(self.port, "/static/app.js")
        self.assertNotIn(b'"/api/', js)
        self.assertNotIn(b"`/api/", js)
        _, _, css = get(self.port, "/static/app.css")
        self.assertNotIn(b'url("/static/', css)

    def test_front_end_carries_no_internal_execution_profile_reference(self):
        # the OVERVIEW tab (and its execution-profile display) is gone
        # entirely in the one-flow SPA — nothing reads .profile at all.
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        self.assertNotIn(".profile", js)

    def test_stage_machine_driven_by_flow_endpoint(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ('api("api/flow")', "flowData", "STAGES",
                       '{ id: "connect"', '{ id: "describe"', '{ id: "approve"',
                       '{ id: "build"', '{ id: "done"', "renderFlow",
                       "loadStageDetail", "toggleStage"):
            self.assertIn(marker, js)

    def test_team_strip_is_the_one_merged_list(self):
        # requirement 4: one merged team list from /api/flow — no duplicate
        # active/waiting widgets, no local runner-name catalog.
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        self.assertIn("teamStripHTML", js)
        self.assertIn("flowData.team", js)
        self.assertIn("teamDisplayName", js)
        for removed in ("RUNNER_NAMES", "function runnerName"):
            self.assertNotIn(removed, js)
        _, _, css = get(self.port, "/static/app.css")
        for token in (".team-list", ".team-member", ".team-dot"):
            self.assertIn(token, css.decode())

    def test_feature_editor_is_shared_by_approve_and_build(self):
        # requirement: ONE feature-list editor component backs both the
        # Approve stage's product scope and the Build stage's additions.
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("function featureCardHTML", "function newFeatureEditor",
                       "function seedFeatureEditor", "function collectFeatureEditor",
                       "function featureEditorHTML", "scopeEditor",
                       "additionsEditor"):
            self.assertIn(marker, js)

    def test_advanced_drawer_holds_cortex_and_raw_log(self):
        # rarely-used surfaces (CORTEX stats, raw activity log, internal
        # plan artifacts) live behind the one Advanced drawer, not extra tabs.
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("openAdvanced", "closeAdvanced", "loadAdvanced",
                       "cortexPanel", "api/conductor?limit=100",
                       "planInternalsPanel", 'api("api/plan")'):
            self.assertIn(marker, js)
        # the internal plan tree/plan.md is not duplicated inside Build too
        self.assertNotIn("build-internals", js)

    def test_onboard_form_wiring_present(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/onboard/submit", "api/onboard/followup",
                       "api/onboard/resolve", "api/onboard/research",
                       "api/onboard/checkpoint", "api/onboard/approve",
                       "api/onboard/finish", "showIfMet", "collectAnswers"):
            self.assertIn(marker, js)

    def test_onboard_css_form_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        self.assertIn(".field", body.decode())

    def test_describe_stage_wires_project_choice_and_audit(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in (
            "Create New", "Continue Existing", "Auditing repository",
            "Audit results", "Create project brief", "api/project/discover",
        ):
            self.assertIn(marker, js)
        for removed_copy in (
            "Onboarding unlocks", "finish onboarding to create one",
            "Finish Setup and Onboarding to start building",
            "onboarding finishes",
        ):
            self.assertNotIn(removed_copy, js)

    def test_approve_stage_wires_scope_editor_and_exact_approval(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in (
            "Draft product scope", "Acceptance criteria",
            "Material coverage gaps", "api/project/scope",
            "api/project/approve", "api/project/decompose",
            "expected_revision: scope.revision",
            "audit_fingerprint: audit.fingerprint",
            "acknowledged_gaps: gapIds",
            "scopeEditor.dirty = true", "approve.disabled = true",
        ):
            self.assertIn(marker, js)

    def test_project_css_has_bounded_choice_audit_and_scope_styles(self):
        _, _, body = get(self.port, "/static/app.css")
        css = body.decode()
        for token in (".project-choices", ".audit-grid", ".feature-card"):
            self.assertIn(token, css)
        self.assertNotIn(".scope-feature", css)

    def test_connect_stage_wires_agents_lineup_and_workspace(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/setup", "loadConnect", "boss-lineup",
                       "workspace-attach", "attach_command",
                       "api/connection/launch", "api/connection/verify",
                       "features-per-turn",
                       "features_per_turn: pick.features_per_turn"):
            self.assertIn(marker, js)
        for removed in ("Who Does What", "characterRow", "data-seat",
                        "SEAT_VERBS", "Specialist roles", "ONE ACTIVE BOSS",
                        "NO ROLE THEATRE", "turnSize",
                        "ACTIVE TONY-D", "WAITING FOR ITS TURN"):
            self.assertNotIn(removed, js)
        for value in ('value="2"', 'value="3"', 'value="4"', 'value="5"'):
            self.assertIn(value, js)
        for removed in ("Full Power", "data-dial", "data-override",
                        "dial: pick.dial", "overrides: pick.overrides"):
            self.assertNotIn(removed, js)
        # catalog strengths is a plain sentence (runners.py), not a list —
        # joining it crashes renderConnect (found in the T13 live eyeball)
        self.assertNotIn("a.strengths || []", js)
        self.assertIn("a.strengths || \"\"", js)

    def test_setup_css_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        css = body.decode()
        for token in (".agent-card", ".boss-lineup", ".boss-card",
                      ".boss-feature-choice", ".setup-live-status",
                      ".workspace-panel", ".workspace-pane"):
            self.assertIn(token, css)
        self.assertNotIn(".dial-card", css)

    def test_build_stage_wires_relay_controls_and_progress(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/build/start", "api/build/stop", "loadBuild",
                       "Stop the build crew? The current turn finishes safely.",
                       "Finish Approve to start building",
                       "Handed the baton to", "Live product progress",
                       'id="stage-body-${s.id}"'):
            self.assertIn(marker, js)

    def test_build_stage_renders_additions_via_the_shared_editor(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in (
            "Product scope revision", "Acceptance criteria",
            "Atomic build units", "Quota this turn", "Hard stop",
            "Blocked", "blocker_reason", "next_handoff",
            "Add product feature", "Save additions draft",
            "Approve exact additions revision",
            'post("api/build/additions"', 'post("api/build/approve"',
            "expected_revision: additions.revision",
            "additionsEditor.dirty = true",
        ):
            self.assertIn(marker, js)
        self.assertIn('bodyEl.contains(document.activeElement)', js)

    def test_build_css_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        css = body.decode()
        for token in (".session-tail", ".build-feature",
                      ".build-feature.completed", ".build-unit",
                      ".quota-meter", ".build-alert", ".feature-card"):
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
                  "headless": [], "detected": True, "auth": "ok"}}}
    (Path(root) / RUNNERS_RELPATH).write_text(json.dumps(config))
    routing = {"version": ROUTING_SCHEMA_VERSION, "features_per_turn": 2,
               "lineup": ["stub"], "seats": team_seats("stub")}
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

    def test_get_setup_reports_agents_without_auto_selecting_clients(self):
        status, _, raw = get(self.port, "/api/setup")
        self.assertEqual(status, 200)
        o = json.loads(raw)
        names = [a["name"] for a in o["agents"]]
        # five real catalog entries; the generic copy-me template is no card
        self.assertEqual(names, ["claude", "codex", "gemini", "grok",
                                 "hermes", "opencode"])
        claude = o["agents"][0]
        self.assertEqual(claude["display_name"], "Claude Code")
        self.assertTrue(claude["detected"])
        self.assertEqual(claude["auth"], "ok")
        self.assertEqual(claude["state"], "verified")
        codex = o["agents"][1]
        self.assertFalse(codex["detected"])
        self.assertEqual(codex["auth"], "unprobed")
        self.assertEqual(codex["state"], "not_installed")
        gemini = o["agents"][2]
        self.assertEqual(gemini["state"], "verified")
        # A fresh project is intentionally empty. Detection never chooses a
        # boss or specialist assignment on the user's behalf.
        self.assertEqual(o["lineup"], [])
        self.assertIsNone(o["active_boss"])
        self.assertEqual(o["waiting_bosses"], [])
        self.assertEqual(o["features_per_turn"], 2)
        # P T8a: dead setup_summary fields are gone — seats/boss_mode are
        # internal routing detail now, and roster lives on /api/overview.
        for removed in ("dial", "overrides", "floors", "budgets_error",
                        "seats", "conductor", "specialist_execution",
                        "boss_turns", "roster"):
            self.assertNotIn(removed, o)
        self.assertFalse(o["setup_complete"])

    def test_setup_summary_reports_provider_states(self):
        server_mod._BUILD_REGISTRY = lambda: fake_registry(
            auth={"claude": "unauthenticated", "gemini": "unprobed"})
        server_mod._reset_registry_cache()
        summary = server_mod.setup_summary(self.root)
        states = {agent["name"]: agent["state"] for agent in summary["agents"]}
        self.assertEqual(states["claude"], "needs_sign_in")
        self.assertEqual(states["gemini"], "verification_unavailable")

    def test_post_setup_writes_only_runners_and_routing(self):
        body = {"lineup": ["claude", "gemini"],
                "features_per_turn": 4,
                "seats": team_seats("claude", research="gemini",
                                    map="gemini")}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200, out)
        self.assertTrue(out["ok"])
        self.assertTrue(out["setup"]["setup_complete"])
        for rel in (RUNNERS_RELPATH, ROUTING_RELPATH):
            self.assertTrue((Path(self.root) / rel).exists(), rel)
        self.assertFalse((Path(self.root) / STALE_BUDGETS_RELPATH).exists())
        saved = json.loads((Path(self.root) / RUNNERS_RELPATH).read_text())
        self.assertEqual(saved["boss"], "claude")  # boss = lineup[0]
        routing = json.loads((Path(self.root) / ROUTING_RELPATH).read_text())
        self.assertEqual(routing["features_per_turn"], 4)
        self.assertEqual(out["setup"]["features_per_turn"], 4)

    def test_post_setup_accepts_ordered_boss_lineup_without_role_mapping(self):
        body = {"lineup": ["gemini", "claude"], "features_per_turn": 2}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200, out)
        routing = json.loads((Path(self.root) / ROUTING_RELPATH).read_text())
        self.assertEqual(routing["lineup"], ["gemini", "claude"])
        self.assertEqual(routing["boss_mode"], "sequential")
        self.assertEqual(routing["seats"]["conductor"], "builtin")
        for work_type in SEAT_WORK_TYPES:
            self.assertEqual(routing["seats"][work_type], "gemini")
        setup = out["setup"]
        self.assertEqual(setup["active_boss"], "gemini")
        self.assertEqual(setup["waiting_bosses"], ["claude"])

    def test_activated_setup_prepares_the_shared_workspace_before_save(self):
        installation = Path(self.root) / ".danza" / "runtime" / "installation.json"
        installation.parent.mkdir(parents=True, exist_ok=True)
        installation.write_text("{}")
        with patch.object(server_mod, "_PREPARE_WORKSPACE",
                          return_value={"host": "tmux"}) as prepare:
            status, out = post(self.port, "/api/setup", {
                "lineup": ["claude", "gemini"], "features_per_turn": 2})
        self.assertEqual(status, 200, out)
        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.args[1], ["claude", "gemini"])

    def test_connection_launch_endpoint_starts_project_client_session(self):
        saved = server_mod.launch_runner
        server_mod.launch_runner = lambda root, runner, config: {
            "status": "launched", "runner": runner,
            "session": "danza-demo-claude",
            "attach_command": "tmux attach -t danza-demo-claude"}
        self.addCleanup(lambda: setattr(server_mod, "launch_runner", saved))
        status, out = post(self.port, "/api/connection/launch",
                           {"runner": "claude"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["launch"]["status"], "launched")
        self.assertIn("tmux attach", out["launch"]["attach_command"])

    def test_workspace_open_endpoint_returns_workspace_and_terminal_status(self):
        with patch.object(server_mod, "open_workspace", return_value={
                "workspace": {"host": "tmux", "session": "danza-demo"},
                "terminal": {"opened": True}}) as opened:
            status, out = post(self.port, "/api/workspace/open", {})
        self.assertEqual(status, 200, out)
        opened.assert_called_once_with(self.root)
        self.assertEqual(out["workspace"]["host"], "tmux")
        self.assertTrue(out["terminal"]["opened"])

    def test_setup_summary_tracks_sequential_turn_owner(self):
        status, out = post(self.port, "/api/setup", {
            "lineup": ["claude", "gemini"], "features_per_turn": 2})
        self.assertEqual(status, 200, out)
        runtime = Path(self.root) / ".danza" / "runtime"
        (runtime / "team-state.json").write_text(json.dumps({
            **TEAM_STATE, "turn_number": 3, "current_boss": "gemini"}))
        summary = server_mod.setup_summary(self.root)
        self.assertEqual(summary["active_boss"], "gemini")
        self.assertEqual(summary["waiting_bosses"], ["claude"])

    def test_post_rejects_five_runner_lineup(self):
        body = {"lineup": ["claude", "gemini", "codex", "grok", "opencode"],
                "features_per_turn": 2}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("1-4", out["error"])

    def test_post_requires_valid_features_per_turn_before_any_write(self):
        base = {"lineup": ["claude"], "seats": team_seats("claude")}
        for value in (None, True, False, 1, 6, 2.5, "2"):
            with self.subTest(value=value):
                body = dict(base)
                if value is not None:
                    body["features_per_turn"] = value
                status, out = post(self.port, "/api/setup", body)
                self.assertEqual(status, 400, out)
                for rel in (RUNNERS_RELPATH, ROUTING_RELPATH):
                    self.assertFalse((Path(self.root) / rel).exists(), rel)

    def test_post_setup_ignores_and_preserves_stale_budgets_file(self):
        stale = Path(self.root) / STALE_BUDGETS_RELPATH
        stale.parent.mkdir(parents=True, exist_ok=True)
        original = '{"dial":"full_power","overrides":{"bonnie-qa":1}}\n'
        stale.write_text(original)
        body = {"lineup": ["claude"], "seats": team_seats("claude"),
                "features_per_turn": 2,
                "dial": "not-a-real-setting", "overrides": ["invalid"]}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200, out)
        self.assertEqual(stale.read_text(), original)
        for removed in ("dial", "overrides", "floors", "budgets_error"):
            self.assertNotIn(removed, out["setup"])

    def test_post_rejects_six_runner_lineup(self):
        body = {"lineup": ["claude", "codex", "gemini", "grok", "hermes", "opencode",
                           "generic"],
                "features_per_turn": 2}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("1-4", out["error"])

    def test_post_rejects_unauthenticated_lineup_member(self):
        server_mod._BUILD_REGISTRY = \
            lambda: fake_registry(auth={"claude": "unauthenticated"})
        server_mod._reset_registry_cache()
        body = {"lineup": ["claude"], "features_per_turn": 2}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 400)
        self.assertIn("not logged in", out["error"])

    def test_post_ignores_legacy_seats_and_boss_mode_in_body(self):
        # P T8a: sequential relay is the only routing model that ships —
        # an explicit "seats"/"boss_mode" body (the retired per-seat picker)
        # is ignored like any other unrecognized field, not honored or
        # rejected.
        body = {"lineup": ["claude", "gemini"], "features_per_turn": 3,
                "seats": team_seats("gemini", plan="claude"),
                "boss_mode": "seat_routed"}
        status, out = post(self.port, "/api/setup", body)
        self.assertEqual(status, 200, out)
        routing = json.loads((Path(self.root) / ROUTING_RELPATH).read_text())
        self.assertEqual(routing["boss_mode"], "sequential")
        for work_type in SEAT_WORK_TYPES:
            self.assertEqual(routing["seats"][work_type], "claude")
        self.assertEqual(out["setup"]["lineup"], ["claude", "gemini"])
        self.assertEqual(out["setup"]["features_per_turn"], 3)

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
            "lineup": ["claude"], "features_per_turn": 2})
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
        self.assertNotIn("dial", runners)

    def test_snapshot_token_moves_on_routing_but_ignores_stale_budgets(self):
        t0 = snapshot_token(self.root)
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (Path(self.root) / ROUTING_RELPATH).write_text("{}")
        t1 = snapshot_token(self.root)
        self.assertNotEqual(t0, t1)
        (Path(self.root) / STALE_BUDGETS_RELPATH).write_text("{}")
        self.assertEqual(t1, snapshot_token(self.root))


def _flow_feature(feature_id, *, status="pending"):
    return {"id": feature_id,
            "summary": f"Users can complete outcome {feature_id}.",
            "acceptance_criteria": [f"Outcome {feature_id} is verified."],
            "status": status}


def _flow_leaf(unit_id, feature_id):
    return {"id": unit_id, "feature_id": feature_id,
            "description": f"implement {unit_id}", "kind": "backend",
            "size_est": 10, "writes": [f"src/{unit_id}.py"],
            "verification": {"kind": "automated_test", "detail": "exit 0"}}


class TestFlowApi(unittest.TestCase):
    """P T8a: /api/flow one-flow stage machine + merged team roster."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / ".danza" / "runtime").mkdir(parents=True)

    def _stage(self, flow, stage_id):
        return next(s for s in flow["stages"] if s["id"] == stage_id)

    def _seed_connect_and_describe(self):
        """Confirmed team + verified connection + a written project brief —
        Connect and Describe both complete."""
        seed_confirmed_setup(self.root)
        (Path(self.root) / ".danza" / "runtime" / "connection.json").write_text(
            json.dumps({"status": "verified", "runner": "stub"}))
        (Path(self.root) / ".danza" / "spec.md").write_text("# Spec\n")

    def _seed_approved_plan(self, *, completed=False):
        """An approved features.json (revision 1) plus a matching plan.json
        with two leaves — the minimal 'Approve stage complete' fixture."""
        scope = product_scope_mod.new_scope(
            [_flow_feature(1), _flow_feature(2)])
        product_scope_mod.write_scope(self.root, scope)
        product_scope_mod.approve_scope(self.root, expected_revision=1)
        tasks = [_flow_leaf("1.1", 1), _flow_leaf("2.1", 2)]
        order = [t["id"] for t in tasks]
        execution = execution_mod.initial_execution(order)
        if completed:
            for unit_id in order:
                execution[unit_id].update({
                    "status": "completed", "started_at": "start",
                    "completed_at": "done", "actual_minutes": 1,
                    "verification_attempts": 1, "verification_passed": True,
                    "verification_evidence": [{"passed": True}],
                    "completed_turn": 0,
                })
        plan = {"spec_ref": ".danza/features.json#revision-1",
                "tasks": tasks, "order": order, "execution": execution,
                "calibration": []}
        (Path(self.root) / ".danza" / "plan.json").write_text(
            json.dumps(plan), encoding="utf-8")

    def test_fresh_project_is_all_incomplete_and_current_is_connect(self):
        flow = server_mod.flow_state(self.root)
        self.assertEqual([s["id"] for s in flow["stages"]],
                         ["connect", "describe", "approve", "build", "done"])
        self.assertTrue(all(not s["complete"] for s in flow["stages"]))
        self.assertEqual(flow["current"], "connect")
        self.assertEqual(flow["team"], [])

    def test_connect_completes_on_confirmed_team_and_verified_connection(self):
        seed_confirmed_setup(self.root)
        (Path(self.root) / ".danza" / "runtime" / "connection.json").write_text(
            json.dumps({"status": "verified", "runner": "stub"}))
        flow = server_mod.flow_state(self.root)
        self.assertTrue(self._stage(flow, "connect")["complete"])
        self.assertEqual(flow["current"], "describe")

    def test_connect_incomplete_without_verified_connection(self):
        seed_confirmed_setup(self.root)  # team confirmed, never verified
        flow = server_mod.flow_state(self.root)
        stage = self._stage(flow, "connect")
        self.assertFalse(stage["complete"])
        self.assertTrue(stage["team_confirmed"])
        self.assertEqual(flow["current"], "connect")

    def test_describe_completes_when_spec_is_written(self):
        self._seed_connect_and_describe()
        flow = server_mod.flow_state(self.root)
        self.assertTrue(self._stage(flow, "describe")["complete"])
        self.assertEqual(flow["current"], "approve")

    def test_approve_completes_when_scope_approved_and_plan_matches(self):
        self._seed_connect_and_describe()
        self._seed_approved_plan()
        flow = server_mod.flow_state(self.root)
        stage = self._stage(flow, "approve")
        self.assertTrue(stage["complete"])
        self.assertEqual(stage["scope_state"], "approved")
        self.assertEqual(stage["revision"], 1)
        self.assertEqual(stage["features_total"], 2)
        self.assertEqual(flow["current"], "build")

    def test_approve_incomplete_when_scope_is_only_drafted(self):
        self._seed_connect_and_describe()
        scope = product_scope_mod.new_scope([_flow_feature(1)])
        product_scope_mod.write_scope(self.root, scope)
        flow = server_mod.flow_state(self.root)
        stage = self._stage(flow, "approve")
        self.assertFalse(stage["complete"])
        self.assertEqual(stage["scope_state"], "draft")
        self.assertEqual(flow["current"], "approve")

    def test_build_and_done_complete_when_every_feature_is_completed(self):
        self._seed_connect_and_describe()
        self._seed_approved_plan(completed=True)
        flow = server_mod.flow_state(self.root)
        build_stage = self._stage(flow, "build")
        self.assertTrue(build_stage["complete"])
        self.assertEqual(build_stage["status"], "completed")
        self.assertEqual(build_stage["completed"], 2)
        self.assertEqual(build_stage["total"], 2)
        self.assertTrue(self._stage(flow, "done")["complete"])
        self.assertEqual(flow["current"], "done")

    def test_build_reports_pending_status_before_any_work_starts(self):
        self._seed_connect_and_describe()
        self._seed_approved_plan(completed=False)
        flow = server_mod.flow_state(self.root)
        build_stage = self._stage(flow, "build")
        self.assertFalse(build_stage["complete"])
        self.assertEqual(build_stage["status"], "pending")
        self.assertFalse(build_stage["running"])
        self.assertFalse(self._stage(flow, "done")["complete"])
        self.assertEqual(flow["current"], "build")

    def test_build_stage_light_summary_carries_a_single_saved_tokens_number(self):
        # P4.1 T9 requirement 4: /api/flow gets one small number, never the
        # injected/replaced breakdown (that lives in /api/build detail).
        build_stage = server_mod._build_stage(self.root)
        self.assertEqual(build_stage["saved_tokens"], 0)
        self.assertNotIn("injected_tokens", build_stage)
        self.assertNotIn("replaced_tokens", build_stage)

        from danzaboss.cortex import commands as cortex_commands
        from danzaboss.cortex.identity import resolve_project
        project = resolve_project(str(self.root))
        CaptureLog(cortex_commands.db_path(str(self.root))).record_context_read(
            project, "jonathan-builder", 400, 900, replaced=1200)
        self.assertEqual(
            server_mod._build_stage(self.root)["saved_tokens"], 800)

    def test_team_roster_is_empty_without_a_confirmed_team(self):
        self.assertEqual(server_mod.flow_state(self.root)["team"], [])

    def test_team_roster_merges_active_waiting_pane_and_live_state(self):
        config = default_config({"claude": True, "codex": True})
        config["runners"]["claude"]["auth"] = "ok"
        config["runners"]["codex"]["auth"] = "ok"
        save_runners_config(self.root, config)
        seats = {seat: "claude" for seat in SEAT_WORK_TYPES}
        seats["conductor"] = routing_mod.BUILTIN_CONDUCTOR
        routing_mod.save_routing(self.root, {
            "version": ROUTING_SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude", "codex"], "seats": seats}, config)
        save_workspace(self.root, {
            "schema_version": 1, "session": session_name(self.root),
            "host": "tmux", "order": ["claude", "codex"],
            "panes": {"claude": "%1", "codex": "%2"},
            "active_runner": "claude", "terminal_opened": True})
        (Path(self.root) / ".danza" / "runtime" / "team-state.json").write_text(
            json.dumps({**TEAM_STATE, "turn_number": 1, "current_boss": "codex"}))

        class FakeHost:
            def alive(self, name):
                return True

        saved = server_mod._SESSION_HOST
        server_mod._SESSION_HOST = lambda root: FakeHost()
        self.addCleanup(lambda: setattr(server_mod, "_SESSION_HOST", saved))

        team = server_mod.flow_state(self.root)["team"]

        self.assertEqual([m["runner"] for m in team], ["claude", "codex"])
        claude, codex = team
        self.assertEqual(claude["display_name"], "Claude Code")
        self.assertEqual(claude["pane"], "%1")
        self.assertTrue(claude["live"])
        self.assertFalse(claude["active"])   # turn_number=1 -> codex's turn
        self.assertEqual(codex["display_name"], "Codex")
        self.assertEqual(codex["pane"], "%2")
        self.assertTrue(codex["active"])

    def test_team_roster_pane_is_not_live_when_the_session_is_dead(self):
        config = default_config({"claude": True})
        config["runners"]["claude"]["auth"] = "ok"
        save_runners_config(self.root, config)
        seats = {seat: "claude" for seat in SEAT_WORK_TYPES}
        seats["conductor"] = routing_mod.BUILTIN_CONDUCTOR
        routing_mod.save_routing(self.root, {
            "version": ROUTING_SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude"], "seats": seats}, config)
        save_workspace(self.root, {
            "schema_version": 1, "session": session_name(self.root),
            "host": "tmux", "order": ["claude"], "panes": {"claude": "%1"},
            "active_runner": "claude", "terminal_opened": True})

        class DeadHost:
            def alive(self, name):
                return False

        saved = server_mod._SESSION_HOST
        server_mod._SESSION_HOST = lambda root: DeadHost()
        self.addCleanup(lambda: setattr(server_mod, "_SESSION_HOST", saved))

        team = server_mod.flow_state(self.root)["team"]
        self.assertEqual(len(team), 1)
        self.assertFalse(team[0]["live"])

    def test_http_route_serves_the_same_payload_as_flow_state(self):
        self._seed_connect_and_describe()
        server, port = serve_in_thread(self.root)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        status, ctype, raw = get(port, "/api/flow")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(raw), server_mod.flow_state(self.root))


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
        """Confirmed setup + exact approved scope + matching plan."""
        seed_confirmed_setup(self.root)
        project_mod.discover_project(self.root, mode="new")
        project_mod.draft_scope(self.root, features=[{
            "id": 71,
            "summary": "Users can run the prepared build plan.",
            "acceptance_criteria": ["The matching plan can start."],
            "status": "pending",
        }])
        project_mod.approve_project_scope(self.root, expected_revision=1)
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
        state = json.loads((Path(self.root) / ".danza" / "runtime" /
                            "team-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_boss"], "stub")
        self.assertEqual(state["max_features_per_turn"], 2)
        self.assertEqual(out["conclusion"], "continue")

    def test_start_preflight_concludes_no_work_without_spawning(self):
        self._pass_start_gate()
        data = json.loads(json.dumps(PLAN))
        data["execution"] = execution_mod.initial_execution(data["order"])
        data["calibration"] = []
        for unit_id in data["order"]:
            data["execution"][unit_id].update({
                "status": "completed", "started_at": "start",
                "completed_at": "done", "actual_minutes": 1,
                "verification_attempts": 1, "verification_passed": True,
                "verification_evidence": [{"passed": True}],
                "completed_turn": 0,
            })
        (Path(self.root) / ".danza" / "plan.json").write_text(
            json.dumps(data), encoding="utf-8")

        out = server_mod.post_build_start(
            self.root, {}, popen=lambda *a, **k: self.fail("must not spawn"))

        self.assertTrue(out["ok"])
        self.assertIsNone(out["pid"])
        self.assertEqual(out["conclusion"], "no_work")
        state = json.loads((Path(self.root) / ".danza" / "runtime" /
                            "team-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "done")

    def test_start_preflight_concludes_hard_stop_without_spawning(self):
        self._pass_start_gate()
        data = json.loads(json.dumps(PLAN))
        data["tasks"][0]["subtasks"][0]["flags"] = ["auth"]
        (Path(self.root) / ".danza" / "plan.json").write_text(
            json.dumps(data), encoding="utf-8")

        out = server_mod.post_build_start(
            self.root, {}, popen=lambda *a, **k: self.fail("must not spawn"))

        self.assertIsNone(out["pid"])
        self.assertEqual(out["conclusion"], "hard_stop")
        state = json.loads((Path(self.root) / ".danza" / "runtime" /
                            "team-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "blocked")

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
