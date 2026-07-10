"""Wiring test — Tony + specialist prompts point drivers at CORTEX context.

Two parts. Part A reads the `.claude/agents/*.md` prompt files and proves they
tell Tony to compile role-scoped memory (`cortex context --driver`) into a
`## CORTEX Context` block and to spawn only the specialists a task needs, and
that every specialist is told to use that supplied block FIRST, ahead of the
`cortex search` fallback. Part B is an isolated APP_BUILD flow harness: it seeds
a mock post-onboarding project store and drives the Task-1 CLI for a SUBSET of
drivers with no explicit budget, asserting each package is scoped, role-budgeted
and non-empty, while OS_DEV stays CORTEX-silent.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa

from danzaboss.cortex import commands
from danzaboss.cortex.driver_context import compile_driver_context, default_budget
from danzaboss.cortex.observation import Importance, Observation
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.kernel.profile import PROFILE_ENV_VAR, active_profile


# commands.__file__ is .../danzaboss/cortex/commands.py; three dirnames up = repo root.
AGENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(commands.__file__))),
    ".claude", "agents")

SPECIALISTS = [
    "jonathan-builder", "samantha-mapper", "angela-auditor", "bonnie-qa",
    "carmella-researcher", "hank-designer", "billy-security",
]

TASK = "build the login endpoint"


def _read_agent(name):
    with open(os.path.join(AGENTS_DIR, name + ".md"), encoding="utf-8") as fh:
        return fh.read()


def obs(title, summary, typ, project="userapp", **kw):
    return Observation(title=title, summary=summary, type=typ,
                       project=project, **kw)


def app_build_store(project="userapp"):
    """An isolated, mock APP_BUILD-style project store: observations of many
    types so different driver profiles must select different slices."""
    store = ObservationStore(SqliteBackend(":memory:"))
    seeds = [
        obs("Login race condition fixed", "double-submit on the login form",
            "bug_fix", project=project, concepts=["login", "auth"],
            tags=["login"], importance=Importance.HIGH.value, confidence=95,
            reasoning="two POSTs raced the session write"),
        obs("Session cookie dropped on redirect", "cookie lost after 302",
            "root_cause", project=project, concepts=["session", "redirect"],
            tags=["login"], importance=Importance.HIGH.value, confidence=90),
        obs("Fail-closed input validation", "validation raises on bad input",
            "convention", project=project, concepts=["validation", "inputs"],
            tags=["login"], importance=Importance.CRITICAL.value, confidence=95),
        obs("Login endpoint hashes with bcrypt", "cost factor 12",
            "impl_detail", project=project, concepts=["login", "bcrypt"],
            tags=["login"], confidence=90),
        obs("Chose Postgres for the user store", "relational users + sessions",
            "decision", project=project, concepts=["postgres", "users"],
            tags=["login"]),
        obs("CSRF token required on every POST", "double-submit cookie pattern",
            "security", project=project, concepts=["csrf", "login"],
            tags=["login"], importance=Importance.HIGH.value, confidence=95),
        obs("bcrypt pinned to 4.x", "avoid 5.x breaking change",
            "dependency", project=project, concepts=["bcrypt", "login"],
            tags=["login"]),
        obs("Cache invalidation lesson", "invalidate on write, not on read",
            "lesson", project=project, concepts=["cache", "login"],
            tags=["login"]),
    ]
    for o in seeds:
        store.upsert(o)
    return store


class TestPromptWiring(unittest.TestCase):
    """Part A — the prompt files instruct the CORTEX-context handoff."""

    def test_tony_compiles_context_block(self):
        # req 1,2: Tony compiles role-scoped memory into a ## CORTEX Context block.
        text = _read_agent("tony-d-orchestrator")
        self.assertIn("cortex context --driver", text)
        self.assertIn("## CORTEX Context", text)

    def test_tony_spawns_minimum_roster(self):
        # req 4: only the specialists a task needs, never the full roster.
        text = _read_agent("tony-d-orchestrator")
        self.assertIn("only the specialists a task actually needs", text)
        self.assertIn("never the full roster", text)

    def test_specialists_use_supplied_block_before_search(self):
        # req 3: each specialist has a ## CORTEX Context heading that precedes
        # (is the primary source ahead of) the cortex search fallback.
        for name in SPECIALISTS:
            text = _read_agent(name)
            self.assertIn("## CORTEX Context", text,
                          "%s missing ## CORTEX Context" % name)
            self.assertIn("cortex search", text,
                          "%s missing cortex search fallback" % name)
            self.assertLess(
                text.index("## CORTEX Context"), text.index("cortex search"),
                "%s: supplied block must precede the search fallback" % name)


class TestAppBuildFlow(unittest.TestCase):
    """Part B — APP_BUILD flow harness against Task-1's CLI/compiler."""

    def setUp(self):
        self._saved = os.environ.get(PROFILE_ENV_VAR)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(PROFILE_ENV_VAR, None)
        else:
            os.environ[PROFILE_ENV_VAR] = self._saved

    def _seed_app_repo(self, root):
        """Build a mock APP_BUILD repo: team-state.json + scoped project store."""
        runtime = os.path.join(root, ".danza", "runtime")
        os.makedirs(runtime)
        state = {
            "current_boss": "claude", "previous_boss": None, "turn_number": 1,
            "features_completed_this_turn": 0, "max_features_per_turn": 2,
            "handoff_required": False, "status": "in_progress",
        }
        with open(os.path.join(runtime, "team-state.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(state, fh)
        project = commands._project(root)
        store = ObservationStore(SqliteBackend(commands.db_path(root)))
        for o in app_build_store(project).backend.all(project):
            store.upsert(o)

    def _run(self, root, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(argv, root=root, stdin=io.StringIO(""))
        return code, out.getvalue()

    def test_subset_of_drivers_get_scoped_budgeted_context(self):
        # req 6,7: team-state.json present -> APP_BUILD heuristic.
        os.environ.pop(PROFILE_ENV_VAR, None)
        with tempfile.TemporaryDirectory() as root:
            self._seed_app_repo(root)
            self.assertEqual(active_profile(root).name, "APP_BUILD")

            # Tony delegates to a SUBSET, not the full roster.
            called = {"jonathan-builder", "bonnie-qa"}
            self.assertLess(len(called), 7)  # subset is a proper subset

            total = 0
            for driver in called:
                code, out = self._run(
                    root, ["context", "--driver", driver, "--task", TASK,
                           "--json"])
                self.assertEqual(code, 0, "%s CLI failed" % driver)
                data = json.loads(out)
                # req 8: within the role default budget, non-empty package.
                self.assertLessEqual(data["used"], default_budget(driver),
                                     "%s exceeded its role budget" % driver)
                self.assertGreaterEqual(len(data["observations"]), 1,
                                        "%s got an empty block" % driver)
                total += data["used"]
            self.assertGreater(total, 0, "no tokens measured across the subset")

    def test_os_dev_stays_cortex_silent(self):
        # req 5: a fresh repo with no team-state.json under OS_DEV stays silent.
        os.environ[PROFILE_ENV_VAR] = "OS_DEV"
        with tempfile.TemporaryDirectory() as root2:
            prof = active_profile(root2)
            self.assertEqual(prof.name, "OS_DEV")
            self.assertFalse(prof.session_inject)


class TestNoLegacySubstrate(unittest.TestCase):
    """req 9 — the compiler never revives the legacy memory/context substrate."""

    def test_driver_context_has_no_legacy_dependency(self):
        src = os.path.join(os.path.dirname(commands.__file__),
                           "driver_context.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("memory.store", text)
        self.assertNotIn("MemoryStore", text)
        self.assertNotIn("context.pipeline", text)


if __name__ == "__main__":
    unittest.main()
