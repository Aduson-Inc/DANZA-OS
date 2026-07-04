"""Tests for cortex.learn — C5 learning engine + aging scheduler.

C5 acceptance (spec section 8): weights shift on a replayed usage log;
expiry archives on schedule (the schedule being every session start).
"""

import datetime as dt
import io
import json
import os
import tempfile
import unittest

from danzaboss.cortex import commands
from danzaboss.cortex.learn import PROMOTE_AT, learn, replay
from danzaboss.cortex.observation import Importance, Observation
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def _store() -> ObservationStore:
    return ObservationStore(SqliteBackend(":memory:"))


def _obs(title: str, importance: str = Importance.LOW.value, **kw) -> Observation:
    return Observation(title=title, summary="s", type="impl_detail",
                       project="p", importance=importance, **kw)


class TestUsageLog(unittest.TestCase):
    def test_record_use_writes_replayable_rows(self):
        store = _store()
        o = _obs("logged")
        store.backend.put(o)
        store.record_use(o.id, source="get", now="2026-07-04T00:00:00+00:00")
        rows = store.backend.usage_log()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"obs_id": o.id,
                                   "ts": "2026-07-04T00:00:00+00:00",
                                   "source": "get"})


class TestLearn(unittest.TestCase):
    def test_replayed_usage_log_shifts_weights(self):
        """The C5 acceptance test: replay a usage log, weights move."""
        store = _store()
        o = _obs("hot", importance=Importance.LOW.value)
        store.backend.put(o)
        log = [{"obs_id": o.id, "ts": f"2026-07-04T0{i}:00:00+00:00"}
               for i in range(PROMOTE_AT)]
        self.assertEqual(replay(store, log), PROMOTE_AT)
        result = learn(store, now="2026-07-04T12:00:00+00:00")
        self.assertEqual(result["promoted"],
                         [[o.id, "low", "medium"]])
        after = store.get(o.id)
        self.assertEqual(after.importance, Importance.MEDIUM.value)
        self.assertEqual(after.history[-1]["event"], "promoted_by_learning")

    def test_promotion_never_reaches_critical(self):
        store = _store()
        o = _obs("ceiling", importance=Importance.HIGH.value, usage_count=99)
        store.backend.put(o)
        result = learn(store)
        self.assertEqual(result["promoted"], [])
        self.assertEqual(store.get(o.id).importance, Importance.HIGH.value)

    def test_use_refreshes_expiry(self):
        store = _store()
        o = _obs("alive", importance=Importance.LOW.value,
                 created="2026-07-01T00:00:00+00:00",
                 last_used="2026-07-04T00:00:00+00:00")
        store.backend.put(o)
        old_expiry = o.expires
        learn(store, now="2026-07-04T01:00:00+00:00")
        new_expiry = store.get(o.id).expires
        self.assertGreater(new_expiry, old_expiry)
        # low TTL is 14 days from last_used
        want = (dt.datetime.fromisoformat("2026-07-04T00:00:00+00:00")
                + dt.timedelta(hours=24 * 14)).isoformat(timespec="seconds")
        self.assertEqual(new_expiry, want)

    def test_learn_is_deterministic_and_stable(self):
        store = _store()
        o = _obs("stable", importance=Importance.LOW.value,
                 usage_count=PROMOTE_AT)
        store.backend.put(o)
        first = learn(store, now="2026-07-04T00:00:00+00:00")
        second = learn(store, now="2026-07-04T00:00:00+00:00")
        self.assertEqual(len(first["promoted"]), 1)   # low -> medium
        self.assertEqual(len(second["promoted"]), 1)  # medium -> high
        third = learn(store, now="2026-07-04T00:00:00+00:00")
        self.assertEqual(third["promoted"], [])       # capped at high

    def test_unused_observations_untouched(self):
        store = _store()
        o = _obs("cold")
        store.backend.put(o)
        result = learn(store)
        self.assertEqual(result, {"promoted": [], "refreshed": []})


class TestAgingSchedule(unittest.TestCase):
    def test_session_start_hook_archives_expired(self):
        """Expiry archives on schedule — the schedule is session start."""
        with tempfile.TemporaryDirectory() as root:
            store = ObservationStore(SqliteBackend(commands.db_path(root)))
            dead = _obs("stale note", importance=Importance.TEMPORARY.value,
                        expires="2020-01-01T00:00:00+00:00")
            store.backend.put(dead)
            rc = commands.main(
                ["hook", "session-start"], root=root,
                stdin=io.StringIO(json.dumps({"session_id": "s1"})))
            self.assertEqual(rc, 0)
            self.assertEqual(store.get(dead.id).importance,
                             Importance.ARCHIVE.value)

    def test_learn_cli_verb(self):
        with tempfile.TemporaryDirectory() as root:
            store = ObservationStore(SqliteBackend(commands.db_path(root)))
            o = _obs("cli hot", importance=Importance.LOW.value,
                     usage_count=PROMOTE_AT)
            store.backend.put(o)
            rc = commands.main(["learn"], root=root, stdin=io.StringIO(""))
            self.assertEqual(rc, 0)
            self.assertEqual(store.get(o.id).importance,
                             Importance.MEDIUM.value)


if __name__ == "__main__":
    unittest.main()
