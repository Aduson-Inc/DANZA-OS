"""Reality Check research (design spec section 4, Phase 1.5).

Provider interface with two v1 implementations: Tavily (direct API over
stdlib urllib, urlopen injectable) and headless-boss-with-web fallback.
Research is NEVER automatic — run_reality_check (Task 4) is only invoked
from an explicit user click, which is the user approval external research
requires in every profile. Digest synthesis reuses the checkpoint
runner's subprocess + lenient JSON parse: one CLI seam, not two.
"""
from __future__ import annotations

import json
import os
import urllib.request

from danzaboss.workstation import checkpoints as checkpoints_mod

DIGEST_VERDICTS = ("saturated", "crowded_but_viable", "novel")
DIGEST_KEYS = ("verdict", "summary", "competitors", "differentiation")
TAVILY_URL = "https://api.tavily.com/search"
TAVILY_ENV = "TAVILY_API_KEY"

DIGEST_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"verdict": "saturated"|"crowded_but_viable"|"novel", "summary": str, '
    '"competitors": [{"name": str, "url": str, "note": str}], '
    '"differentiation": str}'
)


class ResearchError(ValueError):
    """Bad digest, bad provider response, or misuse. Fail closed."""


def validate_digest(digest: dict) -> dict:
    """The digest contract feeds compile_spec and Checkpoint 1 — a torn
    digest must die here, not render as a half-empty card."""
    if not isinstance(digest, dict):
        raise ResearchError("digest must be an object")
    missing = [k for k in DIGEST_KEYS if k not in digest]
    if missing:
        raise ResearchError(f"digest missing keys {missing}")
    if digest["verdict"] not in DIGEST_VERDICTS:
        raise ResearchError(
            f"digest.verdict must be one of {DIGEST_VERDICTS}")
    if not isinstance(digest["summary"], str) or not digest["summary"].strip():
        raise ResearchError("digest.summary must be non-empty text")
    competitors = digest["competitors"]
    if (not isinstance(competitors, list)
            or not all(isinstance(c, dict)
                       and isinstance(c.get("name"), str) and c["name"]
                       for c in competitors)):
        raise ResearchError(
            "digest.competitors must be objects with at least a name")
    if not isinstance(digest["differentiation"], str):
        raise ResearchError("digest.differentiation must be text")
    return digest


def build_query(answers: dict) -> str:
    """Deterministic search query from the concept phase answers."""
    parts = [answers.get("concept_what", ""), answers.get("concept_who", "")]
    similar = answers.get("concept_similar") or []
    if similar:
        parts.append("similar to " + ", ".join(similar))
    query = " ".join(p.strip() for p in parts if p and p.strip())
    if not query:
        raise ResearchError(
            "cannot research an empty concept (finish phase 1 first)")
    return query[:400]


def tavily_search(query: str, api_key: str, *,
                  urlopen=urllib.request.urlopen,
                  timeout: int = 30) -> list[dict]:
    """One Tavily call over stdlib urllib. urlopen is injectable so the
    suite proves the mapping without a network or a key."""
    payload = json.dumps({"api_key": api_key, "query": query,
                          "search_depth": "basic",
                          "max_results": 8}).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_URL, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ResearchError(f"tavily search failed: {exc}") from exc
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise ResearchError(
            f"tavily response missing results: {str(body)[:200]}")
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "content": r.get("content", "")} for r in results]


def build_digest_prompt(answers: dict, evidence: list[dict] | None) -> str:
    """Synthesis prompt. evidence=None tells a web-capable boss to gather
    its own; inline evidence means no web tools are needed at all."""
    lines = [
        "You are the DANZA Reality Check analyst. Assess this product idea "
        "against the real market: direct competitors and near-substitutes, "
        "pricing, user complaints, recent entrants or shutdowns, and "
        "whether the described angle already exists.",
        "Verdict rules: 'saturated' needs evidence-backed pushback; "
        "'crowded_but_viable' must name the wedge; 'novel' must still list "
        "the closest adjacents so the claim is falsifiable.", "",
        "Concept (JSON):",
        json.dumps(answers, indent=2, sort_keys=True), "",
    ]
    if evidence is None:
        lines.append("Use your web search tools to gather evidence first.")
    else:
        lines += ["Search evidence (JSON):",
                  json.dumps(evidence, indent=2, sort_keys=True)]
    lines += ["", DIGEST_CONTRACT]
    return "\n".join(lines)


def _synthesize(command: list[str], prompt: str, *, timeout: int) -> dict:
    """Headless synthesis call -> validated digest. Checkpoint errors
    become research errors at this boundary so callers handle ONE type."""
    try:
        raw = checkpoints_mod.run_headless(command, prompt, timeout=timeout)
        reply = checkpoints_mod.parse_json_reply(raw)
    except checkpoints_mod.CheckpointError as exc:
        raise ResearchError(f"digest synthesis failed: {exc}") from exc
    if not isinstance(reply, dict):
        raise ResearchError(f"digest is not an object: {str(reply)[:200]}")
    return validate_digest(reply)


class TavilyProvider:
    """Gather evidence via Tavily, then synthesize the digest with one
    headless boss call — the evidence rides inline, so the boss needs
    no web tools of its own."""

    def __init__(self, api_key: str, command: list[str], *,
                 urlopen=urllib.request.urlopen) -> None:
        self._api_key = api_key
        self._command = list(command)
        self._urlopen = urlopen

    def run(self, answers: dict, *, timeout: int = 180) -> dict:
        evidence = tavily_search(build_query(answers), self._api_key,
                                 urlopen=self._urlopen)
        digest = _synthesize(self._command,
                             build_digest_prompt(answers, evidence),
                             timeout=timeout)
        digest["sources"] = [e["url"] for e in evidence if e.get("url")]
        return digest


class BossWebProvider:
    """Fallback: one headless boss-with-web call does search + synthesis."""

    def __init__(self, command: list[str]) -> None:
        self._command = list(command)

    def run(self, answers: dict, *, timeout: int = 300) -> dict:
        return _synthesize(self._command,
                           build_digest_prompt(answers, None),
                           timeout=timeout)


def tavily_from_env(command: list[str],
                    env=os.environ) -> TavilyProvider | None:
    """Provider when a key is configured, None otherwise — None routes
    run_reality_check into the honest no-provider path."""
    api_key = env.get(TAVILY_ENV, "").strip()
    return TavilyProvider(api_key, command) if api_key else None
