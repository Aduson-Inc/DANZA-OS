"""Row codec shared by every StorageBackend adapter (C6).

Observation <-> flat dict of TEXT columns: list fields JSON-encoded, int
fields re-widened on decode. Adapter-neutral so SQLite and Postgres store
byte-identical rows — backend parity by construction, not by discipline.
"""
from __future__ import annotations

import json
from dataclasses import fields
from typing import Any, Mapping

from .observation import Observation

LIST_FIELDS = {"tags", "concepts", "files", "symbols", "dependencies",
               "related_observations", "related_docs", "related_commits",
               "related_issues", "evidence", "when_relevant", "when_not_relevant",
               "history"}

INT_FIELDS = ("confidence", "layer", "usage_count")

COLUMNS = [f.name for f in fields(Observation)]


def encode_row(obs: Observation) -> dict:
    row = obs.to_row()
    for k in LIST_FIELDS:
        row[k] = json.dumps(row[k])
    return row


def decode_row(row: Mapping[str, Any]) -> Observation:
    """Rebuild an Observation from a stored row; extra columns (e.g. a
    Postgres tsvector) are ignored so adapters may index however they like."""
    data = {k: row[k] for k in COLUMNS if k in row.keys()}
    for k in LIST_FIELDS:
        data[k] = json.loads(data[k]) if data.get(k) else []
    for k in INT_FIELDS:
        data[k] = int(data[k])
    return Observation(**data)
