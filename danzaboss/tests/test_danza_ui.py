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
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/overview", data=b"{}",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 405")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)
            e.close()

    def test_conductor_endpoint_serves_tail(self):
        _, _, body = get(self.port, "/api/conductor?limit=1")
        items = json.loads(body)["items"]
        self.assertEqual(items[0]["event"], "session_end")


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


if __name__ == "__main__":
    unittest.main()
