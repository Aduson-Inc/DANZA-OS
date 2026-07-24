"""CORTEX-native driver context compiler — C-driver front-door.

Proves a thin, budget-capped, role-specific CORTEX package can be compiled for
any driver WITHOUT reviving the legacy context/pipeline.py + memory/store.py
substrate. The compiler is an explicit on-demand front-door (like
`danza cortex retrieve`), so it is profile-agnostic and never makes OS_DEV hot.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import _bootstrap  # noqa

from danzaboss.cortex import commands, driver_context
from danzaboss.cortex.driver_context import (
    DRIVER_CORTEX, DriverContext, compile_driver_context, default_budget)
from danzaboss.cortex.observation import Importance, Observation
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.kernel.profile import PROFILE_ENV_VAR, active_profile


def obs(title, summary, typ, project="userapp", **kw):
    return Observation(title=title, summary=summary, type=typ,
                       project=project, **kw)


def app_build_store(project="userapp"):
    """An isolated, mock APP_BUILD-style project store: observations of many
    types so different driver profiles must select different slices."""
    store = ObservationStore(SqliteBackend(":memory:"))
    seeds = [
        obs("Login race condition fixed", "double-submit on the login form",
            "bug_fix", concepts=["login", "auth"], tags=["login"],
            importance=Importance.HIGH.value, confidence=95,
            reasoning="two POSTs raced the session write"),
        obs("Session cookie dropped on redirect", "cookie lost after 302",
            "root_cause", concepts=["session", "redirect"], tags=["login"],
            importance=Importance.HIGH.value, confidence=90),
        obs("Fail-closed input validation", "validation raises on bad input",
            "convention", concepts=["validation", "inputs"], tags=["login"],
            importance=Importance.CRITICAL.value, confidence=95),
        obs("Login endpoint hashes with bcrypt", "cost factor 12",
            "impl_detail", concepts=["login", "bcrypt"], tags=["login"],
            confidence=90),
        obs("Chose Postgres for the user store", "relational users + sessions",
            "decision", concepts=["postgres", "users"], tags=["login"]),
        obs("CSRF token required on every POST", "double-submit cookie pattern",
            "security", concepts=["csrf", "login"], tags=["login"],
            importance=Importance.HIGH.value, confidence=95),
        obs("bcrypt pinned to 4.x", "avoid 5.x breaking change",
            "dependency", concepts=["bcrypt", "login"], tags=["login"]),
        obs("Cache invalidation lesson", "invalidate on write, not on read",
            "lesson", concepts=["cache", "login"], tags=["login"]),
    ]
    for o in seeds:
        store.upsert(o)
    return store


TASK = "build the login endpoint"


class TestCompileDriverContextCore(unittest.TestCase):
    def test_function_is_cortex_native_and_callable(self):
        # requirement 1: exists, callable, CORTEX-native (no legacy substrate).
        self.assertTrue(callable(compile_driver_context))
        self.assertFalse(hasattr(driver_context, "MemoryStore"),
                         "compiler must not pull in the legacy MemoryStore")

    def test_accepts_store_driver_task_project_budget(self):
        # requirement 2: the documented signature.
        ctx = compile_driver_context(
            store=app_build_store(), driver="jonathan-builder",
            task=TASK, project="userapp", budget=800)
        self.assertIsInstance(ctx, DriverContext)
        self.assertEqual(ctx.driver, "jonathan-builder")
        self.assertEqual(ctx.project, "userapp")
        self.assertEqual(ctx.budget, 800)

    def test_applies_the_correct_driver_profile(self):
        # requirement 3: the driver's forced intent + type filter are honoured.
        ctx = compile_driver_context(app_build_store(), "bonnie-qa", TASK,
                                     "userapp", budget=800)
        self.assertEqual(ctx.intent, DRIVER_CORTEX["bonnie-qa"]["intent"])
        allowed = set(DRIVER_CORTEX["bonnie-qa"]["types"])
        self.assertTrue(ctx.package.items, "bonnie should see her slice")
        for item in ctx.package.items:
            self.assertIn(item.observation.type, allowed)

    def test_context_stays_within_requested_budget(self):
        # requirement 4: the package never exceeds the requested budget.
        for budget in (120, 400, 900):
            ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                         TASK, "userapp", budget=budget)
            self.assertLessEqual(ctx.used, budget)
            self.assertLessEqual(ctx.package.used, budget)
            self.assertEqual(ctx.used, ctx.package.used)

    def test_tighter_budget_never_grows_the_package(self):
        # requirement 4 (cap actually trims): smaller budget <= larger budget.
        small = compile_driver_context(app_build_store(), "jonathan-builder",
                                       TASK, "userapp", budget=120)
        large = compile_driver_context(app_build_store(), "jonathan-builder",
                                       TASK, "userapp", budget=900)
        self.assertLessEqual(small.used, large.used)

    def test_different_drivers_get_different_context_profiles(self):
        # requirement 5: role-specific, meaningfully different slices.
        bonnie = compile_driver_context(app_build_store(), "bonnie-qa", TASK,
                                        "userapp", budget=800)
        billy = compile_driver_context(app_build_store(), "billy-security", TASK,
                                       "userapp", budget=800)
        self.assertNotEqual(bonnie.intent, billy.intent)
        bonnie_types = {i.observation.type for i in bonnie.package.items}
        billy_types = {i.observation.type for i in billy.package.items}
        self.assertNotEqual(bonnie_types, billy_types)
        # QA never gets the raw security observation; Security does.
        billy_ids = {i.observation.id for i in billy.package.items}
        bonnie_ids = {i.observation.id for i in bonnie.package.items}
        self.assertNotEqual(billy_ids, bonnie_ids)

    def test_unknown_driver_falls_back_safely(self):
        # requirement 6: predictable fallback, no crash.
        ctx = compile_driver_context(app_build_store(), "ghostbuster-9000",
                                     TASK, "userapp", budget=800)
        self.assertIsInstance(ctx, DriverContext)
        self.assertEqual(ctx.profile_source, "fallback")
        # fallback forces no intent -> the detected intent stands.
        self.assertEqual(ctx.intent, "write_code")

    def test_known_driver_is_tagged_as_driver_map(self):
        ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=800)
        self.assertEqual(ctx.profile_source, "driver_map")

    def test_render_names_the_driver(self):
        ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=800)
        rendered = ctx.render()
        self.assertIn("jonathan-builder", rendered)

    def test_every_driver_profile_uses_known_intents_and_types(self):
        # salvaged from the retired legacy context/pipeline.py DRIVER_CORTEX
        # invariant test: every live driver profile must still name a real
        # intent and only real observation types.
        from danzaboss.cortex.intent import INTENTS
        from danzaboss.cortex.observation import ObsType
        valid_types = {t.value for t in ObsType}
        for driver, prof in DRIVER_CORTEX.items():
            self.assertIn(prof["intent"], INTENTS, driver)
            if prof["types"] is not None:
                self.assertTrue(set(prof["types"]) <= valid_types, driver)


class TestNoLegacySubstrate(unittest.TestCase):
    def test_module_never_imports_memory_store(self):
        # requirement 10: no MemoryStore dependency is introduced.
        src = os.path.join(os.path.dirname(commands.__file__),
                           "driver_context.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("memory.store", text)
        self.assertNotIn("MemoryStore", text)
        self.assertNotIn("context.pipeline", text)
        # and it DOES ride the real CORTEX engine.
        self.assertIn("quality", text)


class TestProfileInvariants(unittest.TestCase):
    """OS_DEV stays CORTEX-silent (requirement 8); APP_BUILD is the intended
    target (requirement 9); the compiler itself is profile-agnostic."""

    def setUp(self):
        self._saved = os.environ.get(PROFILE_ENV_VAR)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(PROFILE_ENV_VAR, None)
        else:
            os.environ[PROFILE_ENV_VAR] = self._saved

    def test_os_dev_stays_cortex_silent(self):
        os.environ[PROFILE_ENV_VAR] = "OS_DEV"
        prof = active_profile(".")
        self.assertFalse(prof.session_inject)
        self.assertFalse(prof.distill_gate_active)

    def test_app_build_is_cortex_hot(self):
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"
        prof = active_profile(".")
        self.assertTrue(prof.session_inject)
        self.assertTrue(prof.distill_gate_active)

    def test_compiler_is_profile_agnostic(self):
        # same store + driver + task -> identical selection regardless of the
        # active profile: an explicit call can never make OS_DEV "hot".
        os.environ[PROFILE_ENV_VAR] = "OS_DEV"
        dev = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=800)
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"
        app = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=800)
        self.assertEqual([i.observation.id for i in dev.package.items],
                         [i.observation.id for i in app.package.items])


class TestDefaultBudgets(unittest.TestCase):
    """Per-driver default context token budgets — the role default resolved
    when the caller/CLI passes no explicit budget."""

    def test_default_budget_jonathan_builder(self):
        self.assertEqual(default_budget("jonathan-builder"), 2400)

    def test_default_budget_bonnie_qa(self):
        self.assertEqual(default_budget("bonnie-qa"), 2000)

    def test_default_budget_unknown_driver_falls_back_to_generic_cap(self):
        self.assertEqual(default_budget("nobody"), 2400)

    def test_compile_driver_context_no_budget_resolves_role_default_jonathan(self):
        ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp")
        self.assertEqual(ctx.budget, 2400)
        self.assertLessEqual(ctx.used, 2400)
        self.assertEqual(ctx.adaptation["selected_mode"], "base")
        self.assertEqual(ctx.adaptation["initial_budget"], 2400)
        self.assertEqual(ctx.adaptation["selected_budget"], 2400)
        self.assertTrue(ctx.adaptation["expansion_considered"])

    def test_compile_driver_context_no_budget_resolves_role_default_bonnie(self):
        ctx = compile_driver_context(app_build_store(), "bonnie-qa",
                                     TASK, "userapp")
        self.assertEqual(ctx.budget, 2000)
        self.assertLessEqual(ctx.used, 2000)

    def test_explicit_budget_is_exact_and_bypasses_adaptation(self):
        with patch("danzaboss.cortex.driver_context.select_adaptive_package") \
                as adaptive:
            ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                         TASK, "userapp", budget=600)
        adaptive.assert_not_called()
        evidence = ctx.adaptation
        self.assertEqual(ctx.budget, 600)
        self.assertEqual(evidence["requested_budget"], 600)
        self.assertEqual(evidence["initial_budget"], 600)
        self.assertEqual(evidence["selected_budget"], 600)
        self.assertEqual(evidence["selected_mode"], "explicit")
        self.assertFalse(evidence["expansion_considered"])
        self.assertFalse(evidence["expansion_attempted"])
        self.assertEqual(evidence["acceptance_reason"],
                         "explicit_budget_bypass")

    def test_empty_store_stays_at_base_without_expansion(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        ctx = compile_driver_context(store, "jonathan-builder", TASK, "userapp")
        self.assertEqual(ctx.used, 0)
        self.assertEqual(ctx.budget, 2400)
        self.assertFalse(ctx.adaptation["expansion_qualified"])
        self.assertFalse(ctx.adaptation["expansion_attempted"])

    def test_quality_retry_does_not_duplicate_adaptive_base_build(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        with patch("danzaboss.cortex.driver_context.build_package",
                   wraps=driver_context.build_package) as build:
            ctx = compile_driver_context(
                store, "jonathan-builder", TASK, "userapp")
        self.assertEqual(build.call_count, 1)
        self.assertTrue(ctx.adaptation["expansion_considered"])


class TestDriverContextCLI(unittest.TestCase):
    """requirement 7: `danza cortex context --driver <id> --task <t> --budget N`.
    Runs under APP_BUILD (requirement 9) against an isolated project DB."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._saved = os.environ.get(PROFILE_ENV_VAR)
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"
        # seed the scoped project store the CLI will read (identity resolves
        # the project name from the repo root, so query with that name).
        project = commands._project(self.root)
        store = ObservationStore(SqliteBackend(commands.db_path(self.root)))
        for o in app_build_store(project).backend.all(project):
            store.upsert(o)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(PROFILE_ENV_VAR, None)
        else:
            os.environ[PROFILE_ENV_VAR] = self._saved
        self.tmp.cleanup()

    def _run(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(argv, root=self.root, stdin=io.StringIO(""))
        return code, out.getvalue()

    def test_cli_json_reports_budget_and_driver(self):
        code, out = self._run(["context", "--driver", "jonathan-builder",
                               "--task", TASK, "--budget", "600", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["driver"], "jonathan-builder")
        self.assertEqual(data["budget"], 600)
        self.assertLessEqual(data["used"], 600)
        self.assertEqual(data["profile_source"], "driver_map")
        self.assertEqual(data["adaptation"]["selected_mode"], "explicit")
        self.assertEqual(data["adaptation"]["selected_budget"], 600)

    def test_cli_default_renders_text_block(self):
        code, out = self._run(["context", "--driver", "bonnie-qa",
                               "--task", TASK, "--budget", "600"])
        self.assertEqual(code, 0)
        self.assertIn("bonnie-qa", out)

    def test_cli_requires_task_with_driver(self):
        code, _ = self._run(["context", "--driver", "jonathan-builder"])
        self.assertEqual(code, 2)

    def test_bare_context_command_still_works(self):
        # additive: the legacy `danza cortex context` (no --driver) is unchanged.
        code, out = self._run(["context"])
        self.assertEqual(code, 0)

    def test_cli_no_budget_resolves_role_default(self):
        code, out = self._run(["context", "--driver", "bonnie-qa",
                               "--task", TASK, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["budget"], 2000)
        self.assertLessEqual(data["used"], 2000)
        self.assertIn(data["adaptation"]["selected_mode"], ("base", "expanded"))
        self.assertEqual(data["adaptation"]["policy_base"], 2000)
        self.assertEqual(data["adaptation"]["policy_ceiling"], 3500)


class TestReplacedTokensForSavingsMeter(unittest.TestCase):
    """P4.1 T9: the savings meter's 'replaced' figure — the estimated cost
    of pulling each injected observation in full, one at a time, the way a
    boss without a compiled brief would have to (`danza cortex get <id>`).
    Computed with the same calibrated estimator as every other CORTEX token
    accounting call site — never a fixed multiplier, never fabricated."""

    def test_replaced_tokens_is_zero_for_empty_package(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        ctx = compile_driver_context(store, "jonathan-builder", TASK, "userapp")
        self.assertEqual(driver_context.replaced_tokens(ctx), 0)

    def test_replaced_tokens_sums_full_raw_observation_size(self):
        from danzaboss.cortex.tokens import est_tokens

        ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=800)
        self.assertTrue(ctx.package.items, "fixture must inject something")
        expected = sum(
            est_tokens(json.dumps(item.observation.to_row(), sort_keys=True),
                      kind="json")
            for item in ctx.package.items)
        self.assertEqual(driver_context.replaced_tokens(ctx), expected)

    def test_replaced_tokens_never_cheaper_than_the_injected_package(self):
        # the raw observation (every bookkeeping field, serialized) can
        # never be smaller than the condensed/possibly-compressed text that
        # was actually injected for the same observation.
        ctx = compile_driver_context(app_build_store(), "jonathan-builder",
                                     TASK, "userapp", budget=200)
        self.assertGreaterEqual(driver_context.replaced_tokens(ctx), ctx.used)


if __name__ == "__main__":
    unittest.main()
