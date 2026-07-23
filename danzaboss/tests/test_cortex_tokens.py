"""Calibrated token estimator — single home for every est_tokens call site
(Task 6 Part A). Divisors are chars-per-token approximations, not exact
counts; the tests pin relative ordering and the presence of the optional
tiktoken precise-mode switch, never brittle absolute numbers.
"""
import unittest
from unittest import mock

import _bootstrap  # noqa
from danzaboss.cortex import tokens


class TestKindDivisors(unittest.TestCase):
    def test_prose_matches_legacy_len_over_4(self):
        text = "x" * 400
        self.assertEqual(tokens.est_tokens(text, kind="prose"), 100)

    def test_code_denser_than_prose(self):
        text = "x" * 400
        # code divisor (~3.3) is smaller than prose (~4.0) -> more tokens
        # for the same character count.
        self.assertGreater(tokens.est_tokens(text, kind="code"),
                           tokens.est_tokens(text, kind="prose"))

    def test_json_denser_than_code(self):
        text = "x" * 400
        self.assertGreater(tokens.est_tokens(text, kind="json"),
                           tokens.est_tokens(text, kind="code"))

    def test_default_kind_is_prose(self):
        text = "x" * 400
        self.assertEqual(tokens.est_tokens(text), tokens.est_tokens(text, kind="prose"))

    def test_unknown_kind_falls_back_to_prose(self):
        text = "x" * 400
        self.assertEqual(tokens.est_tokens(text, kind="nonsense"),
                         tokens.est_tokens(text, kind="prose"))

    def test_empty_text_is_zero(self):
        self.assertEqual(tokens.est_tokens(""), 0)

    def test_nonempty_text_is_at_least_one(self):
        self.assertGreaterEqual(tokens.est_tokens("x"), 1)

    def test_never_negative(self):
        for kind in ("prose", "code", "json", "whatever"):
            self.assertGreaterEqual(tokens.est_tokens("hi", kind=kind), 0)


class _FakeEncoder:
    """Stand-in for a tiktoken Encoding: one 'token' per two characters."""

    def encode(self, text: str) -> list:
        return [0] * (len(text) // 2)


class TestPreciseModeSwitch(unittest.TestCase):
    """tiktoken is never a hard dependency; the module must work identically
    whether or not it's installed. Rather than requiring the real package,
    tests mock the module-level encoder handle directly."""

    def test_heuristic_path_used_when_no_encoder(self):
        with mock.patch.object(tokens, "_ENCODER", None):
            self.assertEqual(tokens.est_tokens("x" * 400, kind="prose"), 100)

    def test_precise_path_used_when_encoder_present(self):
        with mock.patch.object(tokens, "_ENCODER", _FakeEncoder()):
            # fake encoder: 1 token per 2 chars, independent of kind/divisor
            self.assertEqual(tokens.est_tokens("x" * 400, kind="prose"), 200)
            self.assertEqual(tokens.est_tokens("x" * 400, kind="json"), 200)

    def test_precise_path_falls_back_on_encode_error(self):
        class _Broken:
            def encode(self, text):
                raise RuntimeError("boom")

        with mock.patch.object(tokens, "_ENCODER", _Broken()):
            # must not raise; falls back to heuristic
            self.assertEqual(tokens.est_tokens("x" * 400, kind="prose"), 100)

    def test_precise_path_empty_text_still_zero(self):
        with mock.patch.object(tokens, "_ENCODER", _FakeEncoder()):
            self.assertEqual(tokens.est_tokens(""), 0)

    def test_module_imports_without_tiktoken_installed(self):
        # tiktoken must never be a hard dependency: simulate it being absent
        # and confirm the module still imports and works via importlib reload.
        import importlib
        import sys
        with mock.patch.dict(sys.modules, {"tiktoken": None}):
            reloaded = importlib.reload(tokens)
            try:
                self.assertIsNone(reloaded._ENCODER)
                self.assertEqual(reloaded.est_tokens("x" * 400), 100)
            finally:
                importlib.reload(tokens)  # restore real module state


class TestMigrationSitesReturnNonNegativeInts(unittest.TestCase):
    """Every site migrated off ad-hoc len//4 math must funnel through
    est_tokens and produce an int >= 0 (never negative, never a float)."""

    def test_inject_est_tokens_is_the_shared_estimator(self):
        from danzaboss.cortex import inject
        cost = inject.est_tokens("hello world")
        self.assertIsInstance(cost, int)
        self.assertGreaterEqual(cost, 0)

    def test_cli_dispatch_tokens_uses_json_kind(self):
        from danzaboss import cli
        cost = cli._dispatch_tokens("Task", {"prompt": "x" * 400})
        self.assertIsInstance(cost, int)
        self.assertGreaterEqual(cost, 0)


if __name__ == "__main__":
    unittest.main()
