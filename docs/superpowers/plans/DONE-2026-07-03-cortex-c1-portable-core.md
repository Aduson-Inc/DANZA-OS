# CORTEX C1 — Portable Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring CORTEX to life — capture real session events, enforce agent distillation at Stop, and inject observation context at SessionStart, all through the `danza cortex` CLI.

**Architecture:** Thin fail-open hook handlers append raw events to a repo-scoped SQLite capture log (`.danza/cortex/cortex.db`); a fail-closed-once Stop-gate forces the in-session agent to distill events into structured Observations via the existing tested `ObservationStore`; a deterministic floor extractor drafts low-confidence observations when distillation doesn't happen; SessionStart injects a token-budgeted context block. FTS5 is added to the SQLite backend for search.

**Tech Stack:** Python 3.10+ stdlib only. SQLite (WAL + FTS5). `unittest` with the existing `_bootstrap.py` pattern. Claude Code hooks JSON protocol.

**Spec:** `docs/superpowers/specs/2026-07-03-cortex-design.md` (Phase C1). This plan implements C1 only; C2 (UI, port 33000) through C6 get their own plans.

## Global Constraints

- **Stdlib only** — no pip installs anywhere in `danzaboss/` (spec D7).
- **Capture fails open** — any internal error in a hook handler logs to stderr and allows; a CORTEX bug must never brick a session (spec §4.1).
- **Stop-gate blocks at most once per session** (spec §4.2); second stop runs the deterministic floor extractor and passes.
- **Redaction before storage** — secrets never reach the DB (spec §4.1).
- **Deterministic drafts** enter at `confidence_source=speculation`, confidence 20 (spec D2/§4.3).
- **Existing P1 modules (`observation.py`, `store.py`, `ports.py`) are not modified.** `sqlite_backend.py` is only extended (FTS5 + search).
- Tests: `unittest`, file per module in `danzaboss/tests/`, first import `import _bootstrap  # noqa`. Done-bar for every task: `./danzaboss/run_tests.sh` green.
- Run single test file: `PYTHONPATH="$PWD:$PWD/danzaboss/tests" python3 -m unittest danzaboss.tests.<name> -v` from repo root — or `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.<name> -v`.
- Git: commit after every task; messages follow `feat(cortex): ...` style; end with the Claude co-author trailer used in the initial commit.
- All new DB access goes through `.danza/cortex/cortex.db` resolved from the process CWD (the repo the OS is working in) — never a hardcoded absolute path.

---

### Task 1: Redaction filter + capture log (`events.py`)

**Files:**
- Create: `danzaboss/cortex/events.py`
- Test: `danzaboss/tests/test_cortex_events.py`

**Interfaces:**
- Consumes: nothing new (stdlib `sqlite3`, `re`, `datetime`).
- Produces (used by Tasks 3, 5, 6):
  - `redact(text: str) -> str`
  - `class CaptureLog(path: str = ":memory:")` with methods:
    `open_session(session_id: str, project: str, environment: str = "") -> None`,
    `record_event(session_id: str, tool: str, file_path: str = "", command: str = "", outcome: str = "", excerpt: str = "") -> int` (returns event row id; redacts `command`/`excerpt`/`outcome`),
    `pending(session_id: str) -> list[dict]` (unprocessed events, each dict has keys `id, session_id, ts, tool, file_path, command, outcome, excerpt`),
    `mark_processed(session_id: str) -> int` (returns count marked),
    `note_observations(session_id: str, n: int = 1) -> None`,
    `mark_gate_blocked(session_id: str) -> None`,
    `session(session_id: str) -> Optional[dict]` (keys `id, project, environment, started_at, ended_at, prompt_count, observations_written, gate_blocked, status`),
    `end_session(session_id: str) -> None`,
    `stats(project: Optional[str] = None) -> dict` (keys `sessions, events, pending_events, observations_written`).

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_events.py
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.events import CaptureLog, redact


class TestRedaction(unittest.TestCase):
    def test_api_keys_and_passwords_redacted(self):
        cases = [
            "export ANTHROPIC_KEY=sk-ant-abc123def456ghi789jkl",
            "aws AKIA1234567890ABCDEF",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6",
            "password=hunter2secret",
            "postgres://admin:s3cr3t@db.example.com/prod",
        ]
        for text in cases:
            out = redact(text)
            self.assertIn("[REDACTED]", out, f"failed to redact: {text}")
        self.assertNotIn("s3cr3t", redact(cases[4]))

    def test_clean_text_untouched(self):
        clean = "edited danzaboss/cortex/events.py to add CaptureLog"
        self.assertEqual(redact(clean), clean)


