"""CORTEX must never read or write a cross-project global memory bank."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from danzaboss.cortex.factory import open_store
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.sqlite_backend import SqliteBackend


class ProjectOnlyCortex(unittest.TestCase):
    def test_default_store_is_project_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = open_store(str(root))
            self.assertIsInstance(store, ObservationStore)
            self.assertTrue((root / ".danza" / "cortex" / "cortex.db").is_file())

    def test_observations_never_cross_project_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            first.mkdir()
            second.mkdir()
            obs = Observation(
                title="private project decision", summary="only first",
                type=ObsType.DECISION.value, project="first",
                layer=5,
            )
            open_store(str(first)).upsert(obs)
            self.assertEqual(open_store(str(second)).backend.all("second"), [])
            self.assertIsNotNone(
                SqliteBackend(str(first / ".danza/cortex/cortex.db")).get(obs.id)
            )


if __name__ == "__main__":
    unittest.main()
