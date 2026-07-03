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
