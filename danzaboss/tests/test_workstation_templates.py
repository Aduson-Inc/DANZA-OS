"""W1-P1 stack templates: data files under validation (design section 5).
Combinations, never pinned versions; selection is deterministic."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.templates import (REQUIRED_FIELDS, StackTemplate,
                                             load_templates,
                                             select_templates)

EXPECTED_KEYS = {"static-site", "content-site", "saas-ts", "saas-python",
                 "lightweight-tool", "realtime-app", "cli-tool"}


class LibraryShape(unittest.TestCase):
    def setUp(self):
        self.templates = load_templates()

    def test_all_seven_load(self):
        self.assertEqual({t.key for t in self.templates}, EXPECTED_KEYS)

    def test_no_pinned_versions_in_components(self):
        for t in self.templates:
            for role, choice in t.components.items():
                for token in str(choice).split():
                    self.assertFalse(
                        token.strip("v").replace(".", "").isdigit()
                        and "." in token,
                        f"{t.key}.{role} pins a version: {choice}")

    def test_ranks_unique(self):
        ranks = [t.rank for t in self.templates]
        self.assertEqual(len(ranks), len(set(ranks)))


class Selection(unittest.TestCase):
    def setUp(self):
        self.templates = load_templates()

    def test_saas_with_auth_and_payments_recommends_ts_standard(self):
        picks = select_templates(self.templates, "saas",
                                 ["accounts_auth", "payments"])
        self.assertEqual(picks[0].key, "saas-ts")

    def test_plain_website_recommends_static(self):
        picks = select_templates(self.templates, "website", [])
        self.assertEqual(picks[0].key, "static-site")

    def test_workflow_recommends_cli_tool(self):
        picks = select_templates(self.templates, "workflow", [])
        self.assertEqual(picks[0].key, "cli-tool")

    def test_realtime_capability_surfaces_realtime_template(self):
        picks = select_templates(self.templates, "saas", ["realtime"])
        self.assertIn("realtime-app", [t.key for t in picks[:2]])

    def test_selection_is_deterministic(self):
        a = select_templates(self.templates, "saas", ["accounts_auth"])
        b = select_templates(self.templates, "saas", ["accounts_auth"])
        self.assertEqual([t.key for t in a], [t.key for t in b])


class Validation(unittest.TestCase):
    def test_missing_field_fails_closed(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict.fromkeys(REQUIRED_FIELDS, "x")
            del bad["rank"]
            Path(tmp, "bad.json").write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_templates(tmp)

    def test_empty_directory_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_templates(tmp)

    def test_wrong_field_type_fails_closed(self):
        # Final-review fix: presence-only validation let a string rank or
        # string best_for load, deferring the explosion to select time.
        import json
        import tempfile
        from pathlib import Path
        good = {"name": "x", "tagline": "x",
                "best_for": {"project_types": ["saas"], "capabilities": []},
                "components": {}, "why": "x", "tradeoffs": "x",
                "avoid_when": "x", "testing_defaults": {},
                "philosophy_fit": "x", "rank": 1}
        for field, bad_value in (("rank", "3"), ("best_for", "saas"),
                                 ("rank", True)):
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "bad.json").write_text(
                    json.dumps(dict(good, **{field: bad_value})))
                with self.assertRaises(ValueError, msg=f"{field}={bad_value}"):
                    load_templates(tmp)


if __name__ == "__main__":
    unittest.main()
