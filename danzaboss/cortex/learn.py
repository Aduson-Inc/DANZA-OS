"""Learning engine — CORTEX C5.

Usage is the only training signal: every `record_use` call (CLI `get`,
`retrieve` package assembly) lands one row in the backend's `usage_log`.
This module turns that log into deterministic weight updates — importance
IS the retrieval weight (`_IMPORTANCE_WEIGHT` multiplier in store/retrieve),
so promoting importance is how CORTEX "learns" that a memory earns rank.

Rules are deliberately boring and replayable (same log in, same weights out):

* promote — an observation used >= PROMOTE_AT times climbs one step per
  learn() run along temporary -> low -> medium -> high. Never to critical:
  critical means "a human or agent said so", not "popular".
* refresh — use keeps memories alive: expiry extends to last_used + the
  TTL of the (possibly new) importance, never shrinking an existing expiry.

Demotion is not learning's job — aging (`store.age()`) already archives
what expires, and unused observations simply never get refreshed.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from .observation import Importance, TTL_HOURS
from .store import ObservationStore

PROMOTE_AT = 3  # uses before an observation earns a promotion step

_LADDER = {
    Importance.TEMPORARY.value: Importance.LOW.value,
    Importance.LOW.value: Importance.MEDIUM.value,
    Importance.MEDIUM.value: Importance.HIGH.value,
}


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _extended_expiry(last_used: str, importance: str) -> Optional[str]:
    ttl = TTL_HOURS.get(Importance(importance))
    if ttl is None:
        return None  # critical/archive never carry an expiry
    base = _dt.datetime.fromisoformat(last_used)
    return (base + _dt.timedelta(hours=ttl)).isoformat(timespec="seconds")


def replay(store: ObservationStore, entries: list[dict],
           source: str = "replay") -> int:
    """Re-apply a usage log (rows of {obs_id, ts}) through the live path.

    Exists so a rebuilt or restored store can recover its learned state
    from an exported log, and so tests can drive learning without racing
    real clocks. Returns the number of applied entries.
    """
    applied = 0
    for entry in entries:
        oid = entry.get("obs_id", "")
        if store.get(oid) is None:
            continue
        store.record_use(oid, source=entry.get("source", source),
                         now=entry.get("ts"))
        applied += 1
    return applied


def learn(store: ObservationStore, now: Optional[str] = None) -> dict:
    """One deterministic learning pass over every observation.

    Returns {"promoted": [(id, from, to)...], "refreshed": [id...]} so the
    caller (CLI, session-start scheduler) can report what shifted.
    """
    now = now or _utcnow()
    promoted: list[list[str]] = []
    refreshed: list[str] = []
    for o in store.backend.all():
        changed = False
        if o.usage_count >= PROMOTE_AT and o.importance in _LADDER:
            new_importance = _LADDER[o.importance]
            o.history.append({"ts": now, "event": "promoted_by_learning",
                              "from": o.importance, "to": new_importance,
                              "usage_count": o.usage_count})
            promoted.append([o.id, o.importance, new_importance])
            o.importance = new_importance
            changed = True
        if o.last_used:
            new_expiry = _extended_expiry(o.last_used, o.importance)
            if new_expiry and (o.expires is None or new_expiry > o.expires):
                o.expires = new_expiry
                refreshed.append(o.id)
                changed = True
        if changed:
            o.updated = now
            store.backend.put(o)
    return {"promoted": promoted, "refreshed": refreshed}
