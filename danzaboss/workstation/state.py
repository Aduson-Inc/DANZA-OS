"""Wizard state persistence into a TARGET repo's .danza/onboarding/.

Rule 35 discipline in code: read-then-merge and atomic replace, so a save
never blind-overwrites what another writer put on disk, and a crash never
leaves a torn file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_RELPATH: Path = Path(".danza") / "onboarding" / "answers.json"


def state_path(root: str | os.PathLike) -> Path:
    """Where this target repo's wizard state lives."""
    return Path(root) / STATE_RELPATH


def load_state(root: str | os.PathLike) -> dict[str, Any]:
    """Current wizard state, or an empty shape. Fails closed on a file
    that exists but is not a JSON object.

    Deliberate asymmetry with save_state: loading corrupt state raises
    (the reader must not act on garbage), while saving over corrupt
    state heals it (the writer's merged snapshot is the best truth
    available and an atomic replace cannot make things worse)."""
    raw: dict[str, Any] = {}
    path = state_path(root)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"corrupt wizard state (not an object): {path}")
    raw.setdefault("answers", {})
    raw.setdefault("steps", {})
    return raw


def save_state(root: str | os.PathLike, state: dict[str, Any]) -> None:
    """Merge answers/steps over what is on disk, then atomic-replace.

    Unlike load_state, a corrupt on-disk file does not raise here — it
    is replaced wholesale (see load_state docstring for why)."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    on_disk: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                on_disk = loaded
        except (json.JSONDecodeError, OSError):
            on_disk = {}
    on_disk["answers"] = state["answers"]
    on_disk["steps"] = state["steps"]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(on_disk, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
