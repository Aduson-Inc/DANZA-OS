"""danza CLI — the entrypoint the agent layer + Claude Code hooks call.

Commands:
  danzaboss.cli scan <dir> [--domain D]        learn an AppProfile from a real repo
  danzaboss.cli verify "<test command>" <dir>  run the app's tests -> pass/fail (QA gate)
  danzaboss.cli selftest                        run the cold-start harness
  danzaboss.cli hook pretooluse                 Claude Code PreToolUse guard (reads CC JSON on stdin)
  danzaboss.cli hook stop                       Claude Code Stop hook

Run:  PYTHONPATH=<repo-root> python3 -m danzaboss.cli <command> ...
"""
from __future__ import annotations

import json
import sys

from .runtime.scan import profile_repo
from .runtime.verify import run_verification
from .selftest.harness import run_cold_start
from .hooks.events import ToolEvent
from .hooks.guards import GuardConfig, hard_stop_guard, file_protection_guard


def _cmd_scan(argv: list[str]) -> int:
    if not argv:
        print("usage: danzaboss.cli scan <dir> [--domain D]", file=sys.stderr); return 2
    root = argv[0]
    domain = argv[argv.index("--domain") + 1] if "--domain" in argv else ""
    print(json.dumps(profile_repo("target", root, domain=domain).to_dict(), indent=2, default=str))
    return 0


def _cmd_verify(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: danzaboss.cli verify "<test command>" <dir>', file=sys.stderr); return 2
    res = run_verification(argv[0], argv[1])
    print(json.dumps(res.__dict__, indent=2))
    return 0 if res.passed else 1


def _cmd_selftest(_: list[str]) -> int:
    rep = run_cold_start()
    print(json.dumps(rep.to_dict(), indent=2))
    return 0 if rep.ok else 1


# ---- Claude Code hook protocol ---------------------------------------------
# Contract (verified against Claude Code hooks docs):
#   * stdin = CC event JSON (tool_name, tool_input{command,file_path,...}).
#   * Decision via stdout JSON + exit 0:
#       {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#        "permissionDecision": "allow"|"deny"|"ask",
#        "permissionDecisionReason": "..."}}
#   * FAIL OPEN on any internal error (exit 0, allow) so a hook bug never bricks
#     the session. FAIL CLOSED only on a real policy hit.

def _emit(decision: str, reason: str = "") -> int:
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(out))
    return 0


def _cmd_hook(argv: list[str]) -> int:
    event = argv[0] if argv else "pretooluse"
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        return _emit("allow")  # unreadable input -> fail open

    if event in ("stop", "Stop"):
        # DANZA's turn-end gates (anti-theatre/verify/regression) need turn data
        # the CC Stop event does not carry, so we do not block stops here.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop"}}))
        return 0

    # PreToolUse: enforce the actor-independent, safety-critical guards.
    try:
        ti = payload.get("tool_input", {}) or {}
        ev = ToolEvent(
            actor="",  # CC hooks don't expose the acting sub-agent
            tool=payload.get("tool_name", ""),
            path=ti.get("file_path") or ti.get("path") or "",
            command=ti.get("command", ""),
        )
        cfg = GuardConfig()

        fp = file_protection_guard(ev, cfg)          # templates / .claude / log overwrite
        if not fp.allow:
            return _emit("deny", fp.reason)

        hs = hard_stop_guard(ev, cfg)                # auth/payment/schema/destructive
        if not hs.allow:
            # destructive -> hard deny; sensitive domain -> escalate to the user (Rules 13-16)
            decision = "deny" if "destructive" in hs.reason else "ask"
            return _emit(decision, hs.reason)

        return _emit("allow")
    except Exception as e:                           # internal error -> fail open
        print(f"danza hook internal error (failing open): {e}", file=sys.stderr)
        return _emit("allow")


_COMMANDS = {"scan": _cmd_scan, "verify": _cmd_verify,
             "selftest": _cmd_selftest, "hook": _cmd_hook}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in _COMMANDS:
        print("danzaboss.cli <scan|verify|selftest|hook> ...", file=sys.stderr)
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
