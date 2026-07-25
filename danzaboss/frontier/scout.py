"""Frontier scout orchestration entrypoint (plan 01 Task 11 / Decision 7).

No daemon/cron: `maybe_scout` is the one seam a caller hits opportunistically
wherever the dashboard already polls product state (e.g. a GET the SPA makes
on load). Every early exit is silent and every failure is swallowed here --
a Tavily outage or a code-health bug must never turn into a 500 on an
existing route. The trigger is: canonical repo (the unactivated DANZA-OS
source checkout only -- fail closed on any doubt) AND TAVILY_API_KEY present
AND >=7 days since the last completed run.
"""
from __future__ import annotations

import datetime as _dt
import os
import urllib.request

from danzaboss.kernel.profile import active_profile

from . import codehealth as codehealth_mod
from . import store as store_mod
from . import tavily as tavily_mod

THROTTLE = _dt.timedelta(days=7)
TAVILY_ENV = tavily_mod.TAVILY_ENV


def is_canonical_repo(root, env: dict | None = None) -> bool:
    """Reuse the profile heuristic that already distinguishes Layer-0 OS_DEV
    (this unactivated DANZA-OS checkout) from an activated customer install
    (kernel/profile.py): only the literal OS_DEV profile counts as canonical.
    Any other profile, or a profile-resolution failure, means "cannot prove
    canonical" -> the scout stays off. Customer installs never need or use
    the key."""
    env = env if env is not None else os.environ
    try:
        return active_profile(root, env).name == "OS_DEV"
    except Exception:
        return False


def _due(state: dict, *, now: _dt.datetime) -> bool:
    last_run = state.get("last_run")
    if not last_run:
        return True
    try:
        last = _dt.datetime.fromisoformat(last_run)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=_dt.timezone.utc)
    return now - last >= THROTTLE


def maybe_scout(root, *, env: dict | None = None,
                urlopen=urllib.request.urlopen,
                now: _dt.datetime | None = None) -> dict:
    """Run the weekly scout if it is due; never raises -- this is the one
    call callers make on every dashboard load/poll. Returns a status dict:
    {"ran": False, "reason": ...} for every early exit, or
    {"ran": True, "added": [...]} for a completed run."""
    env = env if env is not None else os.environ
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if not is_canonical_repo(root, env):
        return {"ran": False, "reason": "not_canonical"}
    try:
        state = store_mod.load_state(root)
    except store_mod.FrontierError:
        return {"ran": False, "reason": "corrupt_state"}
    if not _due(state, now=now):
        return {"ran": False, "reason": "not_due"}
    api_key = env.get(TAVILY_ENV, "").strip()
    if not api_key:
        # No key -> the entire weekly scout is inert this opportunity;
        # last_run is left untouched so the next dashboard poll retries.
        return {"ran": False, "reason": "no_key"}
    try:
        research_items = tavily_mod.research_pass(api_key, urlopen=urlopen)
    except store_mod.FrontierError:
        # Tavily unreachable -> silently skip, retry next opportunity
        # (task 11 failure mode); last_run stays untouched.
        return {"ran": False, "reason": "tavily_unreachable"}
    try:
        health_items = codehealth_mod.code_health_pass(root)
    except OSError:
        health_items = []
    added = store_mod.add_proposals(root, research_items + health_items,
                                    now=now)
    return {"ran": True, "added": added}
