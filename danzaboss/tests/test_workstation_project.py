"""Phase 4.1 Task 6: PROJECT backend lifecycle and takeover audit."""
import json
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa

try:
    from danzaboss.workstation import project
except ImportError:
    class _MissingProject:
        ProjectRevisionConflict = AssertionError

        def __getattr__(self, _name):
            def missing(*_args, **_kwargs):
                raise AssertionError("PROJECT backend is not implemented")
            return missing

    project = _MissingProject()

from danzaboss.workstation import server as server_mod
from danzaboss.workstation.product_scope import load_scope
from danzaboss.workstation.routing import (
    ROUTING_RELPATH,
    SCHEMA_VERSION as ROUTING_SCHEMA_VERSION,
    SEAT_WORK_TYPES,
)
from danzaboss.workstation.runners import RUNNERS_RELPATH, SCHEMA_VERSION
from danzaboss.workstation.server import GateConflict, serve_in_thread


def feature(feature_id=71, summary="Users can inspect repository health."):
    return {
        "id": feature_id,
        "summary": summary,
        "acceptance_criteria": ["The audit reports repository evidence."],
        "status": "pending",
    }


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def seed_git_repo(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "task6@example.invalid")
    git(root, "config", "user.name", "Task Six")
    (Path(root) / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (Path(root) / "tests").mkdir()
    (Path(root) / "tests" / "test_app.py").write_text(
        "def test_app(): pass\n", encoding="utf-8")
    (Path(root) / "README.md").write_text("# Demo\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")


def seed_setup(root):
    runtime = Path(root) / ".danza" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    config = {
        "version": SCHEMA_VERSION,
        "boss": "stub",
        "session_host": "headless",
        "permission_mode": None,
        "runners": {"stub": {
            "kind": "cli", "binary": "stub", "display_name": "Stub",
            "strengths": "", "suggested_seats": [], "activation": "argv",
            "full_power_extra_argv": [], "interactive": ["stub"],
            "headless": [], "detected": True, "auth": "unprobed",
        }},
    }
    (Path(root) / RUNNERS_RELPATH).write_text(json.dumps(config))
    seats = {"conductor": "builtin"}
    seats.update({work_type: "stub" for work_type in SEAT_WORK_TYPES})
    routing = {"version": ROUTING_SCHEMA_VERSION, "features_per_turn": 2,
               "lineup": ["stub"], "seats": seats}
    (Path(root) / ROUTING_RELPATH).write_text(json.dumps(routing))


def post(port, path, body):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read())
        exc.close()
        return exc.code, payload


class ProjectDiscovery(unittest.TestCase):
    def test_new_mode_records_discovery_without_takeover_audit(self):
        with tempfile.TemporaryDirectory() as root:
            result = project.discover_project(root, mode="new")

            self.assertEqual(result["mode"], "new")
            self.assertIsNone(result["audit"])
            self.assertTrue(result["ready_for_scope"])
            self.assertEqual(project.project_summary(root)["mode"], "new")

    def test_existing_mode_audits_all_required_evidence_categories(self):
        with tempfile.TemporaryDirectory() as root:
            seed_git_repo(root)

            result = project.discover_project(root, mode="existing")

            audit = result["audit"]
            self.assertEqual(
                set(audit["evidence"]),
                {"repository", "git", "manifests", "source_graph", "tests",
                 "config", "docs", "git_history", "danza_artifacts",
                 "analyzer_coverage"},
            )
            self.assertEqual(audit["head"], git(root, "rev-parse", "HEAD"))
            self.assertTrue(audit["fingerprint"])

    def test_takeover_audit_caches_by_head_and_tracked_worktree(self):
        with tempfile.TemporaryDirectory() as root:
            seed_git_repo(root)
            first = project.discover_project(root, mode="existing")
            second = project.discover_project(root, mode="existing")
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(first["audit"], second["audit"])

            (Path(root) / "untracked.txt").write_text("ignored\n")
            untracked = project.discover_project(root, mode="existing")
            self.assertTrue(untracked["cached"])

            (Path(root) / "app.py").write_text("print('changed')\n")
            changed = project.discover_project(root, mode="existing")
            self.assertFalse(changed["cached"])
            self.assertNotEqual(first["audit"]["fingerprint"],
                                changed["audit"]["fingerprint"])

    def test_material_analyzer_gap_requires_exact_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            seed_git_repo(root)
            (Path(root) / "Widget.vue").write_text("<template/>\n")
            git(root, "add", "Widget.vue")
            git(root, "commit", "-qm", "add unsupported source")
            discovered = project.discover_project(root, mode="existing")
            gap_ids = [gap["id"] for gap in discovered["audit"]["gaps"]]
            self.assertIn("analyzer:.vue", gap_ids)

            with self.assertRaises(GateConflict):
                project.draft_scope(
                    root, features=[feature()],
                    audit_fingerprint=discovered["audit"]["fingerprint"],
                    acknowledged_gaps=[],
                )

            scope = project.draft_scope(
                root, features=[feature()],
                audit_fingerprint=discovered["audit"]["fingerprint"],
                acknowledged_gaps=gap_ids,
            )
            self.assertEqual(scope["approval"]["state"], "draft")

    def test_stale_takeover_fingerprint_is_a_revision_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            seed_git_repo(root)
            discovered = project.discover_project(root, mode="existing")
            (Path(root) / "app.py").write_text("print('changed')\n")

            self.assertFalse(project.project_summary(root)["ready_for_scope"])

            with self.assertRaises(project.ProjectRevisionConflict):
                project.draft_scope(
                    root, features=[feature()],
                    audit_fingerprint=discovered["audit"]["fingerprint"],
                    acknowledged_gaps=[],
                )