class TestCaptureLog(unittest.TestCase):
    def setUp(self):
        self.log = CaptureLog(":memory:")
        self.log.open_session("s1", "danza-os", environment="claude-code")

    def test_open_session_is_idempotent(self):
        self.log.open_session("s1", "danza-os")  # second call must not raise
        sess = self.log.session("s1")
        self.assertEqual(sess["project"], "danza-os")
        self.assertEqual(sess["status"], "active")
        self.assertEqual(sess["gate_blocked"], 0)

    def test_record_event_redacts_and_is_pending(self):
        eid = self.log.record_event("s1", "Bash", command="curl -H 'Bearer sk-ant-abc123def456ghi789'")
        self.assertGreater(eid, 0)
        pending = self.log.pending("s1")
        self.assertEqual(len(pending), 1)
        self.assertIn("[REDACTED]", pending[0]["command"])
        self.assertNotIn("sk-ant", pending[0]["command"])

    def test_mark_processed_clears_pending(self):
        self.log.record_event("s1", "Edit", file_path="a.py")
        self.log.record_event("s1", "Edit", file_path="b.py")
        self.assertEqual(self.log.mark_processed("s1"), 2)
        self.assertEqual(self.log.pending("s1"), [])

    def test_observation_and_gate_counters(self):
        self.log.note_observations("s1", 3)
        self.log.mark_gate_blocked("s1")
        sess = self.log.session("s1")
        self.assertEqual(sess["observations_written"], 3)
        self.assertEqual(sess["gate_blocked"], 1)

    def test_stats_counts(self):
        self.log.record_event("s1", "Read", file_path="x.py")
        s = self.log.stats("danza-os")
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["events"], 1)
        self.assertEqual(s["pending_events"], 1)

    def test_unknown_session_returns_none(self):
        self.assertIsNone(self.log.session("nope"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_events -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.cortex.events'`

- [ ] **Step 3: Write the implementation**

```python
# danzaboss/cortex/events.py
"""CORTEX raw capture — sessions + events tables with a redaction filter (C1).

Tier-0 of the write path: hook handlers append one row per tool event, nothing
here calls an LLM. Secrets are redacted BEFORE storage so they can never become
memory (spec section 13). The Stop-gate and the floor extractor read from here.

Stdlib only.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sqlite3
from typing import Optional

_REDACTION_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),                    # provider-style API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),          # bearer tokens
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api_?key)\s*[=:]\s*\S+"),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@"),     # url with user:pass@
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    """Replace secret-shaped substrings so they never reach the store."""
    for pat in _REDACTION_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class CaptureLog:
    """Sessions + raw tool events for one project store (repo-scoped DB)."""

    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, environment TEXT DEFAULT '',
            started_at TEXT NOT NULL, ended_at TEXT,
            prompt_count INTEGER DEFAULT 0, observations_written INTEGER DEFAULT 0,
            gate_blocked INTEGER DEFAULT 0, status TEXT DEFAULT 'active')""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            ts TEXT NOT NULL, tool TEXT NOT NULL, file_path TEXT DEFAULT '',
            command TEXT DEFAULT '', outcome TEXT DEFAULT '', excerpt TEXT DEFAULT '',
            processed INTEGER DEFAULT 0)""")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, processed)")
        self.conn.commit()

    # -- sessions --------------------------------------------------------------
    def open_session(self, session_id: str, project: str, environment: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions (id, project, environment, started_at) "
            "VALUES (?, ?, ?, ?)", (session_id, project, environment, _utcnow()))
        self.conn.commit()

    def end_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'completed' WHERE id = ?",
            (_utcnow(), session_id))
        self.conn.commit()

    def session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?",
                                (session_id,)).fetchone()
        return dict(row) if row else None

    def note_observations(self, session_id: str, n: int = 1) -> None:
        self.conn.execute(
            "UPDATE sessions SET observations_written = observations_written + ? "
            "WHERE id = ?", (n, session_id))
        self.conn.commit()

    def mark_gate_blocked(self, session_id: str) -> None:
        self.conn.execute("UPDATE sessions SET gate_blocked = 1 WHERE id = ?",
                          (session_id,))
        self.conn.commit()

    # -- events ----------------------------------------------------------------
    def record_event(self, session_id: str, tool: str, file_path: str = "",
                     command: str = "", outcome: str = "", excerpt: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO events (session_id, ts, tool, file_path, command, outcome, excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, _utcnow(), tool, file_path,
             redact(command), redact(outcome), redact(excerpt)))
        self.conn.commit()
        return int(cur.lastrowid)

    def pending(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? AND processed = 0 ORDER BY id",
            (session_id,)).fetchall()
        return [dict(r) for r in rows]

    def mark_processed(self, session_id: str) -> int:
        cur = self.conn.execute(
            "UPDATE events SET processed = 1 WHERE session_id = ? AND processed = 0",
            (session_id,))
        self.conn.commit()
        return cur.rowcount

    # -- stats -----------------------------------------------------------------
    def stats(self, project: Optional[str] = None) -> dict:
        if project:
            sess = self.conn.execute(
                "SELECT COUNT(*) c FROM sessions WHERE project = ?", (project,)).fetchone()["c"]
            base = ("SELECT COUNT(*) c FROM events e JOIN sessions s ON e.session_id = s.id "
                    "WHERE s.project = ?")
            events = self.conn.execute(base, (project,)).fetchone()["c"]
            pending = self.conn.execute(base + " AND e.processed = 0", (project,)).fetchone()["c"]
            obs = self.conn.execute(
                "SELECT COALESCE(SUM(observations_written), 0) c FROM sessions "
                "WHERE project = ?", (project,)).fetchone()["c"]
        else:
            sess = self.conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
            events = self.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
            pending = self.conn.execute(
                "SELECT COUNT(*) c FROM events WHERE processed = 0").fetchone()["c"]
            obs = self.conn.execute(
                "SELECT COALESCE(SUM(observations_written), 0) c FROM sessions").fetchone()["c"]
        return {"sessions": sess, "events": events, "pending_events": pending,
                "observations_written": obs}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_events -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the full suite**

Run: `./danzaboss/run_tests.sh`
Expected: all green (124 existing + 9 new)

- [ ] **Step 6: Commit**

```bash
git add danzaboss/cortex/events.py danzaboss/tests/test_cortex_events.py
git commit -m "feat(cortex): raw event capture with sessions table and secret redaction

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: FTS5 keyword search in the SQLite backend

**Files:**
- Modify: `danzaboss/cortex/sqlite_backend.py` (extend only — `_ensure_schema`, `put`, `delete`, new `search`)
- Test: `danzaboss/tests/test_cortex_fts.py`

**Interfaces:**
- Consumes: existing `SqliteBackend`, `Observation`.
- Produces (used by Tasks 4, 6): `SqliteBackend.search(text: str, project: Optional[str] = None, limit: int = 10) -> list[Observation]` — BM25-ranked, best first; returns `[]` for blank/no-match queries.

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_fts.py
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.sqlite_backend import SqliteBackend


def obs(title, summary, project="p", **kw):
    return Observation(title=title, summary=summary,
                       type=ObsType.DECISION.value, project=project, **kw)


class TestFtsSearch(unittest.TestCase):
    def setUp(self):
        self.be = SqliteBackend(":memory:")
        self.be.put(obs("Redis chosen for JWT refresh cache",
                        "Redis holds refresh tokens to prevent races",
                        concepts=["redis", "jwt"]))
        self.be.put(obs("Postgres schema for billing",
                        "billing tables normalized to 3NF",
                        concepts=["postgres", "billing"]))

    def test_search_ranks_matching_observation_first(self):
        res = self.be.search("redis jwt")
        self.assertGreaterEqual(len(res), 1)
        self.assertIn("Redis", res[0].title)

    def test_search_scopes_by_project(self):
        self.be.put(obs("Redis elsewhere", "other repo", project="other",
                        concepts=["redis"]))
        res = self.be.search("redis", project="p")
        self.assertTrue(all(o.project == "p" for o in res))

    def test_search_handles_fts_special_chars(self):
        # quotes/operators in user text must not raise fts5 syntax errors
        res = self.be.search('redis AND "jwt" OR (cache*')
        self.assertIsInstance(res, list)

    def test_blank_query_returns_empty(self):
        self.assertEqual(self.be.search("   "), [])

    def test_delete_removes_from_index(self):
        target = self.be.search("billing")[0]
        self.be.delete(target.id)
        self.assertEqual(self.be.search("billing"), [])

    def test_put_same_id_does_not_duplicate_index(self):
        o = self.be.search("redis")[0]
        o.summary = "updated summary about redis caching"
        self.be.put(o)
        self.assertEqual(len(self.be.search("redis")), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_fts -v`
Expected: FAIL — `AttributeError: 'SqliteBackend' object has no attribute 'search'`

- [ ] **Step 3: Extend the backend**

In `danzaboss/cortex/sqlite_backend.py`, add `import re` and `Optional` is already imported. Append to `_ensure_schema` (after the index line, before `commit`):

```python
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5("
            "obs_id UNINDEXED, title, summary, tags, concepts, "
            "tokenize='porter unicode61')")
```

At the end of `put` (before nothing — replace the method body's final lines so index sync happens inside `put`), append after the existing `INSERT OR REPLACE ... execute(...)` call and before `self.conn.commit()`:

```python
        self.conn.execute("DELETE FROM observations_fts WHERE obs_id = ?", (obs.id,))
        self.conn.execute(
            "INSERT INTO observations_fts (obs_id, title, summary, tags, concepts) "
            "VALUES (?, ?, ?, ?, ?)",
            (obs.id, obs.title, obs.summary, " ".join(obs.tags), " ".join(obs.concepts)))
```

In `delete`, before `self.conn.commit()`:

```python
        self.conn.execute("DELETE FROM observations_fts WHERE obs_id = ?", (obs_id,))
```

Add the new method and module-level tokenizer:

```python
_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class SqliteBackend(StorageBackend):
    ...  # existing methods unchanged

    def search(self, text: str, project: Optional[str] = None,
               limit: int = 10) -> list[Observation]:
        """BM25-ranked keyword search. Each token is quoted so user text can
        never inject FTS5 query syntax."""
        tokens = _QUERY_TOKEN.findall(text)
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"' for t in tokens)
        sql = ("SELECT o.* FROM observations_fts f "
               "JOIN observations o ON o.id = f.obs_id "
               "WHERE observations_fts MATCH ?")
        params: list = [match]
        if project:
            sql += " AND o.project = ?"
            params.append(project)
        sql += " ORDER BY bm25(observations_fts) LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [self._decode(r) for r in rows]
```

(`_QUERY_TOKEN` sits at module level next to `_LIST_FIELDS`; `search` is a method on `SqliteBackend`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_fts -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite (existing cortex tests must stay green)**

Run: `./danzaboss/run_tests.sh`
Expected: all green — especially `test_cortex_store.py`, which exercises `put`/`delete` heavily.

- [ ] **Step 6: Commit**

```bash
git add danzaboss/cortex/sqlite_backend.py danzaboss/tests/test_cortex_fts.py
git commit -m "feat(cortex): FTS5 keyword index with BM25 search on the sqlite backend

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Deterministic floor extractor (`extract.py`)

**Files:**
- Create: `danzaboss/cortex/extract.py`
- Test: `danzaboss/tests/test_cortex_extract.py`

**Interfaces:**
- Consumes: event dicts as produced by `CaptureLog.pending()` (Task 1); `Observation`, `ObsType`, `Importance`, `ConfidenceSource` from `observation.py`.
- Produces (used by Task 6): `draft_observations(events: list[dict], project: str) -> list[Observation]` — every draft has `confidence_source == "speculation"`, `confidence == 20`, `importance == "low"`, and `evidence` naming the source events.

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_extract.py
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.extract import draft_observations
from danzaboss.cortex.observation import ObsType


def ev(tool, file_path="", command="", outcome="", excerpt="", eid=1):
    return {"id": eid, "session_id": "s1", "ts": "2026-07-03T00:00:00+00:00",
            "tool": tool, "file_path": file_path, "command": command,
            "outcome": outcome, "excerpt": excerpt}


class TestFloorExtractor(unittest.TestCase):
    def test_git_commit_becomes_impl_detail_draft(self):
        events = [ev("Bash", command='git commit -m "feat: add capture log"')]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d.type, ObsType.IMPL_DETAIL.value)
        self.assertIn("feat: add capture log", d.title)
        self.assertEqual(d.confidence, 20)
        self.assertEqual(d.confidence_source, "speculation")
        self.assertEqual(d.importance, "low")

    def test_verify_fail_becomes_limitation(self):
        events = [ev("Bash", command='python3 -m danzaboss.cli verify "pytest" .',
                     outcome="FAIL")]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(drafts[0].type, ObsType.LIMITATION.value)

    def test_verify_pass_becomes_bug_fix(self):
        events = [ev("Bash", command='python3 -m danzaboss.cli verify "pytest" .',
                     outcome="PASS")]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(drafts[0].type, ObsType.BUG_FIX.value)

    def test_edit_cluster_of_three_becomes_one_draft(self):
        events = [ev("Edit", file_path="danzaboss/cortex/a.py", eid=1),
                  ev("Edit", file_path="danzaboss/cortex/b.py", eid=2),
                  ev("Write", file_path="danzaboss/cortex/c.py", eid=3)]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(sorted(drafts[0].files),
                         ["danzaboss/cortex/a.py", "danzaboss/cortex/b.py",
                          "danzaboss/cortex/c.py"])

    def test_two_edits_are_below_cluster_threshold(self):
        events = [ev("Edit", file_path="a.py"), ev("Edit", file_path="b.py", eid=2)]
        self.assertEqual(draft_observations(events, "p"), [])

    def test_reads_and_unknown_tools_ignored(self):
        events = [ev("Read", file_path="x.py"), ev("Glob", command="**/*.py", eid=2)]
        self.assertEqual(draft_observations(events, "p"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_extract -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.cortex.extract'`

- [ ] **Step 3: Write the implementation**

```python
# danzaboss/cortex/extract.py
"""Deterministic floor extractor — CORTEX Tier 2 (C1).

When a session ends without agent distillation (crash, hookless environment,
non-compliant agent), this pass converts high-signal raw events into DRAFT
observations so nothing is fully lost. Drafts enter at speculation confidence
(20) and low importance so retrieval ranks them below distilled knowledge.

Deliberately rule-based and boring: no LLM, no heuristics beyond three rules.
"""
from __future__ import annotations

import os
import re
from .observation import Observation, ObsType, Importance, ConfidenceSource

_COMMIT_MSG = re.compile(r"""git\s+commit\b.*?-m\s+["']([^"']+)["']""")
_CLUSTER_MIN = 3  # edits in one top-level module before it counts as a cluster


def _draft(project: str, title: str, summary: str, typ: str,
           files: list[str], evidence: list[str]) -> Observation:
    return Observation(
        title=title, summary=summary, type=typ, project=project,
        importance=Importance.LOW.value, confidence=20,
        confidence_source=ConfidenceSource.SPECULATION.value,
        files=files, evidence=evidence,
        reasoning="auto-drafted by the deterministic floor extractor; "
                  "no agent distillation happened this session")


def draft_observations(events: list[dict], project: str) -> list[Observation]:
    """Apply the three floor rules to unprocessed events. Returns drafts only;
    the caller decides whether to upsert them."""
    drafts: list[Observation] = []
    edits: list[dict] = []

    for e in events:
        cmd = e.get("command", "")
        if e["tool"] == "Bash":
            m = _COMMIT_MSG.search(cmd)
            if m:
                drafts.append(_draft(
                    project, f"Commit: {m.group(1)}",
                    f"A git commit was made: {m.group(1)}",
                    ObsType.IMPL_DETAIL.value, [],
                    [f"event:{e['id']} {cmd[:120]}"]))
                continue
            if "danzaboss.cli verify" in cmd or " verify " in f" {cmd}":
                outcome = e.get("outcome", "").upper()
                if "PASS" in outcome:
                    drafts.append(_draft(
                        project, "Verification passed",
                        f"Verification command succeeded: {cmd[:120]}",
                        ObsType.BUG_FIX.value, [], [f"event:{e['id']}"]))
                elif "FAIL" in outcome:
                    drafts.append(_draft(
                        project, "Verification failed",
                        f"Verification command failed: {cmd[:120]}",
                        ObsType.LIMITATION.value, [], [f"event:{e['id']}"]))
        elif e["tool"] in ("Edit", "Write") and e.get("file_path"):
            edits.append(e)

    # rule 3: a cluster of >= _CLUSTER_MIN edits in one top-level module
    by_module: dict[str, list[dict]] = {}
    for e in edits:
        module = e["file_path"].split(os.sep)[0]
        by_module.setdefault(module, []).append(e)
    for module, group in sorted(by_module.items()):
        if len(group) >= _CLUSTER_MIN:
            files = sorted({g["file_path"] for g in group})
            drafts.append(_draft(
                project, f"Edit cluster in {module} ({len(files)} files)",
                "Files changed together this session: " + ", ".join(files),
                ObsType.IMPL_DETAIL.value, files,
                [f"event:{g['id']}" for g in group]))
    return drafts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_extract -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/cortex/extract.py danzaboss/tests/test_cortex_extract.py
git commit -m "feat(cortex): deterministic floor extractor drafting speculation-confidence observations

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: SessionStart context block builder (`inject.py`)

**Files:**
- Create: `danzaboss/cortex/inject.py`
- Test: `danzaboss/tests/test_cortex_inject.py`

**Interfaces:**
- Consumes: `ObservationStore` (existing), `Importance`; optionally a list of recently changed files.
- Produces (used by Task 6):
  - `est_tokens(text: str) -> int` (len//4 heuristic, min 1 — same convention as `memory/store.py`)
  - `rank_for_injection(store: ObservationStore, project: str, changed_files: Optional[list[str]] = None) -> list[Observation]` (best first; archives and superseded excluded)
  - `build_context(store: ObservationStore, project: str, *, max_full: int = 5, token_ceiling: int = 2000, changed_files: Optional[list[str]] = None, stats: Optional[dict] = None) -> str` — returns `""` when the store has nothing for the project.

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_inject.py
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.inject import build_context, rank_for_injection, est_tokens


def obs(title, **kw):
    kw.setdefault("summary", "s")
    kw.setdefault("type", ObsType.DECISION.value)
    kw.setdefault("project", "p")
    return Observation(title=title, **kw)


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

    def test_block_contains_index_and_full_sections(self):
        self.store.upsert(obs("Redis decision", summary="why redis",
                              reasoning="races", concepts=["redis"]))
        block = build_context(self.store, "p", max_full=1)
        self.assertIn("[CORTEX]", block)
        self.assertIn("Redis decision", block)
        self.assertIn("why redis", block)          # full body present
        self.assertIn("danza cortex get", block)   # fetch-by-id hint

    def test_token_ceiling_limits_full_bodies(self):
        for i in range(10):
            self.store.upsert(obs(f"unique topic {i}", summary="x" * 800,
                                  concepts=[f"c{i}"]))
        block = build_context(self.store, "p", max_full=10, token_ceiling=500)
        self.assertLess(est_tokens(block), 900)  # ceiling + index margin

    def test_archived_never_injected(self):
        self.store.upsert(obs("dead knowledge", importance=Importance.ARCHIVE.value,
                              concepts=["dead"]))
        self.assertEqual(build_context(self.store, "p"), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_inject -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.cortex.inject'`

- [ ] **Step 3: Write the implementation**

```python
# danzaboss/cortex/inject.py
"""SessionStart context injection — CORTEX read path, C1 version.

Builds the block a new session sees: a cheap semantic index (one line per
observation) plus the top-K full observations under a token ceiling. Ranking
here is deliberately simple (importance x confidence x recency x usage, plus a
changed-files boost); C3 replaces it with the hybrid retriever behind the same
function signature.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from .observation import Observation, Importance
from .store import ObservationStore, _IMPORTANCE_WEIGHT

_TYPE_GLYPH = {
    "bug_fix": "B", "decision": "D", "performance": "P", "dependency": "d",
    "security": "S", "api_behavior": "A", "milestone": "M", "lesson": "L",
    "root_cause": "R", "limitation": "l", "impl_detail": "i", "convention": "c",
}


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _recency_bonus(obs: Observation) -> float:
    try:
        updated = _dt.datetime.fromisoformat(obs.updated)
        age_days = (_dt.datetime.now(_dt.timezone.utc) - updated).days
    except ValueError:
        return 0.0
    return 1.0 if age_days <= 7 else (0.5 if age_days <= 30 else 0.0)


def rank_for_injection(store: ObservationStore, project: str,
                       changed_files: Optional[list[str]] = None) -> list[Observation]:
    changed = {f for f in (changed_files or [])}
    scored: list[tuple[float, Observation]] = []
    for o in store.backend.all(project):
        if o.superseded_by or o.importance == Importance.ARCHIVE.value:
            continue
        score = _IMPORTANCE_WEIGHT[o.importance] * (0.5 + o.confidence / 200.0)
        score += _recency_bonus(o)
        score += min(1.0, o.usage_count * 0.1)
        if changed and (set(o.files) & changed):
            score += 2.0
        scored.append((score, o))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return [o for _, o in scored]


def _index_line(o: Observation) -> str:
    glyph = _TYPE_GLYPH.get(o.type, "?")
    cost = est_tokens(o.summary + o.reasoning)
    return f"{o.id} [{glyph}] {o.title} (~{cost}t)"


def _full_entry(o: Observation) -> str:
    parts = [f"### {o.title}  ({o.type}, {o.importance}, conf {o.confidence})",
             o.summary]
    if o.reasoning:
        parts.append(f"Why: {o.reasoning}")
    if o.files:
        parts.append("Files: " + ", ".join(o.files[:6]))
    return "\n".join(parts)


def build_context(store: ObservationStore, project: str, *, max_full: int = 5,
                  token_ceiling: int = 2000,
                  changed_files: Optional[list[str]] = None,
                  stats: Optional[dict] = None) -> str:
    ranked = rank_for_injection(store, project, changed_files)
    if not ranked:
        return ""
    index_lines = [_index_line(o) for o in ranked[:50]]
    full_entries: list[str] = []
    used = 0
    for o in ranked[:max_full]:
        entry = _full_entry(o)
        cost = est_tokens(entry)
        if used + cost > token_ceiling:
            break
        full_entries.append(entry)
        used += cost

    parts = [f"[CORTEX] {project} — {len(ranked)} observations "
             f"(index below; bodies for top {len(full_entries)})",
             "Types: B bug_fix, D decision, S security, R root_cause, L lesson, "
             "i impl_detail, c convention, l limitation, M milestone, P perf, "
             "d dependency, A api",
             *index_lines]
    if full_entries:
        parts.append("── Top observations ──")
        parts.extend(full_entries)
    if stats:
        parts.append(f"Economics: {stats.get('events', 0)} events captured, "
                     f"{stats.get('observations_written', 0)} observations distilled "
                     f"across {stats.get('sessions', 0)} sessions")
    parts.append("Fetch details: danza cortex get <id> [<id>...]")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_inject -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/cortex/inject.py danzaboss/tests/test_cortex_inject.py
git commit -m "feat(cortex): token-budgeted SessionStart context block builder

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Distillation Stop-gate (`hooks/gates.py`)

**Files:**
- Modify: `danzaboss/hooks/gates.py` (append one gate function; do NOT add it to `run_all_gates` — that runner takes a `TurnRecord`, and this gate is fed from capture-DB counts by the CLI in Task 6)
- Test: `danzaboss/tests/test_cortex_gate.py`

**Interfaces:**
- Consumes: `Decision` from `hooks/events.py`.
- Produces (used by Task 6): `distillation_gate(pending_events: int, observations_written: int, already_blocked: bool) -> Decision`.

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_gate.py
import unittest
import _bootstrap  # noqa
from danzaboss.hooks.gates import distillation_gate


class TestDistillationGate(unittest.TestCase):
    def test_blocks_when_events_pending_and_nothing_distilled(self):
        d = distillation_gate(pending_events=7, observations_written=0,
                              already_blocked=False)
        self.assertFalse(d.allow)
        self.assertIn("7", d.reason)
        self.assertIn("danza cortex observe", d.reason)

    def test_passes_when_observations_written(self):
        self.assertTrue(distillation_gate(7, 2, False).allow)

    def test_passes_when_no_pending_events(self):
        self.assertTrue(distillation_gate(0, 0, False).allow)

    def test_blocks_at_most_once(self):
        # second stop after a block must pass (loop safety, Rule 18 spirit)
        self.assertTrue(distillation_gate(7, 0, True).allow)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_gate -v`
Expected: FAIL — `ImportError: cannot import name 'distillation_gate'`

- [ ] **Step 3: Append the gate to `danzaboss/hooks/gates.py`**

```python
# -- CORTEX distillation gate (spec 2026-07-03, section 4.2) ------------------
def distillation_gate(pending_events: int, observations_written: int,
                      already_blocked: bool) -> Decision:
    """Turn knowledge must be distilled before the session may stop. Blocks at
    most once per session: after one block (or any distillation) it passes, and
    the caller runs the deterministic floor extractor instead (Tier 2)."""
    hook = "distillation_gate"
    if pending_events == 0 or observations_written > 0 or already_blocked:
        return Decision.ok(hook)
    return Decision.deny(
        hook,
        f"{pending_events} captured events not distilled. Write what this session "
        "learned via `danza cortex observe` (JSON on stdin: title, summary, type, "
        "reasoning, when_relevant/when_not_relevant), or run "
        "`danza cortex observe --nothing-meaningful` if nothing durable happened. "
        "Then stop again.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_gate -v`
Expected: PASS (4 tests). Also run `./danzaboss/run_tests.sh` — `test_hooks.py` must stay green.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/hooks/gates.py danzaboss/tests/test_cortex_gate.py
git commit -m "feat(cortex): distillation stop-gate, fail-closed once per session

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `danza cortex` CLI command group (`commands.py` + `cli.py`)

**Files:**
- Create: `danzaboss/cortex/commands.py`
- Modify: `danzaboss/cli.py` (register the `cortex` command — 3 lines)
- Test: `danzaboss/tests/test_cortex_commands.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5 plus existing `ObservationStore`/`SqliteBackend`.
- Produces:
  - `commands.main(argv: list[str], *, root: Optional[str] = None, stdin: Optional[TextIO] = None) -> int` — `root` and `stdin` are injectable for tests; default to CWD and `sys.stdin`.
  - `commands.db_path(root: str) -> str` → `<root>/.danza/cortex/cortex.db`
  - Subcommands: `hook session-start|post-tool-use|stop` (Claude Code JSON on stdin), `observe [--session ID] [--nothing-meaningful]` (JSON object or list on stdin), `get <id>...`, `search <text...>`, `context`, `age`, `stats`.
  - Hook stdout contracts (verified against the Claude Code hooks docs and the existing `cli.py` handler):
    - SessionStart → `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<block>"}}`
    - PostToolUse → no output, exit 0
    - Stop (block) → `{"decision": "block", "reason": "<gate reason>"}`; Stop (allow) → no output, exit 0
  - ALL `hook` subcommands fail open: any internal exception prints to stderr and exits 0 with an allow-shaped (or empty) stdout.

- [ ] **Step 1: Write the failing test**

```python
# danzaboss/tests/test_cortex_commands.py
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def run(argv, root, payload=None):
    stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
    out = io.StringIO()
    with redirect_stdout(out):
        code = commands.main(argv, root=root, stdin=stdin)
    return code, out.getvalue()


class TestCortexCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        return ObservationStore(SqliteBackend(commands.db_path(self.root)))

    def test_session_start_opens_session_and_emits_context_shape(self):
        code, out = run(["hook", "session-start"], self.root,
                        {"session_id": "s1", "source": "startup"})
        self.assertEqual(code, 0)
        log = CaptureLog(commands.db_path(self.root))
        self.assertIsNotNone(log.session("s1"))
        if out.strip():  # empty store may legitimately emit nothing
            parsed = json.loads(out)
            self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"],
                             "SessionStart")

    def test_post_tool_use_records_event(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        code, out = run(["hook", "post-tool-use"], self.root,
                        {"session_id": "s1", "tool_name": "Edit",
                         "tool_input": {"file_path": "a.py"}})
        self.assertEqual(code, 0)
        log = CaptureLog(commands.db_path(self.root))
        self.assertEqual(len(log.pending("s1")), 1)

    def test_stop_blocks_once_then_floor_extracts(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Bash",
             "tool_input": {"command": 'git commit -m "feat: x"'}})
        # first stop: gate blocks
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "block")
        # second stop: floor extractor drafts, then allows silently
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        drafts = self._store().backend.all()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].confidence, 20)
        log = CaptureLog(commands.db_path(self.root))
        self.assertEqual(log.pending("s1"), [])

    def test_observe_writes_observation_and_satisfies_gate(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Edit",
             "tool_input": {"file_path": "a.py"}})
        payload = {"title": "Capture log added", "summary": "events.py capture",
                   "type": "impl_detail", "reasoning": "tier-0 write path",
                   "concepts": ["capture"], "files": ["danzaboss/cortex/events.py"]}
        code, out = run(["observe", "--session", "s1"], self.root, payload)
        self.assertEqual(code, 0)
        self.assertEqual(len(self._store().backend.all()), 1)
        # gate now passes on first stop
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(out.strip(), "")

    def test_observe_nothing_meaningful_clears_pending(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Edit",
             "tool_input": {"file_path": "a.py"}})
        code, _ = run(["observe", "--session", "s1", "--nothing-meaningful"],
                      self.root)
        self.assertEqual(code, 0)
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(out.strip(), "")

    def test_get_and_search_roundtrip(self):
        payload = {"title": "Redis for JWT", "summary": "refresh cache",
                   "type": "decision", "concepts": ["redis", "jwt"]}
        run(["observe"], self.root, payload)
        code, out = run(["search", "redis"], self.root)
        self.assertEqual(code, 0)
        results = json.loads(out)
        self.assertEqual(len(results), 1)
        obs_id = results[0]["id"]
        code, out = run(["get", obs_id], self.root)
        self.assertEqual(json.loads(out)[0]["title"], "Redis for JWT")

    def test_stats_and_age_run(self):
        code, out = run(["stats"], self.root)
        self.assertEqual(code, 0)
        self.assertIn("sessions", json.loads(out))
        code, out = run(["age"], self.root)
        self.assertEqual(code, 0)
        self.assertIn("archived", json.loads(out))

    def test_hook_fails_open_on_garbage_stdin(self):
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["hook", "post-tool-use"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 0)  # never brick the session


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_commands -v`
Expected: FAIL — `ImportError: cannot import name 'commands'`

- [ ] **Step 3: Write the implementation**

```python
# danzaboss/cortex/commands.py
"""`danza cortex` command group — the CLI surface agents and hooks call (C1).

Design rules:
  * hook subcommands FAIL OPEN (stderr + exit 0) — a CORTEX bug never bricks
    a session; same discipline as cli.py's guard hook.
  * non-hook subcommands are normal CLI: JSON out, nonzero exit on user error.
  * the store is repo-scoped: <cwd>/.danza/cortex/cortex.db
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional, TextIO

from .events import CaptureLog
from .extract import draft_observations
from .inject import build_context
from .observation import Observation
from .sqlite_backend import SqliteBackend
from .store import ObservationStore
from ..hooks.gates import distillation_gate


def db_path(root: str) -> str:
    return os.path.join(root, ".danza", "cortex", "cortex.db")


def _project(root: str) -> str:
    return os.path.basename(os.path.abspath(root))


def _read_json(stdin: TextIO) -> dict:
    raw = stdin.read()
    return json.loads(raw) if raw.strip() else {}


# ---- hook handlers (fail open) -----------------------------------------------

def _hook_session_start(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    log = CaptureLog(db_path(root))
    log.open_session(sid, _project(root), environment="claude-code")
    store = ObservationStore(SqliteBackend(db_path(root)))
    block = build_context(store, _project(root), stats=log.stats(_project(root)))
    if block:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": block}}))
    return 0


def _hook_post_tool_use(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    ti = payload.get("tool_input", {}) or {}
    resp = payload.get("tool_response", {}) or {}
    outcome = ""
    if isinstance(resp, dict):
        outcome = str(resp.get("success", ""))[:200]
    log = CaptureLog(db_path(root))
    log.open_session(sid, _project(root))  # idempotent safety net
    log.record_event(sid, payload.get("tool_name", ""),
                     file_path=ti.get("file_path") or ti.get("path") or "",
                     command=ti.get("command", ""), outcome=outcome)
    return 0


def _hook_stop(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    log = CaptureLog(db_path(root))
    sess = log.session(sid)
    if sess is None:
        return 0  # nothing captured -> nothing to gate
    pending = log.pending(sid)
    decision = distillation_gate(len(pending), sess["observations_written"],
                                 bool(sess["gate_blocked"]))
    if not decision.allow:
        log.mark_gate_blocked(sid)
        print(json.dumps({"decision": "block", "reason": decision.reason}))
        return 0
    if pending and sess["observations_written"] == 0:
        # tier-2 floor: gate already blocked once (or never applied) -> draft
        store = ObservationStore(SqliteBackend(db_path(root)))
        for d in draft_observations(pending, _project(root)):
            store.upsert(d)
    log.mark_processed(sid)
    log.end_session(sid)
    return 0


_HOOKS = {"session-start": _hook_session_start,
          "post-tool-use": _hook_post_tool_use,
          "stop": _hook_stop}


def _cmd_hook(argv: list[str], root: str, stdin: TextIO) -> int:
    event = argv[0] if argv else ""
    handler = _HOOKS.get(event)
    if handler is None:
        print(f"unknown cortex hook event: {event!r}", file=sys.stderr)
        return 0  # fail open even on bad wiring
    try:
        return handler(root, _read_json(stdin))
    except Exception as e:  # noqa: BLE001 — fail open by design
        print(f"cortex hook internal error (failing open): {e}", file=sys.stderr)
        return 0


# ---- agent-facing commands -----------------------------------------------------

def _cmd_observe(argv: list[str], root: str, stdin: TextIO) -> int:
    session_id = None
    if "--session" in argv:
        session_id = argv[argv.index("--session") + 1]
    log = CaptureLog(db_path(root))
    if "--nothing-meaningful" in argv:
        if session_id:
            log.mark_processed(session_id)
            log.note_observations(session_id, 0)
            log.mark_gate_blocked(session_id)  # gate passes on next stop
        print(json.dumps({"status": "marked", "session": session_id}))
        return 0
    try:
        payload = _read_json(stdin)
    except json.JSONDecodeError as e:
        print(f"observe: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2
    items = payload if isinstance(payload, list) else [payload]
    store = ObservationStore(SqliteBackend(db_path(root)))
    stored = []
    for item in items:
        item.setdefault("project", _project(root))
        try:
            obs = Observation(**item)
        except TypeError as e:
            print(f"observe: bad observation fields: {e}", file=sys.stderr)
            return 2
        stored.append(store.upsert(obs).id)
    if session_id:
        log.note_observations(session_id, len(stored))
        log.mark_processed(session_id)
    print(json.dumps({"stored": stored}))
    return 0


def _cmd_get(argv: list[str], root: str, stdin: TextIO) -> int:
    store = ObservationStore(SqliteBackend(db_path(root)))
    out = []
    for oid in argv:
        o = store.get(oid)
        if o:
            store.record_use(oid)
            out.append(o.to_row())
    print(json.dumps(out, indent=2))
    return 0


def _cmd_search(argv: list[str], root: str, stdin: TextIO) -> int:
    text = " ".join(argv)
    be = SqliteBackend(db_path(root))
    results = be.search(text, project=_project(root))
    print(json.dumps([{"id": o.id, "type": o.type, "title": o.title,
                       "importance": o.importance, "confidence": o.confidence}
                      for o in results], indent=2))
    return 0


def _cmd_context(argv: list[str], root: str, stdin: TextIO) -> int:
    store = ObservationStore(SqliteBackend(db_path(root)))
    log = CaptureLog(db_path(root))
    print(build_context(store, _project(root), stats=log.stats(_project(root))))
    return 0


def _cmd_age(argv: list[str], root: str, stdin: TextIO) -> int:
    store = ObservationStore(SqliteBackend(db_path(root)))
    print(json.dumps(store.age()))
    return 0


def _cmd_stats(argv: list[str], root: str, stdin: TextIO) -> int:
    log = CaptureLog(db_path(root))
    s = log.stats(_project(root))
    s["observations_stored"] = len(
        ObservationStore(SqliteBackend(db_path(root))).backend.all(_project(root)))
    print(json.dumps(s, indent=2))
    return 0


_COMMANDS = {"hook": _cmd_hook, "observe": _cmd_observe, "get": _cmd_get,
             "search": _cmd_search, "context": _cmd_context,
             "age": _cmd_age, "stats": _cmd_stats}


def main(argv: list[str], *, root: Optional[str] = None,
         stdin: Optional[TextIO] = None) -> int:
    root = root or os.getcwd()
    stdin = stdin if stdin is not None else sys.stdin
    if not argv or argv[0] not in _COMMANDS:
        print("danza cortex <hook|observe|get|search|context|age|stats> ...",
              file=sys.stderr)
        return 2
    return _COMMANDS[argv[0]](argv[1:], root, stdin)
```

Then register it in `danzaboss/cli.py`. Add the import near the other imports:

```python
from .cortex import commands as cortex_commands
```

Add a thin wrapper and registry entry (next to the other `_cmd_*` functions and inside `_COMMANDS`):

```python
def _cmd_cortex(argv: list[str]) -> int:
    return cortex_commands.main(argv)
```

```python
_COMMANDS = {"scan": _cmd_scan, "verify": _cmd_verify,
             "selftest": _cmd_selftest, "hook": _cmd_hook,
             "cortex": _cmd_cortex}
```

Also update the module docstring's command list at the top of `cli.py` to add:
`danzaboss.cli cortex <hook|observe|get|search|context|age|stats>   CORTEX memory (see docs/superpowers/specs/2026-07-03-cortex-design.md)`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_commands -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `./danzaboss/run_tests.sh`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add danzaboss/cortex/commands.py danzaboss/cli.py danzaboss/tests/test_cortex_commands.py
git commit -m "feat(cortex): danza cortex CLI group — hooks, observe, get, search, context, age, stats

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Wire the Claude Code hooks (`.claude/settings.json`) — approved `.claude/` edit

**Files:**
- Modify: `.claude/settings.json` (merge new hook events into the existing `hooks` object — do not remove the existing PreToolUse entry)
- Modify: `danzaboss/hooks/settings.example.json` (keep the example in sync)

**Interfaces:**
- Consumes: `danza cortex hook <event>` handlers from Task 6.
- Produces: live capture + injection + gate in every Claude Code session in this repo.

- [ ] **Step 1: Read the current `.claude/settings.json`**, then write the merged version (existing PreToolUse block is kept verbatim; SessionStart, PostToolUse, and Stop are added):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=\"${CLAUDE_PROJECT_DIR}\" python3 -m danzaboss.cli hook pretooluse"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=\"${CLAUDE_PROJECT_DIR}\" python3 -m danzaboss.cli cortex hook session-start"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=\"${CLAUDE_PROJECT_DIR}\" python3 -m danzaboss.cli cortex hook post-tool-use"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=\"${CLAUDE_PROJECT_DIR}\" python3 -m danzaboss.cli cortex hook stop"
          }
        ]
      }
    ]
  }
}
```

(PostToolUse matcher covers Write/Edit/Bash only — Read/Glob/Grep events are ignored by the floor extractor anyway and would bloat the events table.)

- [ ] **Step 2: Update `danzaboss/hooks/settings.example.json`** — replace its `Stop` entry's command with `python3 -m danzaboss.cli cortex hook stop` and add the same `SessionStart`/`PostToolUse` blocks, so the example reflects reality.

- [ ] **Step 3: Manual smoke test (cannot be unit-tested — hooks are fired by Claude Code itself)**

```bash
# simulate the three events end-to-end from the repo root:
echo '{"session_id":"smoke1","source":"startup"}' | PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex hook session-start
echo '{"session_id":"smoke1","tool_name":"Bash","tool_input":{"command":"git commit -m \"test\""}}' | PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex hook post-tool-use
echo '{"session_id":"smoke1"}' | PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex hook stop
```
Expected: third command prints `{"decision": "block", "reason": "1 captured events not distilled. ..."}`. Then:

```bash
echo '{"title":"smoke test obs","summary":"hook wiring works","type":"impl_detail"}' | PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex observe --session smoke1
echo '{"session_id":"smoke1"}' | PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex hook stop
PYTHONPATH="$PWD" python3 -m danzaboss.cli cortex stats
```
Expected: second stop prints nothing (allow); stats shows 1 session, 1 event, 0 pending, 1 observation.

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json danzaboss/hooks/settings.example.json
git commit -m "feat(cortex): wire SessionStart/PostToolUse/Stop hooks to danza cortex (approved .claude edit)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Agent protocol blocks + doc pointers — approved `.claude/` edits

**Files:**
- Modify: all 8 files in `.claude/agents/` (append one section each)
- Modify: `CLAUDE.md` (two small additions)

**Interfaces:**
- Consumes: the CLI surface from Task 6.
- Produces: agents that actually use CORTEX (D1's "all working Danza agents gain full and current context").

- [ ] **Step 1: Append this section verbatim to each of the 7 driver files** (`jonathan-builder`, `samantha-mapper`, `angela-auditor`, `bonnie-qa`, `carmella-researcher`, `hank-designer`, `billy-security` — exact filenames as found in `.claude/agents/`):

```markdown
## CORTEX memory protocol

