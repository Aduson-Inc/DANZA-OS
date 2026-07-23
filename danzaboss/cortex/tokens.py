"""Calibrated token estimator — single home for every ``est_tokens`` call
site in the package (Task 6 Part A).

Before this module every budget decision (SessionStart injection, compress,
assemble, the turn brief, the dashboards, the PreToolUse dispatch guard) ran
its own ad-hoc ``len(text) // 4``. That one constant is a decent average for
English prose but a poor fit for source code or serialized JSON, both denser
in tokens per character. This module is the single home: one heuristic table,
calibrated per content ``kind``, plus an optional exact-counting fast path
when ``tiktoken`` happens to be installed.

Calibration table (chars-per-token, heuristic averages for the cl100k-family
tokenizers used by Claude/GPT):

    kind    chars/token   notes
    ----    -----------   -----
    prose   ~4.0          English markdown/prose (CORTEX summaries, briefs)
    code    ~3.3          source code: more punctuation, denser tokenization
    json    ~3.0          serialized JSON: quotes/braces/commas inflate count

These are heuristic *estimates*, not exact counts — budgets built on top of
them are approximate by design. Constants are expressed as chars-per-token
times 10 (``_DIVISOR_X10``) so the heuristic path stays integer-only math;
the ``kind="prose"`` default divides by exactly 4, preserving the legacy
``len(text) // 4`` behavior byte for byte.

The package is stdlib-only by policy, so ``tiktoken`` is NEVER a hard
dependency: the import is attempted once at module load inside a bare
``try/except ImportError`` and the resulting encoder handle is exposed as
the module-level ``_ENCODER`` (``None`` when tiktoken is absent, or the
import/encoding-load itself failed). ``est_tokens`` checks that handle on
every call — not a value captured once into a closure — so tests can
monkeypatch ``tokens._ENCODER`` directly to exercise the precise-mode path
without installing the real package.
"""
from __future__ import annotations

_DIVISOR_X10 = {
    "prose": 40,   # ~4.0 chars/token
    "code": 33,    # ~3.3 chars/token
    "json": 30,    # ~3.0 chars/token
}
_DEFAULT_KIND = "prose"

try:
    import tiktoken as _tiktoken  # type: ignore
except ImportError:
    _tiktoken = None


def _load_encoder():
    """Best-effort tiktoken encoder handle, or None if unavailable/broken.

    Any failure here (missing package, missing encoding data, whatever) is
    swallowed — tiktoken is a nicety, never a requirement.
    """
    if _tiktoken is None:
        return None
    try:
        return _tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - optional dependency, fail soft
        return None


_ENCODER = _load_encoder()


def est_tokens(text: str, kind: str = "prose") -> int:
    """Estimate the token cost of ``text``.

    ``kind`` selects the heuristic divisor (see module docstring table);
    unknown kinds fall back to ``prose``. When a working tiktoken encoder is
    available (``_ENCODER`` is not None), it is used for an exact count
    instead of the heuristic — transparently, regardless of ``kind`` — and
    any error during encoding falls back to the heuristic rather than
    raising, since token estimation must never be the reason a caller fails.

    Returns 0 for empty text, otherwise an int >= 1. Never negative.
    """
    if not text:
        return 0
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:  # noqa: BLE001 - fall back to heuristic on any error
            pass
    divisor_x10 = _DIVISOR_X10.get(kind, _DIVISOR_X10[_DEFAULT_KIND])
    return max(1, (len(text) * 10) // divisor_x10)
