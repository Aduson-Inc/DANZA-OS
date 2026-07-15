"""Cold-start self-test harness — DANZABOSS Upgrade #6.

The Phase-1 review found the OS has never run end-to-end and has no self-tests.
This harness validates the framework *itself*: state-file schema integrity and a
simulated New-Project -> build -> handoff -> Continue cycle. It is the regression
net every future upgrade round runs before promotion.

Returns a structured report (list of checks with pass/fail) — never raises, so it
can be run as a health gate in CI.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

from danzaboss.kernel.state import StateManager, StateError
from danzaboss.kernel.scheduler import Scheduler, StepOutcome, Decision
from danzaboss.planning.decompose import Task, Verification, VerificationKind, assert_dispatchable, DispatchError
from danzaboss.security.capabilities import CapabilityRegistry, Capability, CapabilityError


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {"ok": self.ok,
                "passed": sum(c.passed for c in self.checks),
                "total": len(self.checks),
                "checks": [c.__dict__ for c in self.checks]}


def run_cold_start() -> Report:
    r = Report()
    workdir = tempfile.mkdtemp(prefix="danza_selftest_")

    # 1. state init + schema integrity
    try:
        mgr = StateManager(os.path.join(workdir, "team-state.json"))
        s = mgr.init(mode="relay", current_boss="claude", goal="selftest app")
        s.validate()
        r.add("state_init_and_schema", True, "team-state initialised and valid")
    except StateError as e:
        r.add("state_init_and_schema", False, str(e))
        return r  # nothing else can run

    # 2. turn lock actually locks
    try:
        mgr.transition(actor="intruder", to_status="in_progress")
        r.add("turn_lock_enforced", False, "intruder was allowed to mutate state")
    except StateError:
        r.add("turn_lock_enforced", True, "wrong actor rejected")

    # 3. verifiable-decomposition gate rejects unverifiable work
    bad = Task(id="t-bad", description="make it nice")  # no verification
    try:
        assert_dispatchable(bad)
        r.add("unverifiable_task_blocked", False, "unverifiable task passed the gate")
    except DispatchError:
        r.add("unverifiable_task_blocked", True, "unverifiable task correctly blocked")

    good = Task(id="t-ok", description="add login",
                verification=Verification(VerificationKind.AUTOMATED_TEST, "pytest test_login.py"))
    r.add("verifiable_task_dispatchable", good.ready_for_dispatch(),
          "verifiable task is dispatchable")

    # 4. capability enforcement: builder cannot touch auth without elevation
    reg = CapabilityRegistry(os.path.join(workdir, "audit.jsonl"))
    try:
        reg.check("jonathan-builder", Capability.TOUCH_AUTH)
        r.add("hard_stop_enforced", False, "auth touched without elevation")
    except CapabilityError:
        r.add("hard_stop_enforced", True, "auth hard-stop enforced")

    # elevation path works and is single-use
    tok = reg.mint_elevation(Capability.TOUCH_AUTH, "jonathan-builder", "add login (user approved)")
    try:
        reg.check("jonathan-builder", Capability.TOUCH_AUTH, elevation=tok)
        reg.check("jonathan-builder", Capability.TOUCH_AUTH, elevation=tok)  # reuse must fail
        r.add("elevation_single_use", False, "elevation token was reusable")
    except CapabilityError:
        r.add("elevation_single_use", True, "elevation token correctly single-use")

    # 5. simulated build cycle: relay hands off at cap
    try:
        mgr.transition(actor="claude", to_status="in_progress")
        sched = Scheduler(mgr)
        flip = {"b": False, "unit": 0}

        def executor(state, remaining):
            if not flip["b"]:
                flip["b"] = True
                return StepOutcome(built=True, verified=False)
            flip["b"] = False
            flip["unit"] += 1
            return StepOutcome(built=True, verified=True,
                               unit_id=f"selftest-{flip['unit']}")

        result = sched.run(tasks_remaining=10, executor=executor,
                           actor="claude", next_boss="codex")
        ok = (result["decision"] == Decision.HANDOFF.value
              and result["features_completed"] == 2)
        r.add("relay_cycle_hands_off", ok, str(result))
    except Exception as e:
        r.add("relay_cycle_hands_off", False, f"{type(e).__name__}: {e}")

    # 6. continue-mode resume: new boss owns state after handoff
    try:
        s = mgr.load()
        cont_ok = (s.current_boss == "codex" and s.previous_boss == "claude"
                   and s.turn_number == 1)
        r.add("continue_mode_ownership", cont_ok,
              f"boss={s.current_boss} turn={s.turn_number}")
    except StateError as e:
        r.add("continue_mode_ownership", False, str(e))

    return r


if __name__ == "__main__":
    import json
    rep = run_cold_start()
    print(json.dumps(rep.to_dict(), indent=2))
