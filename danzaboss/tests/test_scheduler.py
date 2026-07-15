import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from danzaboss.kernel.state import StateManager
from danzaboss.kernel.scheduler import Scheduler, StepOutcome, Decision


def make_mgr(mode):
    d = tempfile.mkdtemp()
    mgr = StateManager(os.path.join(d, "team-state.json"))
    mgr.init(mode=mode, current_boss="claude")
    return mgr


class TestScheduler(unittest.TestCase):
    def test_continuous_builds_until_done(self):
        mgr = make_mgr("continuous")
        sched = Scheduler(mgr)
        # executor: build then verify each unit
        state_flip = {"built": False, "unit": 0}

        def executor(state, remaining):
            if not state_flip["built"]:
                state_flip["built"] = True
                return StepOutcome(built=True, verified=False)
            state_flip["built"] = False
            state_flip["unit"] += 1
            return StepOutcome(built=True, verified=True,
                               unit_id=f"unit-{state_flip['unit']}")

        result = sched.run(tasks_remaining=3, executor=executor, actor="claude")
        self.assertEqual(result["decision"], Decision.STOP_DONE.value)
        self.assertEqual(result["features_completed"], 3)

    def test_relay_hands_off_at_cap(self):
        mgr = make_mgr("relay")  # cap = 2
        sched = Scheduler(mgr)
        flip = {"b": False, "unit": 0}

        def executor(state, remaining):
            if not flip["b"]:
                flip["b"] = True
                return StepOutcome(built=True, verified=False)
            flip["b"] = False
            flip["unit"] += 1
            return StepOutcome(built=True, verified=True,
                               unit_id=f"unit-{flip['unit']}")

        result = sched.run(tasks_remaining=10, executor=executor,
                           actor="claude", next_boss="codex")
        self.assertEqual(result["decision"], Decision.HANDOFF.value)
        self.assertEqual(result["features_completed"], 2)  # stopped at cap
        self.assertEqual(result["next_boss"], "codex")
        self.assertEqual(mgr.load().verified_unit_ids_this_turn, [])

    def test_blocker_stops_and_escalates(self):
        mgr = make_mgr("continuous")
        sched = Scheduler(mgr)

        def executor(state, remaining):
            return StepOutcome(blocked=True, blocker_reason="needs API key")

        result = sched.run(tasks_remaining=5, executor=executor, actor="claude")
        self.assertEqual(result["decision"], Decision.STOP_BLOCKED.value)
        self.assertIn("API key", result["reason"])

    def test_decide_is_deterministic(self):
        mgr = make_mgr("relay")
        sched = Scheduler(mgr)
        state = mgr.load()
        d1 = sched.decide(state, tasks_remaining=5, last=None)
        d2 = sched.decide(state, tasks_remaining=5, last=None)
        self.assertEqual(d1, d2)

    def test_max_steps_safety_valve(self):
        mgr = make_mgr("continuous")
        sched = Scheduler(mgr, max_steps=3)
        # executor that never verifies -> would loop forever without the valve
        def executor(state, remaining):
            return StepOutcome(built=True, verified=False)
        result = sched.run(tasks_remaining=5, executor=executor, actor="claude")
        self.assertEqual(result["decision"], Decision.STOP_BLOCKED.value)
        self.assertIn("loop", result["reason"].lower())

    def test_verified_outcome_requires_concrete_unit_id(self):
        mgr = make_mgr("continuous")
        sched = Scheduler(mgr)
        built = {"value": False}

        def executor(state, remaining):
            if not built["value"]:
                built["value"] = True
                return StepOutcome(built=True, verified=False)
            return StepOutcome(built=True, verified=True)

        with self.assertRaisesRegex(Exception, "unit_id"):
            sched.run(tasks_remaining=1, executor=executor, actor="claude")


if __name__ == "__main__":
    unittest.main()