class ProjectScopeLifecycle(unittest.TestCase):
    def test_discovery_draft_exact_approval_then_decomposition_gate(self):
        with tempfile.TemporaryDirectory() as root:
            project.discover_project(root, mode="new")
            draft = project.draft_scope(root, features=[feature()])
            self.assertEqual(draft["revision"], 1)
            self.assertEqual(load_scope(root)["approval"]["state"], "draft")
            with self.assertRaises(GateConflict):
                project.require_approved_scope(root)

            approved = project.approve_project_scope(
                root, expected_revision=draft["revision"])
            self.assertEqual(
                project.require_approved_scope(root)["revision"],
                approved["revision"],
            )


class BuildApprovalGate(unittest.TestCase):
    def test_build_rejects_missing_draft_and_mismatched_scope_revisions(self):
        with tempfile.TemporaryDirectory() as root:
            seed_setup(root)
            plan_path = Path(root) / ".danza" / "plan.json"
            plan_path.write_text(json.dumps({
                "spec_ref": ".danza/features.json#revision-1",
                "tasks": [], "order": [], "execution": {},
                "calibration": [],
            }))
            never_spawn = lambda *_args, **_kwargs: self.fail("must not spawn")

            with self.assertRaisesRegex(GateConflict, "approved product scope"):
                server_mod.post_build_start(root, {}, popen=never_spawn)

            project.discover_project(root, mode="new")
            project.draft_scope(root, features=[feature()])
            with self.assertRaisesRegex(GateConflict, "exact current"):
                server_mod.post_build_start(root, {}, popen=never_spawn)

            project.approve_project_scope(root, expected_revision=1)
            plan_path.write_text(json.dumps({
                "spec_ref": ".danza/features.json#revision-2",
                "tasks": [], "order": [], "execution": {},
                "calibration": [],
            }))
            with self.assertRaisesRegex(GateConflict, "revision-1"):
                server_mod.post_build_start(root, {}, popen=never_spawn)


class ProjectHttpApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        seed_setup(self.root)
        self.server, self.port = serve_in_thread(self.root)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_project_routes_split_discovery_draft_approval_decomposition(self):
        expected = {
            "/api/project/discover", "/api/project/scope",
            "/api/project/approve", "/api/project/decompose",
        }
        self.assertTrue(expected.issubset(server_mod._POST_ROUTES))

    def test_stale_scope_approval_returns_http_409(self):
        status, out = post(self.port, "/api/project/discover", {"mode": "new"})
        self.assertEqual(status, 200, out)
        status, draft = post(self.port, "/api/project/scope",
                             {"features": [feature()]})
        self.assertEqual(status, 200, draft)
        status, revised = post(
            self.port, "/api/project/scope",
            {"expected_revision": 1,
             "features": [feature(summary="Users can inspect project health.")]},
        )
        self.assertEqual(status, 200, revised)

        status, out = post(self.port, "/api/project/approve",
                           {"expected_revision": 1})
        self.assertEqual(status, 409, out)
        self.assertIn("current revision is 2", out["error"])


if __name__ == "__main__":
    unittest.main()
