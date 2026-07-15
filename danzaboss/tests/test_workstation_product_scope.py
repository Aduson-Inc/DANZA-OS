"""Phase 4.1 Task 3: authoritative product-scope artifacts."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa

from danzaboss.workstation import product_scope
from danzaboss.workstation.product_scope import (
    FEATURE_LIST_RELPATH,
    FEATURES_JSON_RELPATH,
    ProductScopeError,
    load_scope,
    new_scope,
    validate_scope,
    write_scope,
)


def _missing(*_args, **_kwargs):
    raise AssertionError("product scope behavior is not implemented")


RevisionConflict = getattr(product_scope, "RevisionConflict", ProductScopeError)
approve_scope = getattr(product_scope, "approve_scope", _missing)
derive_progress = getattr(product_scope, "derive_progress", _missing)
revise_scope = getattr(product_scope, "revise_scope", _missing)


def feature(feature_id=71, *, status="pending"):
    return {
        "id": feature_id,
        "summary": "Users can save a draft and return to it later.",
        "acceptance_criteria": [
            "A saved draft survives a process restart.",
            "Returning users resume the latest saved draft.",
        ],
        "status": status,
    }


class ProductScopeArtifacts(unittest.TestCase):
    def test_validated_scope_round_trips_and_generates_markdown(self):
        with tempfile.TemporaryDirectory() as root:
            scope = new_scope([feature()])

            json_path, md_path = write_scope(root, scope)

            self.assertEqual(json_path, Path(root) / FEATURES_JSON_RELPATH)
            self.assertEqual(md_path, Path(root) / FEATURE_LIST_RELPATH)
            self.assertEqual(load_scope(root), scope)
            self.assertEqual(json.loads(json_path.read_text()), scope)
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("Generated from `.danza/features.json`", markdown)
            self.assertIn("**71", markdown)
            self.assertIn("<details>", markdown)
            self.assertIn("A saved draft survives", markdown)
            self.assertIn("Progress: 0/1 (0%)", markdown)
            self.assertEqual(list((Path(root) / ".danza").glob("*.tmp")), [])

    def test_markdown_is_regenerated_from_json_authority(self):
        with tempfile.TemporaryDirectory() as root:
            scope = new_scope([feature()])
            _, md_path = write_scope(root, scope)
            md_path.write_text("not authoritative", encoding="utf-8")

            loaded = load_scope(root)
            write_scope(root, loaded)

            self.assertIn("**71", md_path.read_text(encoding="utf-8"))


class ScopeValidation(unittest.TestCase):
    def test_rejects_unstable_or_duplicate_product_ids(self):
        for bad_id in (True, 0, -1, 1.0, "71"):
            with self.subTest(bad_id=bad_id), self.assertRaises(ProductScopeError):
                new_scope([feature(bad_id)])
        with self.assertRaises(ProductScopeError):
            new_scope([feature(71), feature(71)])

    def test_rejects_non_concise_summary_and_empty_criteria(self):
        too_many = feature()
        too_many["summary"] = "One. Two. Three."
        no_criteria = feature()
        no_criteria["acceptance_criteria"] = []
        for invalid in (too_many, no_criteria):
            with self.subTest(invalid=invalid), self.assertRaises(ProductScopeError):
                new_scope([invalid])

    def test_rejects_inconsistent_approval_revision(self):
        scope = new_scope([feature()])
        scope["approval"] = {"state": "approved", "approved_revision": 2}
        with self.assertRaises(ProductScopeError):
            validate_scope(scope)


class ExactRevisionApproval(unittest.TestCase):
    def test_approval_records_the_exact_revision(self):
        with tempfile.TemporaryDirectory() as root:
            write_scope(root, new_scope([feature()]))

            approved = approve_scope(root, expected_revision=1)

            self.assertEqual(approved["revision"], 1)
            self.assertEqual(
                approved["approval"],
                {"state": "approved", "approved_revision": 1},
            )
            self.assertEqual(load_scope(root), approved)

    def test_stale_approval_is_rejected_without_changing_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            write_scope(root, new_scope([feature()]))
            revised_feature = feature()
            revised_feature["summary"] = "Users can safely resume saved drafts."
            revise_scope(root, expected_revision=1, features=[revised_feature])
            json_path = Path(root) / FEATURES_JSON_RELPATH
            md_path = Path(root) / FEATURE_LIST_RELPATH
            before = (json_path.read_bytes(), md_path.read_bytes())

            with self.assertRaises(RevisionConflict):
                approve_scope(root, expected_revision=1)

            self.assertEqual((json_path.read_bytes(), md_path.read_bytes()), before)


class DerivedProgress(unittest.TestCase):
    def test_progress_and_product_status_are_derived_from_feature_statuses(self):
        scope = new_scope([feature(71, status="completed"), feature(72)])

        self.assertEqual(
            derive_progress(scope),
            {"status": "in_progress", "completed": 1, "total": 2,
             "percent": 50},
        )

    def test_blocked_and_completed_product_statuses_are_derived(self):
        blocked = new_scope([feature(71, status="blocked"), feature(72)])
        completed = new_scope([
            feature(71, status="completed"),
            feature(72, status="completed"),
        ])
        self.assertEqual(derive_progress(blocked)["status"], "blocked")
        self.assertEqual(derive_progress(completed)["status"], "completed")
        self.assertEqual(derive_progress(completed)["percent"], 100)


class CorruptionAndImmutability(unittest.TestCase):
    def test_load_fails_closed_on_invalid_json_and_invalid_shape(self):
        for raw in ("{not json", json.dumps({"version": 1})):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as root:
                path = Path(root) / FEATURES_JSON_RELPATH
                path.parent.mkdir(parents=True)
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ProductScopeError):
                    load_scope(root)

    def test_corrupt_enum_shapes_raise_scope_error(self):
        invalid = new_scope([feature()])
        invalid["approval"]["state"] = []
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / FEATURES_JSON_RELPATH
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaises(ProductScopeError):
                load_scope(root)

    def test_write_refuses_to_heal_corrupt_authority(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / FEATURES_JSON_RELPATH
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")

            with self.assertRaises(ProductScopeError):
                write_scope(root, new_scope([feature()]))

            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_completed_feature_cannot_be_changed_or_removed(self):
        with tempfile.TemporaryDirectory() as root:
            scope = new_scope([feature(71, status="completed"), feature(72)])
            write_scope(root, scope)
            changed = feature(71, status="completed")
            changed["summary"] = "A different feature now uses this ID."
            path = Path(root) / FEATURES_JSON_RELPATH
            before = path.read_bytes()

            with self.assertRaises(ProductScopeError):
                revise_scope(root, expected_revision=1,
                             features=[changed, feature(72)])
            with self.assertRaises(ProductScopeError):
                revise_scope(root, expected_revision=1,
                             features=[feature(72)])

            self.assertEqual(path.read_bytes(), before)

    def test_fully_completed_product_scope_is_immutable(self):
        with tempfile.TemporaryDirectory() as root:
            write_scope(root, new_scope([feature(status="completed")]))
            approve_scope(root, expected_revision=1)

            with self.assertRaises(ProductScopeError):
                revise_scope(root, expected_revision=1,
                             features=[feature(status="completed"), feature(72)])


if __name__ == "__main__":
    unittest.main()
