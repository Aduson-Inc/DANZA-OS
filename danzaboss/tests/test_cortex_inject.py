import json
import os
import tempfile
import unittest

import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.inject import build_context, rank_for_injection, est_tokens
from danzaboss.kernel.state import StateManager


def obs(title, **kw):
    kw.setdefault("summary", "s")
    kw.setdefault("type", ObsType.DECISION.value)
    kw.setdefault("project", "p")
    return Observation(title=title, **kw)


def _root_with_turn_brief(status: str = "in_progress") -> str:
    """A temp repo root with a turn-brief file AND a team-state.json whose
    status is the given value (kernel/state.py's real _ALLOWED_STATUS)."""
    root = tempfile.mkdtemp()
    runtime = os.path.join(root, ".danza", "runtime")
    os.makedirs(runtime)
    with open(os.path.join(runtime, "turn-brief.md"), "w", encoding="utf-8") as fh:
        fh.write("## Your turn\n- Boss/runner: **claude** (turn 1)\n")
    if status == "ready":
        # StateManager.init() always starts at "ready" — no transition needed.
        StateManager(os.path.join(runtime, "team-state.json")).init()
    else:
        mgr = StateManager(os.path.join(runtime, "team-state.json"))
        mgr.init()
        mgr.transition(to_status="in_progress", actor="claude")
        if status != "in_progress":
            mgr.transition(to_status=status, actor="claude")
    return root


def _root_without_turn_brief() -> str:
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, ".danza", "runtime"))
    return root


def _root_with_corrupt_team_state() -> str:
    """A turn-brief file exists, but team-state.json is not valid JSON."""
    root = tempfile.mkdtemp()
    runtime = os.path.join(root, ".danza", "runtime")
    os.makedirs(runtime)
    with open(os.path.join(runtime, "turn-brief.md"), "w", encoding="utf-8") as fh:
        fh.write("## Your turn\n")
    with open(os.path.join(runtime, "team-state.json"), "w", encoding="utf-8") as fh:
        fh.write("{not valid json")
    return root


class TestInjection(unittest.TestCase):
    def setUp(self):
        self.store = ObservationStore(SqliteBackend(":memory:"))

    def test_empty_store_yields_empty_block(self):
        self.assertEqual(build_context(self.store, "p"), "")

    def test_critical_outranks_low(self):
        self.store.upsert(obs("minor note", importance=Importance.LOW.value,
                              concepts=["a"]))
        self.store.upsert(obs("auth is critical", importance=Importance.CRITICAL.value,
                              concepts=["b"]))
        ranked = rank_for_injection(self.store, "p")
        self.assertEqual(ranked[0].title, "auth is critical")

    def test_changed_file_overlap_boosts(self):
        self.store.upsert(obs("touches cli", files=["danzaboss/cli.py"],
                              concepts=["cli"]))
        self.store.upsert(obs("touches nothing", concepts=["other"]))
        ranked = rank_for_injection(self.store, "p",
                                    changed_files=["danzaboss/cli.py"])
        self.assertEqual(ranked[0].title, "touches cli")

    def test_archived_never_injected(self):
        self.store.upsert(obs("dead knowledge", importance=Importance.ARCHIVE.value,
                              concepts=["dead"]))
        self.assertEqual(build_context(self.store, "p"), "")

    # ---- compact index (no active turn brief) ------------------------------

    def test_no_root_yields_compact_index_with_titles_no_bodies(self):
        self.store.upsert(obs("Redis decision", summary="why redis",
                              reasoning="races", concepts=["redis"]))
        block = build_context(self.store, "p")
        self.assertIn("[CORTEX]", block)
        self.assertIn("Redis decision", block)
        self.assertNotIn("why redis", block)        # no full body
        self.assertNotIn("races", block)             # no reasoning body
        self.assertIn("danza cortex get", block)     # fetch-by-id hint

    def test_no_turn_brief_file_yields_compact_index(self):
        root = _root_without_turn_brief()
        self.store.upsert(obs("Redis decision", summary="why redis",
                              reasoning="races", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("Redis decision", block)
        self.assertNotIn("why redis", block)
        self.assertIn("danza cortex get", block)

    def test_compact_index_stays_under_token_cap(self):
        root = _root_without_turn_brief()
        for i in range(30):
            self.store.upsert(obs(f"unique topic {i}", summary="x" * 800,
                                  reasoning="y" * 800, concepts=[f"c{i}"]))
        block = build_context(self.store, "p", root=root)
        self.assertNotIn("x" * 800, block)  # bodies never present
        # index-only block stays small: cap (~1200) plus header/legend/footer
        self.assertLess(est_tokens(block), 1500)

    # ---- active turn brief -> pointer block only ---------------------------

    def test_active_turn_brief_yields_pointer_only(self):
        root = _root_with_turn_brief(status="in_progress")
        self.store.upsert(obs("Redis decision", summary="why redis",
                              reasoning="races", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("turn-brief.md", block)
        self.assertNotIn("Redis decision", block)   # no titles
        self.assertNotIn("why redis", block)         # no bodies
        self.assertNotIn("danza cortex get <id>", block)  # not the index footer
        # 2-3 lines, lean
        self.assertLessEqual(len(block.strip().splitlines()), 3)

    def test_active_turn_brief_ready_status_also_yields_pointer(self):
        root = _root_with_turn_brief(status="ready")
        self.store.upsert(obs("Redis decision", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("turn-brief.md", block)
        self.assertNotIn("Redis decision", block)

    def test_active_turn_brief_awaiting_handoff_also_yields_pointer(self):
        root = _root_with_turn_brief(status="awaiting_handoff")
        self.store.upsert(obs("Redis decision", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("turn-brief.md", block)
        self.assertNotIn("Redis decision", block)

    def test_turn_brief_file_without_active_status_yields_compact_index(self):
        # blocked/done are not "active relay turn" statuses -> compact index,
        # even though the turn-brief file itself is still on disk.
        root = _root_with_turn_brief(status="blocked")
        self.store.upsert(obs("Redis decision", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("Redis decision", block)
        self.assertIn("danza cortex get", block)

    def test_no_team_state_with_turn_brief_file_yields_compact_index(self):
        # turn-brief.md present but no team-state.json at all -> not active.
        root = tempfile.mkdtemp()
        runtime = os.path.join(root, ".danza", "runtime")
        os.makedirs(runtime)
        with open(os.path.join(runtime, "turn-brief.md"), "w") as fh:
            fh.write("brief")
        self.store.upsert(obs("Redis decision", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)
        self.assertIn("Redis decision", block)

    # ---- fail-open on corrupted state --------------------------------------

    def test_corrupted_team_state_falls_back_to_compact_index(self):
        root = _root_with_corrupt_team_state()
        self.store.upsert(obs("Redis decision", concepts=["redis"]))
        block = build_context(self.store, "p", root=root)  # must not raise
        self.assertIn("Redis decision", block)
        self.assertIn("danza cortex get", block)


if __name__ == "__main__":
    unittest.main()
