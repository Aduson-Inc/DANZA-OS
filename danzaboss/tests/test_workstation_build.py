"""Phase 4.1 Task 8: BUILD backend state, additions, and queueing."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa

from danzaboss.kernel.state import StateManager
from danzaboss.workstation import build, execution, product_scope, routing
from danzaboss.workstation import server as server_mod
from danzaboss.workstation.conductor import TEAM_STATE_RELPATH
from danzaboss.workstation.planner import PLAN_JSON_RELPATH
from danzaboss.workstation.runners import default_config, save_runners


def feature(feature_id, *, status="pending"):
    return {
        "id": feature_id,
        "summary": f"Users can complete product outcome {feature_id}.",
        "acceptance_criteria": [f"Outcome {feature_id} is verified."],
        "status": status,
    }


def leaf(unit_id, feature_id, *, depends_on=()):
    return {
        "id": unit_id,
        "feature_id": feature_id,
        "description": f"implement {unit_id}",
        "kind": "backend",
        "size_est": 10,
        "writes": [f"src/{unit_id}.py"],
        "depends_on": list(depends_on),
        "verification": {"kind": "automated_test", "detail": "exit 0"},
    }


def completed_record(record, *, turn=0):
    record.update({
        "status": "completed",
        "started_at": "2026-07-15T10:00:00+00:00",
        "completed_at": "2026-07-15T10:05:00+00:00",
        "actual_minutes": 5,
        "verification_attempts": 1,
        "verification_passed": True,
        "verification_evidence": [{"passed": True}],
        "completed_turn": turn,
    })


class BuildFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".danza" / "runtime").mkdir(parents=True)
        scope = product_scope.new_scope([feature(71), feature(72)])
        product_scope.write_scope(self.root, scope)
        product_scope.approve_scope(self.root, expected_revision=1)
        tasks = [leaf("71-A", 71), leaf("71-B", 71, depends_on=("71-A",)),
                 leaf("72-A", 72)]
        order = [item["id"] for item in tasks]
        self.write_plan({
            "spec_ref": ".danza/features.json#revision-1",
            "tasks": tasks,
            "order": order,
            "execution": execution.initial_execution(order),
            "calibration": [],
        })

    def write_plan(self, plan):
        (self.root / PLAN_JSON_RELPATH).write_text(
            json.dumps(plan), encoding="utf-8")

    def plan(self):
        return json.loads((self.root / PLAN_JSON_RELPATH).read_text())


class LiveBuildPayload(BuildFixture):
    def test_payload_links_scope_to_units_and_derives_live_feature_status(self):
        plan = self.plan()
        completed_record(plan["execution"]["71-A"])
        plan["execution"]["72-A"].update({
            "status": "blocked", "blocker_reason": "needs credentials"})
        self.write_plan(plan)

        payload = build.live_payload(self.root)

        self.assertEqual(payload["scope"]["revision"], 1)
        self.assertEqual(payload["progress"], {
            "status": "blocked", "completed": 0, "total": 2, "percent": 0})
        by_id = {item["id"]: item for item in payload["features"]}
        self.assertEqual(by_id[71]["status"], "in_progress")
        self.assertEqual([unit["id"] for unit in by_id[71]["units"]],
                         ["71-A", "71-B"])
        self.assertEqual(by_id[71]["units"][0]["status"], "completed")
        self.assertEqual(by_id[72]["status"], "blocked")
        self.assertEqual(by_id[72]["units"][0]["blocker_reason"],
                         "needs credentials")

    def test_payload_reports_turn_quota_and_queue_state(self):
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=3)
        manager.transition(actor="claude", to_status="in_progress",
                           features_completed_this_turn=1)

        payload = build.live_payload(self.root)

        self.assertEqual(payload["quota"], {"completed": 1, "limit": 3,
                                             "remaining": 2})
        self.assertIsNone(payload["additions"])
        self.assertIsNone(payload["next_handoff"])


class TransactionalProgress(BuildFixture):
    def test_execution_mutations_transactionally_update_scope_status(self):
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=3)

        execution.begin_unit(
            self.root, manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")
        self.assertEqual(product_scope.load_scope(self.root)["features"][0]
                         ["status"], "in_progress")

        execution.verify_unit(
            self.root, manager, "claude", "71-A",
            completed_at="2026-07-15T10:05:00+00:00")
        self.assertEqual(product_scope.load_scope(self.root)["features"][0]
                         ["status"], "in_progress")

        execution.begin_unit(self.root, manager, "claude", "71-B")
        execution.verify_unit(self.root, manager, "claude", "71-B")
        scope = product_scope.load_scope(self.root)
        self.assertEqual(scope["features"][0]["status"], "completed")
        self.assertIn("Progress: 1/2", (self.root / ".danza" /
                                        "feature-list.md").read_text())
        self.assertFalse((self.root / build.PROGRESS_TX_RELPATH).exists())

    def test_interrupted_progress_transaction_recovers_all_artifacts(self):
        plan = self.plan()
        completed_record(plan["execution"]["71-A"])
        completed_record(plan["execution"]["71-B"])
        scope = product_scope.load_scope(self.root)
        scope["features"][0]["status"] = "completed"
        journal = {"version": 1, "plan": plan, "scope": scope}
        path = self.root / build.PROGRESS_TX_RELPATH
        path.write_text(json.dumps(journal), encoding="utf-8")

        self.assertTrue(build.recover_progress(self.root))

        self.assertEqual(self.plan()["execution"]["71-B"]["status"],
                         "completed")
        self.assertEqual(product_scope.load_scope(self.root)["features"][0]
                         ["status"], "completed")
        self.assertFalse(path.exists())

    def test_execution_mutation_rejects_draft_scope_without_touching_plan(self):
        current = product_scope.load_scope(self.root)
        product_scope.revise_scope(
            self.root, expected_revision=1,
            features=current["features"])
        before = (self.root / PLAN_JSON_RELPATH).read_bytes()

        with self.assertRaises(execution.ExecutionError):
            execution.start_unit(self.root, "71-A")

        self.assertEqual((self.root / PLAN_JSON_RELPATH).read_bytes(), before)

    def test_invalid_recovery_transition_fails_as_build_error_and_keeps_journal(self):
        plan = self.plan()
        plan["spec_ref"] = ".danza/features.json#revision-3"
        scope = product_scope.load_scope(self.root)
        scope["revision"] = 3
        scope["approval"] = {"state": "approved", "approved_revision": 3}
        journal = self.root / build.PROGRESS_TX_RELPATH
        journal.write_text(json.dumps({
            "version": 1, "plan": plan, "scope": scope,
        }), encoding="utf-8")

        with self.assertRaises(build.BuildError):
            build.recover_progress(self.root)

        self.assertTrue(journal.exists())


class AdditionsAndQueue(BuildFixture):
    def proposed_plan(self, planning_scope, spec_ref, reserved_ids):
        self.proposal = (planning_scope, spec_ref, reserved_ids)
        next_ids = {71: "71-C", 72: "72-B", 73: "73-A"}
        tasks = [leaf(next_ids[item["id"]], item["id"])
                 for item in planning_scope["features"]]
        order = [item["id"] for item in tasks]
        return {"spec_ref": spec_ref, "tasks": tasks, "order": order,
                "execution": execution.initial_execution(order),
                "calibration": []}

    def test_exact_addition_approval_replans_only_unfinished_work_and_queues(self):
        plan = self.plan()
        completed_record(plan["execution"]["71-A"])
        self.write_plan(plan)
        build.commit_progress(self.root, plan)
        active_scope = (self.root / product_scope.FEATURES_JSON_RELPATH).read_bytes()
        active_plan = (self.root / PLAN_JSON_RELPATH).read_bytes()
        draft = build.draft_additions(self.root, additions=[feature(73)])

        queued = build.approve_additions(
            self.root, expected_revision=draft["revision"],
            propose=self.proposed_plan)

        planning_scope, spec_ref, reserved = self.proposal
        self.assertEqual([item["id"] for item in planning_scope["features"]],
                         [71, 72, 73])
        self.assertEqual(reserved, {"71-A"})
        self.assertEqual(spec_ref, ".danza/features.json#revision-2")
        self.assertEqual(queued["scope_revision"], 2)
        self.assertEqual(queued["activate_at"], "next_handoff")
        self.assertEqual((self.root / product_scope.FEATURES_JSON_RELPATH)
                         .read_bytes(), active_scope)
        self.assertEqual((self.root / PLAN_JSON_RELPATH).read_bytes(), active_plan)
        queued_plan = json.loads((self.root / build.QUEUE_RELPATH).read_text())
        self.assertEqual(queued_plan["plan"]["order"],
                         ["71-A", "71-C", "72-B", "73-A"])
        self.assertEqual(queued_plan["plan"]["execution"]["71-A"]["status"],
                         "completed")

    def test_stale_approval_and_completed_id_reuse_leave_active_work_unchanged(self):
        draft = build.draft_additions(self.root, additions=[feature(73)])
        build.draft_additions(self.root, expected_revision=draft["revision"],
                              additions=[feature(74)])
        before = (self.root / PLAN_JSON_RELPATH).read_bytes()

        with self.assertRaises(build.BuildRevisionConflict):
            build.approve_additions(
                self.root, expected_revision=1, propose=self.proposed_plan)
        with self.assertRaises(build.BuildError):
            build.draft_additions(self.root, expected_revision=2,
                                  additions=[feature(71)])

        self.assertEqual((self.root / PLAN_JSON_RELPATH).read_bytes(), before)
        self.assertFalse((self.root / build.QUEUE_RELPATH).exists())

    def test_queue_activates_on_quota_handoff_before_routing(self):
        config = default_config({"claude": True, "codex": True})
        config["runners"]["claude"]["auth"] = "ok"
        config["runners"]["codex"]["auth"] = "ok"
        save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude", "codex"], "seats": seats,
        }, config)
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=2)
        plan = self.plan()
        for unit_id in ("71-A", "71-B"):
            completed_record(plan["execution"][unit_id])
        self.write_plan(plan)
        build.commit_progress(self.root, plan)
        manager.transition(actor="claude", to_status="in_progress",
                           features_completed_this_turn=2,
                           verified_unit_ids_this_turn=["71-A", "71-B"],
                           handoff_required=True)
        draft = build.draft_additions(self.root, additions=[feature(73)])
        build.approve_additions(self.root, expected_revision=draft["revision"],
                                propose=self.proposed_plan)

        out = execution.apply_turn_conclusion(
            self.root, manager, "claude", next_boss="codex")

        self.assertEqual(out["conclusion"], "quota")
        self.assertEqual(product_scope.load_scope(self.root)["revision"], 2)
        self.assertEqual(self.plan()["spec_ref"],
                         ".danza/features.json#revision-2")
        self.assertIn("revision-2", (self.root / ".danza" / "plan.md").read_text())
        self.assertFalse((self.root / build.QUEUE_RELPATH).exists())
        self.assertEqual(manager.load().status, "awaiting_handoff")

    def test_active_unit_is_carried_and_queue_activates_at_safe_unit_boundary(self):
        config = default_config({"claude": True})
        config["runners"]["claude"]["auth"] = "ok"
        save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude"], "seats": seats,
        }, config)
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=2)
        execution.begin_unit(
            self.root, manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")
        draft = build.draft_additions(self.root, additions=[feature(73)])
        build.approve_additions(self.root, expected_revision=draft["revision"],
                                propose=self.proposed_plan)

        out = execution.verify_unit(
            self.root, manager, "claude", "71-A",
            completed_at="2026-07-15T10:05:00+00:00")

        self.assertEqual(out["conclusion"], "continue")
        self.assertEqual(manager.load().status, "awaiting_handoff")
        activated = self.plan()
        self.assertEqual(activated["spec_ref"],
                         ".danza/features.json#revision-2")
        self.assertEqual(activated["execution"]["71-A"]["status"],
                         "completed")
        self.assertNotIn("71-B", activated["execution"])
        self.assertFalse((self.root / build.QUEUE_RELPATH).exists())

    def test_corrupt_queue_fails_closed_without_changing_team_state(self):
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=2)
        queue = self.root / build.QUEUE_RELPATH
        queue.write_text("{broken", encoding="utf-8")
        before = (self.root / TEAM_STATE_RELPATH).read_bytes()

        with self.assertRaises(execution.ExecutionError):
            execution.apply_turn_conclusion(
                self.root, manager, "claude", next_boss="claude")

        self.assertEqual((self.root / TEAM_STATE_RELPATH).read_bytes(), before)

    def test_queue_never_bypasses_a_hard_stop_conclusion(self):
        config = default_config({"claude": True})
        config["runners"]["claude"]["auth"] = "ok"
        save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude"], "seats": seats,
        }, config)
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=2)
        plan = self.plan()
        plan["tasks"][0]["flags"] = ["auth"]
        self.write_plan(plan)
        draft = build.draft_additions(self.root, additions=[feature(73)])
        build.approve_additions(self.root, expected_revision=draft["revision"],
                                propose=self.proposed_plan)

        out = execution.apply_turn_conclusion(self.root, manager, "claude")

        self.assertEqual(out["conclusion"], "hard_stop")
        self.assertEqual(manager.load().status, "blocked")
        self.assertTrue((self.root / build.QUEUE_RELPATH).exists())
        self.assertEqual(product_scope.load_scope(self.root)["revision"], 1)

    def test_queued_plan_hard_stop_blocks_before_next_runner_ignition(self):
        config = default_config({"claude": True, "codex": True})
        config["runners"]["claude"]["auth"] = "ok"
        config["runners"]["codex"]["auth"] = "ok"
        save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude", "codex"], "seats": seats,
        }, config)
        manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        manager.init(mode="relay", current_boss="claude",
                     max_features_per_turn=2)
        plan = self.plan()
        for unit_id in ("71-A", "71-B"):
            completed_record(plan["execution"][unit_id])
        self.write_plan(plan)
        build.commit_progress(self.root, plan)
        manager.transition(actor="claude", to_status="in_progress",
                           features_completed_this_turn=2,
                           verified_unit_ids_this_turn=["71-A", "71-B"],
                           handoff_required=True)
        draft = build.draft_additions(self.root, additions=[feature(73)])

        def hard_stop_plan(planning_scope, spec_ref, reserved_ids):
            proposed = self.proposed_plan(
                planning_scope, spec_ref, reserved_ids)
            proposed["tasks"][0]["flags"] = ["auth"]
            return proposed

        build.approve_additions(self.root, expected_revision=draft["revision"],
                                propose=hard_stop_plan)

        out = execution.apply_turn_conclusion(self.root, manager, "claude")

        self.assertEqual(out["conclusion"], "hard_stop")
        self.assertEqual(manager.load().status, "blocked")
        self.assertEqual(product_scope.load_scope(self.root)["revision"], 2)
        self.assertFalse((self.root / build.QUEUE_RELPATH).exists())


class BuildApiContracts(BuildFixture):
    def setUp(self):
        super().setUp()
        config = default_config({"claude": True})
        config["runners"]["claude"]["auth"] = "ok"
        save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude"], "seats": seats,
        }, config)

    def proposed_plan(self, planning_scope, spec_ref, _reserved_ids):
        tasks = [leaf(f"{item['id']}-Z", item["id"])
                 for item in planning_scope["features"]]
        order = [item["id"] for item in tasks]
        return {"spec_ref": spec_ref, "tasks": tasks, "order": order,
                "execution": execution.initial_execution(order),
                "calibration": []}

    def test_build_summary_includes_live_product_backend_payload(self):
        payload = server_mod.build_summary(self.root)

        self.assertEqual(payload["scope"]["revision"], 1)
        self.assertEqual([item["id"] for item in payload["features"]],
                         [71, 72])
        self.assertEqual(payload["progress"]["status"], "pending")

    def test_additions_and_approval_handlers_are_revisioned_and_queue_work(self):
        self.assertIn("/api/build/additions", server_mod._POST_ROUTES)
        self.assertIn("/api/build/approve", server_mod._POST_ROUTES)

        drafted = server_mod.post_build_additions(
            self.root, {"additions": [feature(73)]})
        approved = server_mod.post_build_approve(
            self.root, {"expected_revision": drafted["additions"]["revision"]},
            propose=self.proposed_plan)

        self.assertTrue(drafted["ok"])
        self.assertEqual(approved["next_handoff"]["scope_revision"], 2)
        with self.assertRaises(build.BuildRevisionConflict):
            server_mod.post_build_approve(
                self.root, {"expected_revision": 1},
                propose=self.proposed_plan)


class BuildHttpApi(BuildApiContracts):
    def setUp(self):
        super().setUp()
        self.server, self.port = server_mod.serve_in_thread(self.root)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=(None if body is None else json.dumps(body).encode("utf-8")),
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read())
            exc.close()
            return exc.code, payload

    def test_http_build_payload_and_stale_additions_conflict(self):
        status, payload = self.request("/api/build")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["scope"]["revision"], 1)

        status, drafted = self.request(
            "/api/build/additions", {"additions": [feature(73)]})
        self.assertEqual(status, 200, drafted)
        status, conflict = self.request(
            "/api/build/additions",
            {"expected_revision": 0, "additions": [feature(74)]})
        self.assertEqual(status, 409, conflict)
        self.assertIn("current revision is 1", conflict["error"])


if __name__ == "__main__":
    unittest.main()
