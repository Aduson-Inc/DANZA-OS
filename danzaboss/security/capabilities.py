"""Capability-based security — DANZABOSS Upgrade #10.

Turns the constitution's prose hard-stops into enforced least-privilege. Each
driver holds an explicit set of capabilities (unforgeable, granted at registry
build time). Sensitive domains (auth / payment / db schema — Rules 13-15) and
destructive actions (delete — Rule 16) require an *elevated* capability that is
never granted by default: it must be minted by an explicit, logged authorization
(the human/user gate). Every capability use is written to an append-only audit
trail (Constitution anti-theatre + observability alignment).

This is the "task-intent handle" idea: a capability constrains not just which
action, but under what authorization it may occur.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Capability(str, Enum):
    READ = "read"
    WRITE_CODE = "write_code"          # only the builder
    RUN_TESTS = "run_tests"
    RESEARCH_NET = "research_net"
    WRITE_STATE = "write_state"        # only the orchestrator
    # elevated (never default):
    TOUCH_AUTH = "touch_auth"          # Rule 13
    TOUCH_PAYMENT = "touch_payment"    # Rule 14
    TOUCH_DB_SCHEMA = "touch_db_schema"  # Rule 15
    DELETE = "delete"                  # Rule 16


ELEVATED = {Capability.TOUCH_AUTH, Capability.TOUCH_PAYMENT,
            Capability.TOUCH_DB_SCHEMA, Capability.DELETE}


# default least-privilege grants per driver (post-rename names)
DEFAULT_GRANTS: dict[str, set[Capability]] = {
    "tony-d-orchestrator": {Capability.READ, Capability.WRITE_STATE},
    "jonathan-builder":    {Capability.READ, Capability.WRITE_CODE, Capability.RUN_TESTS},
    "samantha-mapper":     {Capability.READ},
    "angela-auditor":      {Capability.READ},
    "bonnie-qa":           {Capability.READ, Capability.RUN_TESTS},
    "carmella-researcher": {Capability.READ, Capability.RESEARCH_NET},
    "mona-historian":      {Capability.READ},
    "hank-designer":       {Capability.READ, Capability.WRITE_CODE},  # writes design tokens/templates
    "billy-security":      {Capability.READ, Capability.RUN_TESTS},
}


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class CapabilityError(Exception):
    """Raised when an agent attempts an action it does not hold a capability for."""


@dataclass
class ElevationToken:
    """A single-use, logged grant of an elevated capability."""
    capability: str
    granted_to: str
    reason: str
    token: str = field(default_factory=lambda: secrets.token_hex(8))
    ts: str = field(default_factory=_utcnow)
    used: bool = False


class CapabilityRegistry:
    def __init__(self, audit_path: str, grants: Optional[dict[str, set[Capability]]] = None):
        self.grants = {k: set(v) for k, v in (grants or DEFAULT_GRANTS).items()}
        self.audit_path = audit_path
        os.makedirs(os.path.dirname(audit_path) or ".", exist_ok=True)
        self._tokens: dict[str, ElevationToken] = {}

    # -- audit ----------------------------------------------------------------
    def _audit(self, event: dict) -> None:
        event["ts"] = _utcnow()
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    # -- elevation (the user/human gate) --------------------------------------
    def mint_elevation(self, capability: Capability, agent: str, reason: str) -> ElevationToken:
        """Explicitly authorize a one-time elevated action. In production this is
        the point at which the user is prompted (Rules 13-16 hard stops)."""
        if capability not in ELEVATED:
            raise CapabilityError(f"{capability} is not an elevated capability")
        tok = ElevationToken(capability=capability.value, granted_to=agent, reason=reason)
        self._tokens[tok.token] = tok
        self._audit({"event": "mint_elevation", "capability": capability.value,
                     "agent": agent, "reason": reason, "token": tok.token})
        return tok

    # -- enforcement ----------------------------------------------------------
    def check(self, agent: str, capability: Capability,
              elevation: Optional[ElevationToken] = None) -> None:
        """Fail-closed authorization check. Call at every action boundary."""
        if capability in ELEVATED:
            if elevation is None:
                self._audit({"event": "denied", "agent": agent,
                             "capability": capability.value, "reason": "no elevation token"})
                raise CapabilityError(
                    f"{agent} attempted elevated action {capability.value} without "
                    f"an elevation token (Constitution hard stop)")
            tok = self._tokens.get(elevation.token)
            if (tok is None or tok.used or tok.capability != capability.value
                    or tok.granted_to != agent):
                self._audit({"event": "denied", "agent": agent,
                             "capability": capability.value, "reason": "invalid/spent token"})
                raise CapabilityError("invalid or already-used elevation token")
            tok.used = True
            self._audit({"event": "allowed_elevated", "agent": agent,
                         "capability": capability.value, "token": tok.token})
            return

        if capability not in self.grants.get(agent, set()):
            self._audit({"event": "denied", "agent": agent,
                         "capability": capability.value, "reason": "not granted"})
            raise CapabilityError(f"{agent} lacks capability {capability.value}")
        self._audit({"event": "allowed", "agent": agent, "capability": capability.value})
