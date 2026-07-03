import unittest
import _bootstrap  # noqa
from danzaboss.planning.decompose import (
    Task, Verification, VerificationKind, assert_dispatchable, DispatchError)


def v(detail="pytest x"):
    return Verification(VerificationKind.AUTOMATED_TEST, detail)


class TestDecompose(unittest.TestCase):
    def test_leaf_without_verification_not_verifiable(self):
        t = Task("a", "do thing")
        self.assertFalse(t.is_verifiable())
        self.assertFalse(t.ready_for_dispatch())

    def test_leaf_with_verification_is_verifiable(self):
        t = Task("a", "do thing", verification=v())
        self.assertTrue(t.is_verifiable())

    def test_empty_verification_detail_rejected(self):
        t = Task("a", "do thing", verification=Verification(VerificationKind.MANUAL_GATE, "  "))
        self.assertFalse(t.is_verifiable())

    def test_parent_verifiable_iff_all_children_verifiable(self):
        parent = Task("p", "parent")
        parent.decompose([Task("c1", "x", verification=v()),
                          Task("c2", "y")])  # c2 unverifiable
        self.assertFalse(parent.is_verifiable())
        self.assertEqual([t.id for t in parent.unverifiable_leaves()], ["c2"])
        parent.subtasks[1].verification = v()
        self.assertTrue(parent.is_verifiable())

    def test_assert_dispatchable_raises_on_unverifiable(self):
        with self.assertRaises(DispatchError):
            assert_dispatchable(Task("a", "vague"))

    def test_assert_dispatchable_passes_on_verifiable(self):
        assert_dispatchable(Task("a", "clear", verification=v()))  # no raise

    def test_decompose_clears_own_verification(self):
        t = Task("p", "x", verification=v())
        t.decompose([Task("c", "y", verification=v())])
        self.assertIsNone(t.verification)


if __name__ == "__main__":
    unittest.main()