Before starting work: run `danza cortex search "<your task keywords>"` and fetch
relevant hits with `danza cortex get <id>`. Cite observation IDs as evidence in
your report (Rule 43). Before reporting done: if you learned something durable
(a decision, bug root-cause, convention, limitation), emit it as JSON to
`danza cortex observe` — include `reasoning` (the why) and
`when_relevant`/`when_not_relevant` triggers. Commands run with
`PYTHONPATH=<repo-root> python3 -m danzaboss.cli cortex ...`.
```

- [ ] **Step 2: Append this extended version to `tony-d-orchestrator`** (same block PLUS orchestrator duties):

```markdown
## CORTEX memory protocol (orchestrator duties)

Everything in the driver protocol applies to you, plus: (1) when spawning a
driver, run `danza cortex search` for their task and paste the relevant
observation IDs + titles into their spawn prompt; (2) the Stop hook will BLOCK
your handoff if captured events were not distilled — write the turn's
observations via `danza cortex observe --session <session-id>` before writing
the handoff (this is the distillation gate; it blocks at most once); (3) include
"CORTEX: N observations written" in the run log as gate evidence (Rule 43);
(4) every handoff's Required Reading list (Rule 44) must include the line
`.danza/cortex/cortex.db via: danza cortex context` so the next AI loads the
project memory at session start.
```

- [ ] **Step 3: Update `CLAUDE.md`:** add to the "How to run the OS" list:

```markdown
- **CORTEX memory:** `PYTHONPATH=. python3 -m danzaboss.cli cortex <search|get|observe|context|stats>` —
  repo-scoped cognitive memory at `.danza/cortex/cortex.db` (design:
  `docs/superpowers/specs/2026-07-03-cortex-design.md`)
