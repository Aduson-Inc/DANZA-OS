import os, tempfile, unittest
import _bootstrap  # noqa
from danzaboss.security.capabilities import (
    CapabilityRegistry, Capability, CapabilityError)


class TestCapabilities(unittest.TestCase):
    def setUp(self):
        self.audit = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
        self.reg = CapabilityRegistry(self.audit)

    def test_default_grant_allows(self):
        self.reg.check("jonathan-builder", Capability.WRITE_CODE)  # no raise

    def test_missing_grant_denied(self):
        with self.assertRaises(CapabilityError):
            self.reg.check("samantha-mapper", Capability.WRITE_CODE)

    def test_only_orchestrator_writes_state(self):
        self.reg.check("tony-d-orchestrator", Capability.WRITE_STATE)
        with self.assertRaises(CapabilityError):
            self.reg.check("jonathan-builder", Capability.WRITE_STATE)

    def test_elevated_denied_without_token(self):
        with self.assertRaises(CapabilityError):
            self.reg.check("jonathan-builder", Capability.TOUCH_AUTH)

    def test_elevation_allows_once(self):
        tok = self.reg.mint_elevation(Capability.TOUCH_PAYMENT, "jonathan-builder", "checkout")
        self.reg.check("jonathan-builder", Capability.TOUCH_PAYMENT, elevation=tok)
        with self.assertRaises(CapabilityError):  # single use
            self.reg.check("jonathan-builder", Capability.TOUCH_PAYMENT, elevation=tok)

    def test_elevation_bound_to_agent(self):
        tok = self.reg.mint_elevation(Capability.DELETE, "jonathan-builder", "rm file")
        with self.assertRaises(CapabilityError):
            self.reg.check("hank-designer", Capability.DELETE, elevation=tok)

    def test_mint_non_elevated_rejected(self):
        with self.assertRaises(CapabilityError):
            self.reg.mint_elevation(Capability.READ, "x", "y")

    def test_audit_trail_written(self):
        try:
            self.reg.check("samantha-mapper", Capability.WRITE_CODE)
        except CapabilityError:
            pass
        with open(self.audit) as fh:
            lines = [l for l in fh if l.strip()]
        self.assertTrue(any("denied" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
