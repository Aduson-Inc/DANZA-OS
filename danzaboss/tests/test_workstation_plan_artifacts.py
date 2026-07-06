"""W1-P3 plan artifacts: .danza/plan.json + plan.md, atomic writes;
SPEC_RELPATH shared constant (P1 final-review deferred item)."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import compiler
from danzaboss.workstation.planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH,
                                           order_tasks, parse_plan,
                                           plan_payload, render_plan_md,
                                           write_plan)

PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 25, "writes": ["src/log.py"], "flags": ["auth"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}},
        {"id": "1.2", "description": "weekly summary", "kind": "backend",
         "size_est": 20, "writes": ["src/summary.py"],
         "depends_on": ["1.1"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_summary.py"}}]}]}


class PlanPayload(unittest.TestCase):
    def test_whitelist_drops_junk_keys(self):
        raw = json.loads(json.dumps(PLAN))
        raw["evil"] = "ignored"
        raw["tasks"][0]["notes"] = "ignored"
        raw["tasks"][0]["subtasks"][0]["cost_usd"] = 999
        tasks = parse_plan(raw)
        payload = plan_payload(".danza/spec.md", tasks, order_tasks(tasks))
        self.assertEqual(set(payload), {"spec_ref", "tasks", "order"})
        section = payload["tasks"][0]
        self.assertEqual(set(section), {"id", "description", "subtasks"})
        leaf = section["subtasks"][0]
        self.assertNotIn("cost_usd", leaf)
        self.assertEqual(leaf["verification"],
                         {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"})

    def test_payload_round_trips_through_parse(self):
        tasks = parse_plan(PLAN)
        payload = plan_payload(".danza/spec.md", tasks, order_tasks(tasks))
        self.assertEqual(parse_plan(payload), tasks)

    def test_empty_optionals_omitted(self):
        tasks = parse_plan(PLAN)
        payload = plan_payload(".danza/spec.md", tasks, order_tasks(tasks))
        first_leaf = payload["tasks"][0]["subtasks"][0]  # 1.1: no depends_on
        self.assertNotIn("depends_on", first_leaf)
        self.assertIn("flags", first_leaf)  # 1.1 carries ["auth"]


class RenderPlanMd(unittest.TestCase):
    def setUp(self):
        self.ordered = order_tasks(parse_plan(PLAN))
        self.text = render_plan_md(PLAN["spec_ref"], self.ordered)

    def test_numbered_in_execution_order(self):
        self.assertIn("1. **1.1**", self.text)
        self.assertIn("2. **1.2**", self.text)

    def test_verification_rendered(self):
        self.assertIn("verify [automated_test]: pytest tests/test_log.py",
                      self.text)

    def test_hard_stop_flag_called_out(self):
        self.assertIn("HARD STOP", self.text)

    def test_dependency_rendered(self):
        self.assertIn("after: 1.1", self.text)


class WritePlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        tasks = parse_plan(PLAN)
        self.ordered = order_tasks(tasks)
        self.payload = plan_payload(PLAN["spec_ref"], tasks, self.ordered)

    def test_writes_both_artifacts(self):
        json_path, md_path = write_plan(self.root, self.payload, self.ordered)
        self.assertEqual(json_path, self.root / PLAN_JSON_RELPATH)
        self.assertEqual(md_path, self.root / PLAN_MD_RELPATH)
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())

    def test_plan_json_carries_execution_order(self):
        json_path, _ = write_plan(self.root, self.payload, self.ordered)
        on_disk = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["order"], ["1.1", "1.2"])
        self.assertEqual(on_disk["spec_ref"], PLAN["spec_ref"])

    def test_no_tmp_files_left(self):
        write_plan(self.root, self.payload, self.ordered)
        self.assertEqual(list((self.root / ".danza").glob("*.tmp")), [])

    def test_rewrite_overwrites_clean(self):
        write_plan(self.root, self.payload, self.ordered)
        json_path, _ = write_plan(self.root, self.payload, self.ordered)
        on_disk = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["order"], ["1.1", "1.2"])


class SpecRelpath(unittest.TestCase):
    def test_write_spec_uses_shared_constant(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = compiler.write_spec(tmp, "# Spec — X\n")
            self.assertEqual(path, Path(tmp) / compiler.SPEC_RELPATH)


if __name__ == "__main__":
    unittest.main()
