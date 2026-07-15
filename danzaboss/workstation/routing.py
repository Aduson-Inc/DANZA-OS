"""Deterministic seat router for the DANZA workstation — which connected
runner takes the next turn.

Why this module exists: Phase 4 replaces the single-boss model with a team of
1-5 connected AI CLI runners, each assigned to plain-English seats (conductor
plus eight work types). The SETUP tab needs strengths-based seat suggestions,
a validated persistent record of the confirmed team (routing.json), and the
conductor needs one pure, testable answer to "who takes this turn?". All
three live here so seat vocabulary and routing policy have a single home —
no other module hard-codes seat names.

v1 progress cursor (documented proxy): next_boss locates the current feature
as ``turn_number * max_features_per_turn`` clamped into the plan's feature
list. This assumes every completed turn shipped its full feature quota; real
task-completion tracking replaces the cursor in a later phase. The cursor
feature's first leaf supplies the task kind, which maps through
KIND_TO_WORK_TYPE to a seat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from danzaboss.kernel.state import TeamState
from danzaboss.workstation import planner
from danzaboss.workstation.runners import KNOWN_RUNNERS, load_runners

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 2
DEFAULT_FEATURES_PER_TURN = 2
MIN_FEATURES_PER_TURN = 2
MAX_FEATURES_PER_TURN = 5

ROUTING_RELPATH: Path = Path(".danza") / "runtime" / "routing.json"

# The eight work-type seats a runner can hold, plus the conductor seat.
# Order is presentation order for the SETUP tab.
SEAT_WORK_TYPES = ("plan", "build", "map", "qa", "review",
                   "research", "design", "security")
SEATS = ("conductor",) + SEAT_WORK_TYPES

# The conductor seat may be held by the deterministic built-in engine rather
# than a runner (Decision 2, Phase 4 grilling): AI conductor is an advanced
# opt-in, so "builtin" is the default and only non-runner seat value.
BUILTIN_CONDUCTOR = "builtin"

# planning.decompose.TASK_KINDS -> seat work type. Every plan-record kind
# must map somewhere; an unmapped kind in a plan is a routing error, not a
# silent default (fail closed).
KIND_TO_WORK_TYPE = {"scaffold": "build", "backend": "build",
                     "frontend": "build", "db-migration": "build",
                     "integration": "build", "config": "build",
                     "design": "design", "test": "qa"}

_MAX_LINEUP = 5


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RoutingError(ValueError):
    """Invalid routing state, unusable lineup, or unroutable plan."""


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

def _connected(config: dict) -> list[str]:
    """Runner names usable for seating: detected and not known to be logged
    out ("unprobed" counts — the runner may work, and excluding it would
    leave probeless CLIs permanently unseatable). KNOWN_RUNNERS order so
    ties resolve the same way as boss selection in default_config."""
    runners = config.get("runners", {})
    return [name for name in KNOWN_RUNNERS
            if name in runners
            and runners[name].get("detected", False)
            and runners[name].get("auth") != "unauthenticated"]


def suggest_seats(config: dict) -> dict:
    """Suggest a full seat assignment from the runner catalog's per-model
    strengths. Returns all 9 seats; deterministic for a given config.

    Each work type goes to the first connected runner (KNOWN_RUNNERS order)
    that lists it in suggested_seats; work types nobody lists fall back to
    the first connected runner so every seat is always filled. The conductor
    seat is always the built-in engine (Decision 2) — the user upgrades it
    to a runner explicitly, never by suggestion. Raises RoutingError when
    no runner is connected: there is no valid team to suggest."""
    connected = _connected(config)
    if not connected:
        raise RoutingError(
            "no agents are connected — open the dashboard SETUP tab and "
            "connect at least one AI agent"
        )
    seats = {"conductor": BUILTIN_CONDUCTOR}
    for work_type in SEAT_WORK_TYPES:
        seats[work_type] = next(
            (name for name in connected
             if work_type in config["runners"][name]["suggested_seats"]),
            connected[0])
    return seats


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_routing(routing: object, config: dict) -> dict:
    """Validate a routing dict against the live runner *config*. Returns the
    routing on success; raises RoutingError describing the first violation.

    Fail-closed: version, lineup of 1-5 unique connected-and-authenticated
    runner names, seats keys exactly == SEATS, every non-conductor seat
    held by a lineup member, conductor held by a lineup member or the
    built-in engine. A runner that was uninstalled or logged out since the
    team was confirmed makes its routing invalid — it must never silently
    take a turn."""
    if not isinstance(routing, dict):
        raise RoutingError(
            f"routing must be a dict, got {type(routing).__name__!r}"
        )

    version = routing.get("version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise RoutingError(
            f"routing version {version!r} != expected {SCHEMA_VERSION} — "
            f"open the dashboard SETUP tab to rebuild your team"
        )

    features_per_turn = routing.get("features_per_turn")
    if (type(features_per_turn) is not int
            or not MIN_FEATURES_PER_TURN <= features_per_turn <= MAX_FEATURES_PER_TURN):
        raise RoutingError(
            f"features_per_turn must be an integer from "
            f"{MIN_FEATURES_PER_TURN} to {MAX_FEATURES_PER_TURN}, "
            f"got {features_per_turn!r}"
        )

    lineup = routing.get("lineup")
    if (not isinstance(lineup, list)
            or not 1 <= len(lineup) <= _MAX_LINEUP
            or not all(isinstance(name, str) for name in lineup)):
        raise RoutingError(
            f"lineup must be a list of 1-{_MAX_LINEUP} runner names, "
            f"got {lineup!r}"
        )
    if len(set(lineup)) != len(lineup):
        raise RoutingError(f"lineup has duplicate names: {lineup!r}")

    runners = config.get("runners", {})
    for name in lineup:
        entry = runners.get(name)
        if not isinstance(entry, dict):
            raise RoutingError(
                f"lineup member {name!r} is not in the runner registry"
            )
        if not entry.get("detected", False):
            raise RoutingError(
                f"lineup member {name!r} is not installed — open the "
                f"dashboard SETUP tab to rebuild your team"
            )
        if entry.get("auth") == "unauthenticated":
            raise RoutingError(
                f"lineup member {name!r} is not logged in — open the "
                f"dashboard SETUP tab to reconnect your agents"
            )

    seats = routing.get("seats")
    if not isinstance(seats, dict):
        raise RoutingError(
            f"'seats' must be a dict, got {type(seats).__name__!r}"
        )
    if set(seats) != set(SEATS):
        missing = sorted(set(SEATS) - set(seats))
        extra = sorted(set(seats) - set(SEATS))
        raise RoutingError(
            f"seats keys must be exactly {sorted(SEATS)!r} "
            f"(missing {missing!r}, unexpected {extra!r})"
        )
    for seat in SEATS:
        value = seats[seat]
        if seat == "conductor":
            if value != BUILTIN_CONDUCTOR and value not in lineup:
                raise RoutingError(
                    f"conductor seat {value!r} must be a lineup member or "
                    f"{BUILTIN_CONDUCTOR!r}"
                )
        elif value not in lineup:
            raise RoutingError(
                f"seat {seat!r} is assigned to {value!r}, which is not in "
                f"the lineup (only the conductor seat may be "
                f"{BUILTIN_CONDUCTOR!r})"
            )

    return routing


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_routing(root: str | os.PathLike, routing: dict,
                 config: dict) -> Path:
    """Validate *routing* against *config* and atomically write it to
    ROUTING_RELPATH under *root*.

    Atomic write (tmp -> os.replace) so a crash never leaves a torn file.
    Plain overwrite is correct: the SETUP tab writes the whole confirmed
    team at once, so merging would resurrect stale seat assignments. Same
    reasoning as save_runners."""
    validate_routing(routing, config)
    path = Path(root) / ROUTING_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(routing, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_routing(root: str | os.PathLike) -> dict:
    """Read the routing from ROUTING_RELPATH under *root* and validate it
    against the CURRENT runner registry (runners.json is re-loaded here, not
    trusted from confirm time — a runner uninstalled or logged out since
    SETUP must invalidate the routing rather than silently take a turn).

    Missing file / invalid JSON -> RoutingError pointing at the SETUP tab,
    in the load_runners idiom. A missing or invalid runners.json raises
    RunnerError from load_runners — equally fail-closed."""
    path = Path(root) / ROUTING_RELPATH
    if not path.exists():
        raise RoutingError(
            f"team routing not found at {path}; open the dashboard SETUP "
            f"tab to build and confirm your team"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RoutingError(
            f"team routing at {path} is not valid JSON: {exc}"
        ) from exc
    if (isinstance(raw, dict) and type(raw.get("version")) is int
            and raw["version"] == 1):
        legacy_keys = {"version", "lineup", "seats"}
        if set(raw) != legacy_keys:
            raise RoutingError(
                "legacy routing version 1 must contain exactly version, "
                "lineup, and seats"
            )
        raw = {**raw, "version": SCHEMA_VERSION,
               "features_per_turn": DEFAULT_FEATURES_PER_TURN}
    return validate_routing(raw, load_runners(root))


# ---------------------------------------------------------------------------
# Turn routing
# ---------------------------------------------------------------------------

def _leaf_index(tasks) -> dict:
    """id -> leaf Task for every leaf in the parsed tree."""
    out: dict = {}

    def walk(task) -> None:
        if task.is_leaf():
            out[task.id] = task
        for sub in task.subtasks:
            walk(sub)

    for task in tasks:
        walk(task)
    return out


def route_turn(routing: dict, plan_data: dict,
               state: TeamState) -> tuple[str, str]:
    """Pure decision (no I/O): ``(runner name, work type)`` for the next
    turn. The work type rides along so the conductor's ignite log can say
    WHY a runner was chosen, not just which one.

    Cursor rule (v1 proxy — see module docstring): feature index is
    ``state.turn_number * state.max_features_per_turn`` (continuous mode
    has no quota; it advances one feature per turn), clamped to the last
    feature so a finished plan routes its final feature rather than
    crashing. The cursor feature's FIRST leaf in execution order supplies
    the kind; KIND_TO_WORK_TYPE names the seat.

    An unknown kind raises RoutingError (fail closed). A "builtin" or
    missing seat value — possible only in a hand-edited file, since
    validate_routing forbids both — falls back to deterministic rotation:
    ``lineup[turn_number % len(lineup)]``."""
    tasks = planner.parse_plan(plan_data)
    index = _leaf_index(tasks)
    order = plan_data.get("order")
    if (not isinstance(order, list) or not order
            or not all(isinstance(tid, str) for tid in order)):
        raise RoutingError("plan 'order' must be a non-empty list of task ids")
    try:
        ordered = tuple(index[tid] for tid in order)
    except KeyError as exc:
        raise RoutingError(
            f"plan 'order' names unknown task {exc.args[0]!r}"
        ) from None

    features = planner.feature_nodes(ordered)
    per_turn = state.max_features_per_turn or 1
    idx = min(state.turn_number * per_turn, len(features) - 1)
    feature = features[idx]
    leaf = next(item for item in ordered
                if ".".join(item.id.split(".")[:2]) == feature)

    if leaf.kind not in KIND_TO_WORK_TYPE:
        raise RoutingError(
            f"task {leaf.id!r} has kind {leaf.kind!r}, which has no "
            f"work-type mapping in {sorted(KIND_TO_WORK_TYPE)!r}"
        )
    work_type = KIND_TO_WORK_TYPE[leaf.kind]

    seat = routing.get("seats", {}).get(work_type)
    lineup = routing["lineup"]
    if seat is None or seat == BUILTIN_CONDUCTOR:
        return lineup[state.turn_number % len(lineup)], work_type
    return seat, work_type


def next_boss(routing: dict, plan_data: dict, state: TeamState) -> str:
    """The runner name that takes the next turn — route_turn minus the
    work type, kept for callers that only need the seat holder."""
    return route_turn(routing, plan_data, state)[0]