```

and add `danzaboss/cortex/` description in the project-layout tree comment for `danzaboss/`: change `cortex/                    CORTEX cognitive memory (observations, app-profile, store)` to `cortex/                    CORTEX cognitive memory (capture, store, FTS5, inject, extract, CLI)`.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/ CLAUDE.md
git commit -m "feat(cortex): agent CORTEX protocol blocks + CLAUDE.md pointers (approved .claude edits)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end cold-start test + acceptance verification

**Files:**
- Test: `danzaboss/tests/test_cortex_cold_start.py`

**Interfaces:**
- Consumes: the whole C1 surface via `commands.main` only (black-box).
- Produces: the C1 acceptance proof — capture → block-once → distill → inject-next-session, in one test.

- [ ] **Step 1: Write the failing-then-passing acceptance test**

```python
# danzaboss/tests/test_cortex_cold_start.py
"""C1 acceptance (spec section 8): a session captures events, blocks an
un-distilled stop exactly once, and injects context into the NEXT session."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands


def run(argv, root, payload=None):
    stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
    out = io.StringIO()
    with redirect_stdout(out):
        code = commands.main(argv, root=root, stdin=stdin)
    return code, out.getvalue()


class TestC1Acceptance(unittest.TestCase):
    def test_full_lifecycle_capture_gate_distill_inject(self):
        with tempfile.TemporaryDirectory() as root:
            # -- session 1: work happens, agent distills under gate pressure --
            run(["hook", "session-start"], root, {"session_id": "s1"})
            run(["hook", "post-tool-use"], root,
                {"session_id": "s1", "tool_name": "Edit",
                 "tool_input": {"file_path": "danzaboss/cortex/events.py"}})
            _, out = run(["hook", "stop"], root, {"session_id": "s1"})
            self.assertEqual(json.loads(out)["decision"], "block")  # gate fired
            run(["observe", "--session", "s1"], root,
                {"title": "CaptureLog is the tier-0 write path",
                 "summary": "events.py appends redacted tool events per session",
                 "type": "impl_detail", "importance": "high",
                 "reasoning": "hooks must stay thin and fail open",
                 "concepts": ["capture", "events"],
                 "files": ["danzaboss/cortex/events.py"]})
            _, out = run(["hook", "stop"], root, {"session_id": "s1"})
            self.assertEqual(out.strip(), "")                        # gate passes
            # -- session 2: the knowledge is injected --
            _, out = run(["hook", "session-start"], root, {"session_id": "s2"})
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("CaptureLog is the tier-0 write path", ctx)
            self.assertIn("[CORTEX]", ctx)
            self.assertIn("hooks must stay thin", ctx)  # reasoning survives


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the acceptance test**

Run: `cd danzaboss && PYTHONPATH="..:tests" python3 -m unittest tests.test_cortex_cold_start -v`
Expected: PASS. (If it fails, the bug is real — fix the module, not the test.)

- [ ] **Step 3: Run the complete suite one final time**

Run: `./danzaboss/run_tests.sh`
Expected: all green — 124 existing + ~40 new.

- [ ] **Step 4: Live verification in a real session** (human-in-the-loop): restart Claude Code in this repo, do a small piece of work, try to stop — confirm the gate message appears once; distill with `danza cortex observe`; start a new session and confirm the `[CORTEX]` block appears. Check `danza cortex stats`.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/tests/test_cortex_cold_start.py
git commit -m "test(cortex): C1 acceptance — capture, gate-once, distill, inject next session

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Out of scope for this plan (later phases)

- C2: web UI on port 33000 (`ui/server.py`, static SPA, SSE) — next plan.
- C3: intent detection, hybrid RRF retrieval, assembler/budget/quality, `retrieve` CLI, per-driver `context/pipeline.py` integration, explain playground.
- C4–C6: knowledge graph, learning/aging automation beyond the manual `age` command, Tier-3 LLM worker, MCP wrapper, Neon adapter, constitution rule text proposal.
