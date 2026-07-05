"""W1-P1 spec compiler: approved answers render into the fixed
planning/spec_template.md shape — the document every plan derives from."""
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.compiler import compile_spec, write_spec
from danzaboss.workstation.templates import load_templates

ANSWERS = {
    "project_type": "saas",
    "project_name": "DrumLog",
    "concept_what": "Tracks practice sessions for drummers.",
    "concept_who": "Working drummers",
    "concept_problem": "No record of what was practiced",
    "features_must": ["log a session", "weekly summary email"],
    "features_nice": ["streak badges"],
    "non_goals": ["social feed"],
    "capabilities": ["accounts_auth", "payments"],
    "stack_choice": "template",
    "stack_template": "saas-ts",
    "color_direction": "propose",
    "repo_mode": "fresh",
    "deploy_intent": "vps",
    "cadence": "continuous",
    "cadence_n": "4",
}

HEADINGS = ["## 1. Intent", "## 2. Functional requirements",
            "## 3. Non-functional requirements", "## 4. Data model",
            "## 5. External services / APIs", "## 6. Explicit non-goals",
            "## 7. Verification strategy", "## 8. Open questions"]


def _template(key):
    return next(t for t in load_templates() if t.key == key)


class CompileSpec(unittest.TestCase):
    def setUp(self):
        self.text = compile_spec(
            answers=ANSWERS, template=_template("saas-ts"),
            research={"verdict": "crowded_but_viable",
                      "summary": "Three practice-log apps exist; none do drums."},
            checkpoints={"cp_concept": "Concept confirmed.",
                         "cp_final": "Rundown approved."},
        )

    def test_title_and_heading_order(self):
        self.assertTrue(self.text.startswith("# Spec — DrumLog"))
        positions = [self.text.index(h) for h in HEADINGS]
        self.assertEqual(positions, sorted(positions))

    def test_functional_requirements_numbered(self):
        self.assertIn("- FR-1: log a session", self.text)
        self.assertIn("- FR-2: weekly summary email", self.text)
        self.assertIn("(nice-to-have, post-MVP): streak badges", self.text)

    def test_hard_stop_flags_surfaced(self):
        self.assertIn("accounts_auth", self.text)
        self.assertIn("Rules 13-14", self.text)

    def test_stack_components_listed(self):
        self.assertIn("SaaS Standard (TypeScript)", self.text)
        self.assertIn("Stripe", self.text)

    def test_cadence_recorded(self):
        self.assertIn("continuous", self.text)
        self.assertIn("N=4", self.text)

    def test_research_verdict_in_intent(self):
        self.assertIn("crowded_but_viable", self.text)

    def test_non_goals_present(self):
        self.assertIn("- social feed", self.text)

    def test_open_questions_default_none(self):
        tail = self.text.split("## 8. Open questions")[1]
        self.assertIn("None.", tail)


class Overrides(unittest.TestCase):
    def test_custom_stack_and_override_notes(self):
        answers = dict(ANSWERS, stack_choice="custom",
                       stack_custom="Django + MongoDB")
        text = compile_spec(
            answers=answers, template=None,
            overrides=("User kept Django + MongoDB against recommendation "
                       "saas-python (checkpoint cp_stack).",))
        self.assertIn("Django + MongoDB", text)
        self.assertIn("OVERRIDE:", text)

    def test_skipped_research_is_honest(self):
        text = compile_spec(answers=ANSWERS, template=_template("saas-ts"),
                            research=None)
        self.assertIn("Reality check: not run", text)


class WriteSpec(unittest.TestCase):
    def test_writes_to_danza_spec_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, "# Spec — X\n")
            self.assertEqual(path, Path(tmp) / ".danza" / "spec.md")
            self.assertEqual(path.read_text(), "# Spec — X\n")


if __name__ == "__main__":
    unittest.main()
