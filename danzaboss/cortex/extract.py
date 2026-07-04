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
from .observation import (CONFIDENCE_OF, ConfidenceSource, Importance,
                          Observation, ObsType)

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


# ---- ExtractorPort + adapters — CORTEX Tier model (C5) -------------------------
#
# Tier 1 (agent distillation) happens outside this module via the Stop-gate.
# Tier 2 is draft_observations above. Tier 3 is an OPTIONAL background LLM
# worker: off by default, enabled only by explicit configuration, and it
# fails open — a broken worker must never cost a session its Tier-2 floor.

import json
import shlex
import subprocess
from typing import Optional, Protocol


class ExtractorPort(Protocol):
    """Turn a session's unprocessed events into draft Observations."""
    def extract(self, events: list[dict], project: str) -> list[Observation]: ...


class DeterministicExtractor:
    """Tier-2 floor behind the port, so callers can treat tiers uniformly."""
    def extract(self, events: list[dict], project: str) -> list[Observation]:
        return draft_observations(events, project)


class LLMWorkerExtractor:
    """Tier 3: shell out to a configured worker command.

    Contract: events JSON on stdin -> JSON list of observation dicts on
    stdout. Events are already redacted at capture time (events.redact),
    so nothing un-redacted can leave the process. Drafts are clamped to
    llm_inferred confidence at most so a worker cannot mint authority.
    """

    def __init__(self, command: str, timeout: int = 60):
        self.command = command
        self.timeout = timeout

    def extract(self, events: list[dict], project: str) -> list[Observation]:
        try:
            proc = subprocess.run(
                shlex.split(self.command), input=json.dumps(events),
                capture_output=True, text=True, timeout=self.timeout)
            if proc.returncode != 0:
                return []
            items = json.loads(proc.stdout)
            if not isinstance(items, list):
                return []
        except (OSError, ValueError, subprocess.SubprocessError):
            return []  # fail open: Tier 2 already secured the floor
        drafts: list[Observation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item["project"] = project
            item["confidence"] = min(
                int(item.get("confidence", 60)),
                CONFIDENCE_OF[ConfidenceSource.LLM_INFERRED])
            item.setdefault("confidence_source",
                            ConfidenceSource.LLM_INFERRED.value)
            try:
                drafts.append(Observation(**item))
            except TypeError:
                continue  # skip malformed items, keep the rest
        return drafts


def configured_extractor(root: str) -> Optional[LLMWorkerExtractor]:
    """Resolve the Tier-3 worker: env DANZABOSS_TIER3_CMD wins, then
    .danza/cortex/tier3.json {"command": ...}. Absent both -> None (default)."""
    cmd = os.environ.get("DANZABOSS_TIER3_CMD", "")
    if not cmd:
        path = os.path.join(root, ".danza", "cortex", "tier3.json")
        try:
            with open(path, encoding="utf-8") as fh:
                cmd = json.load(fh).get("command", "")
        except (OSError, ValueError):
            cmd = ""
    return LLMWorkerExtractor(cmd) if cmd else None
