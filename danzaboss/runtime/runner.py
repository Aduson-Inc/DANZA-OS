"""DANZA runner — ties the brain together for a real-app trial.

In the Claude Code-native model, the *agents* write code; this runner provides the
brain the agents/hooks call: learn the app, plan verifiable tasks, and verify with
real tests. It does NOT itself call an LLM (that's the headless SDK path, later).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..cortex.app_profile import AppProfile
from ..cortex.sqlite_backend import SqliteBackend
from ..cortex.store import ObservationStore
from ..hooks.dispatcher import HookDispatcher
from ..security.capabilities import CapabilityRegistry
from .scan import profile_repo
from .verify import run_verification, VerifyResult


@dataclass
class DanzaSession:
    """A bound working session over a real target app."""
    project: str
    target_dir: str
    memory_path: str
    audit_path: str
    profile: Optional[AppProfile] = None

    def learn(self, *, domain: str = "", goals: list[str] | None = None,
              big: set[str] | None = None) -> AppProfile:
        self.profile = profile_repo(self.project, self.target_dir, domain=domain,
                                    goals=goals, big_feature_names=big)
        return self.profile

    def store(self) -> ObservationStore:
        return ObservationStore(SqliteBackend(self.memory_path))

    def dispatcher(self, current_boss: str, approved_task_ids: set[str]) -> HookDispatcher:
        return HookDispatcher(CapabilityRegistry(self.audit_path),
                              current_boss=current_boss,
                              approved_task_ids=approved_task_ids)

    def verify(self, test_command: str) -> VerifyResult:
        return run_verification(test_command, self.target_dir)
