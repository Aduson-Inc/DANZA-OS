"""danza CLI — the entrypoint the agent layer + Claude Code hooks call.

Commands:
  danzaboss.cli scan <dir> [--domain D]        learn an AppProfile from a real repo
  danzaboss.cli verify "<test command>" <dir>  run the app's tests -> pass/fail (QA gate)
  danzaboss.cli selftest                        run the cold-start harness
  danzaboss.cli hook pretooluse                 Claude Code PreToolUse guard (reads CC JSON on stdin)
  danzaboss.cli hook stop                       Claude Code Stop hook
  danzaboss.cli cortex <hook|observe|get|search|retrieve|context|age|learn|stats|ui|index|graph|mcp>
                                                CORTEX memory (docs/superpowers/specs/2026-07-03-cortex-design.md)
  danzaboss.cli profile                         print the active execution profile (OS_DEV|OS_BOOT_TEST|APP_BUILD)
  danzaboss.cli tier <paths...> [--commit]      cheapest safe verification tier for a change set
  danzaboss.cli runners <root>                  detect/show the runner registry for a project root
  danzaboss.cli conduct <root> [--poll N] [--max-ticks N]
                                                run the conductor relay loop against a project root

Run:  PYTHONPATH=<repo-root> python3 -m danzaboss.cli <command> ...
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .cortex import commands as cortex_commands
from .kernel.profile import active_profile
from .kernel.tiers import recommend_tier
from .runtime.scan import profile_repo
from .runtime.verify import run_verification
from .selftest.harness import run_cold_start
from .hooks.events import ToolEvent
from .hooks.guards import GuardConfig, hard_stop_guard, file_protection_guard
from .workstation.runners import (RunnerError, RUNNERS_RELPATH,
                                  detect_runners, default_config,
                                  save_runners, load_runners)
from .workstation.hosts import HostError, TmuxHost, HeadlessHost, pick_host
from .workstation.conductor import Conductor, ConductorError, Action


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
        prof = active_profile(os.getcwd())

        # Rule 37 elevation: OS_DEV pre-grants .claude/ writes (Layer 0 edits the
        # OS source, which includes .claude/). Runtime profiles need the explicit
        # user grant: the .danza/runtime/claude-approval sentinel (gitignored)
        # or DANZA_CLAUDE_APPROVAL=1, removable at any time.
        approval = (prof.claude_write_approval
                    or os.path.exists(os.path.join(".danza", "runtime", "claude-approval"))
                    or os.environ.get("DANZA_CLAUDE_APPROVAL") == "1")

        fp = file_protection_guard(ev, cfg, approval=approval)  # templates / .claude / logs
        if not fp.allow:
            return _emit("deny", fp.reason)

        hs = hard_stop_guard(ev, cfg)                # auth/payment/schema/destructive
        if not hs.allow:
            # destructive -> hard deny in EVERY profile, approval or not; sensitive
            # domain -> escalate to the user (Rules 13-16) only where runtime law
            # binds (the patterns exist to protect a user app, not OS source).
            if "destructive" in hs.reason:
                return _emit("deny", hs.reason)
            if prof.domain_ask_active and not approval:
                return _emit("ask", hs.reason)

        return _emit("allow")
    except Exception as e:                           # internal error -> fail open
        print(f"danza hook internal error (failing open): {e}", file=sys.stderr)
        return _emit("allow")


def _cmd_cortex(argv: list[str]) -> int:
    return cortex_commands.main(argv)


def _cmd_profile(_: list[str]) -> int:
    """Print the active execution profile so agents/hooks can consult policy."""
    print(json.dumps(active_profile(os.getcwd()).to_dict(), indent=2))
    return 0


def _cmd_tier(argv: list[str]) -> int:
    """Recommend the cheapest safe verification tier for a set of touched paths."""
    commit = "--commit" in argv
    paths = [a for a in argv if a != "--commit"]
    if not paths and not commit:
        print("usage: danzaboss.cli tier <path> [<path>...] [--commit]", file=sys.stderr)
        return 2
    t = recommend_tier(paths, commit_boundary=commit)
    print(json.dumps({"tier": t.level, "name": t.name, "action": t.action}))
    return 0


def _cmd_runners(argv: list[str]) -> int:
    """Detect or display the runner registry for a project root.

    First call: runs detect_runners(), builds default_config(), writes it to
    RUNNERS_RELPATH, and prints a human line per runner plus the chosen boss
    and the path written.  Subsequent calls: load_runners() + pretty-print.
    NO overwrite on subsequent calls — the /models screen owns edits to
    runners.json once it exists; overwriting would discard user choices.
    """
    if not argv:
        print("usage: danzaboss.cli runners <root>", file=sys.stderr)
        return 2
    root = argv[0]
    try:
        path = Path(root) / RUNNERS_RELPATH
        if path.exists():
            # /models screen owns edits — never overwrite an existing registry
            config = load_runners(root)
            print(json.dumps(config, indent=2))
        else:
            detected = detect_runners()
            config = default_config(detected)
            written = save_runners(root, config)
            for name, entry in config["runners"].items():
                status = "detected" if entry["detected"] else "not found"
                print(f"{name}: {status}")
            print(f"boss: {config['boss']}")
            print(f"written: {written}")
    except RunnerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _cmd_conduct(argv: list[str]) -> int:
    """Run the conductor relay loop against a project root.

    Parses <root>, optional --poll <seconds>, and optional --max-ticks <n>.
    Loads runners.json to pick the right host type, then hands control to
    Conductor.run().  Exit codes: 0 for STOP_DONE or non-terminal exhaustion
    (WAIT/IGNITE after max-ticks); 1 for HALT_BLOCKED or STOP_VALVE (human
    intervention needed); 2 for RunnerError or ConductorError (one-line
    stderr, no traceback).
    """
    if not argv:
        print("usage: danzaboss.cli conduct <root> [--poll N] [--max-ticks N]",
              file=sys.stderr)
        return 2

    root = argv[0]
    rest = argv[1:]
    poll_interval = 2.0
    max_ticks: int | None = None

    i = 0
    while i < len(rest):
        if rest[i] == "--poll" and i + 1 < len(rest):
            try:
                poll_interval = float(rest[i + 1])
            except ValueError:
                print(f"--poll must be a number", file=sys.stderr)
                return 2
            i += 2
        elif rest[i] == "--max-ticks" and i + 1 < len(rest):
            try:
                max_ticks = int(rest[i + 1])
            except ValueError:
                print(f"--max-ticks must be an integer", file=sys.stderr)
                return 2
            i += 2
        else:
            print(f"unknown argument: {rest[i]}", file=sys.stderr)
            return 2

    try:
        config = load_runners(root)
    except RunnerError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        # pick_host may degrade tmux -> headless; the RESOLVED mode must
        # travel with the host or the conductor would pick argv off the
        # raw config and feed an interactive claude to the headless host.
        host_type = pick_host(config["session_host"])
        if host_type == "tmux":
            host = TmuxHost()
        else:
            host = HeadlessHost(log_dir=Path(root) / ".danza" / "runtime")
        action = Conductor(root, host, session_mode=host_type,
                           poll_interval=poll_interval).run(max_ticks=max_ticks)
    except (ConductorError, RunnerError, HostError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if action in (Action.HALT_BLOCKED, Action.STOP_VALVE):
        return 1
    return 0


_COMMANDS = {"scan": _cmd_scan, "verify": _cmd_verify,
             "selftest": _cmd_selftest, "hook": _cmd_hook,
             "cortex": _cmd_cortex, "profile": _cmd_profile,
             "tier": _cmd_tier, "runners": _cmd_runners,
             "conduct": _cmd_conduct}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in _COMMANDS:
        print("danzaboss.cli <scan|verify|selftest|hook|cortex|profile|tier"
              "|runners|conduct> ...",
              file=sys.stderr)
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
