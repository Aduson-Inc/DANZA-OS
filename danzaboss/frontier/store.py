"""Frontier proposal store: `.danza/frontier/state.json` + `proposals.md`.

Decision 7's "approved items -> backlog" lands in two places: the proposal
keeps status="approved" here (the panel's "Backlog (approved)" history), and
the server routes it into the SAME additions store the Build editor uses for
user-added future work (workstation/build.py append_backlog_feature ->
.danza/build-additions.json) via backlog_feature() below. Additions only
ever build after the human additions-approval + replan flow — nothing here
is ever auto-built.

Each proposal carries its own revision fingerprint so Approve/Dismiss follows
the same optimistic-concurrency pattern as product scope / build additions
(workstation/product_scope.py, workstation/build.py) -- scoped per-item here
since proposals are independent records, not one shared document.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path

SCHEMA_VERSION = 1
FRONTIER_RELDIR = Path(".danza") / "frontier"
STATE_RELPATH = FRONTIER_RELDIR / "state.json"
PROPOSALS_MD_RELPATH = FRONTIER_RELDIR / "proposals.md"

STATUSES = ("proposed", "approved", "dismissed")
DECISIONS = ("approved", "dismissed")
SOURCES = ("research", "code_health")


class FrontierError(ValueError):
    """Frontier state is missing, corrupt, or a mutation is invalid."""


class FrontierRevisionConflict(FrontierError):
    """A decide() targeted a stale proposal revision or terminal status."""


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def state_path(root) -> Path:
    return Path(root) / STATE_RELPATH


def _empty_state() -> dict:
    return {"version": SCHEMA_VERSION, "last_run": None, "next_id": 1,
            "proposals": []}


def load_state(root) -> dict:
    """The scout state, or the honest never-ran shape. Corrupt state.json is
    reported, never silently reset — an operator must see it, like every
    other product store (spec section 11 read-side honesty)."""
    path = state_path(root)
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontierError(f"corrupt frontier state at {path}: {exc}") from exc
    if (not isinstance(data, dict)
            or data.get("version") != SCHEMA_VERSION
            or not isinstance(data.get("proposals"), list)):
        raise FrontierError(f"frontier state at {path} has an invalid shape")
    data.setdefault("next_id", len(data["proposals"]) + 1)
    return data


def save_state(root, state: dict) -> None:
    _atomic_json(state_path(root), state)


def render_proposals_md(state: dict) -> str:
    """Human-readable mirror of state.json — the scout's own audit trail,
    grouped so an open proposal, the approved backlog, and dismissed ideas
    are never confused with each other."""
    lines = ["# Frontier scout proposals", "",
             f"Last run: {state.get('last_run') or 'never'}", ""]
    groups = (("Open proposals", "proposed"),
             ("Backlog (approved)", "approved"),
             ("Dismissed", "dismissed"))
    for heading, status in groups:
        items = [p for p in state["proposals"] if p["status"] == status]
        lines.append(f"## {heading}")
        if not items:
            lines.append("_none_")
        for p in items:
            lines.append(f"- **#{p['id']} {p['title']}** ({p['source']})")
            if p.get("summary"):
                lines.append(f"  {p['summary']}")
            if p.get("url"):
                lines.append(f"  {p['url']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _save(root, state: dict) -> None:
    save_state(root, state)
    _atomic_text(Path(root) / PROPOSALS_MD_RELPATH, render_proposals_md(state))


def add_proposals(root, candidates: list[dict], *,
                  now: _dt.datetime | None = None) -> list[dict]:
    """Append new proposals from a completed scout run and stamp last_run.

    Deduplicated by case-insensitive title against every existing record,
    regardless of status — a dismissed idea should not resurface next week,
    and an already-open one should not double up. Always stamps last_run
    (even when nothing new was found): a clean, empty run still resets the
    7-day throttle. Returns only the newly added records."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    state = load_state(root)
    existing_titles = {p["title"].strip().lower() for p in state["proposals"]}
    next_id = state["next_id"]
    added: list[dict] = []
    for item in candidates:
        title = (item.get("title") or "").strip()
        if not title or title.lower() in existing_titles:
            continue
        source = item.get("source")
        if source not in SOURCES:
            raise FrontierError(f"proposal source must be one of {SOURCES}")
        record = {
            "id": next_id,
            "title": title,
            "summary": (item.get("summary") or "").strip(),
            "source": source,
            "url": item.get("url", ""),
            "status": "proposed",
            "revision": 1,
            "created_at": now.isoformat(timespec="seconds"),
            "decided_at": None,
        }
        state["proposals"].append(record)
        existing_titles.add(title.lower())
        added.append(record)
        next_id += 1
    state["next_id"] = next_id
    state["last_run"] = now.isoformat(timespec="seconds")
    _save(root, state)
    return added


def decide(root, proposal_id: int, decision: str, *,
          expected_revision: int, now: _dt.datetime | None = None) -> dict:
    """Approve or dismiss one proposal, gated by its own revision fingerprint
    (mirrors build.py's additions / product_scope.py's scope conflicts).
    Approving moves it into the backlog (status="approved") — it is never
    turned into a build feature automatically."""
    if decision not in DECISIONS:
        raise FrontierError(f"decision must be one of {DECISIONS}, got {decision!r}")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    state = load_state(root)
    record = next((p for p in state["proposals"] if p["id"] == proposal_id),
                  None)
    if record is None:
        raise FrontierError(f"no frontier proposal with id {proposal_id}")
    if record["status"] != "proposed":
        raise FrontierRevisionConflict(
            f"proposal {proposal_id} is already {record['status']}")
    if record["revision"] != expected_revision:
        raise FrontierRevisionConflict(
            f"stale proposal revision {expected_revision!r}; current "
            f"revision is {record['revision']}")
    record["status"] = decision
    record["revision"] += 1
    record["decided_at"] = now.isoformat(timespec="seconds")
    _save(root, state)
    return record


# Sentence terminators the product-scope summary rule counts: a ./!/? run
# followed by whitespace or end of string (product_scope._SENTENCE_RE).
_SENTENCE_BREAK_RE = re.compile(r"[.!?]+(?=\s|$)")


def backlog_feature(record: dict) -> dict:
    """Map an approved proposal to the additions-store feature shape
    (product_scope contract: 1-2 sentence summary <=300 chars, non-empty
    acceptance criteria). Sentence terminators inside the title are
    neutralized so a chatty search-result title can never fail scope
    validation; dots inside file paths are already no sentence break."""
    title = _SENTENCE_BREAK_RE.sub("", record["title"]).strip()
    summary = f"Frontier backlog: {title or 'proposal'}."[:300]
    criterion = (record.get("summary") or "").strip() \
        or f"Evaluate and scope: {title or 'this frontier proposal'}"
    return {"summary": summary, "acceptance_criteria": [criterion]}
