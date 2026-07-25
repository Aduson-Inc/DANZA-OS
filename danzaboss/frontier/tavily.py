"""Tavily research pass: one deterministic query about DANZABOSS's frontier
(new multi-agent dev tools/stacks/practices), mapped straight to proposals.

Security (task 11, binding): the API key is read from the environment by the
caller (scout.py) at call time only and passed here as a plain argument —
never persisted, never logged, never echoed. Errors raised from this module
never interpolate the key or the raw request; `urlopen` is injectable so
tests prove the mapping without a network call or a real key.
"""
from __future__ import annotations

import json
import urllib.request

from .store import FrontierError

TAVILY_URL = "https://api.tavily.com/search"
TAVILY_ENV = "TAVILY_API_KEY"

RESEARCH_QUERY = ("AI coding agent orchestration frontier: new multi-agent "
                  "development tools, stacks, and best practices")
MAX_RESULTS = 5


def tavily_search(query: str, api_key: str, *,
                  urlopen=urllib.request.urlopen,
                  timeout: int = 30) -> list[dict]:
    """One Tavily call over stdlib urllib. The key rides in the POST body
    per Tavily's documented auth, never in the URL or headers, so it can
    never leak into request logs keyed on the URL."""
    payload = json.dumps({"api_key": api_key, "query": query,
                          "search_depth": "basic",
                          "max_results": MAX_RESULTS}).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_URL, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        # Deliberately generic: never interpolate the transport exception,
        # which could in principle echo request internals back to the
        # dashboard or a log (task 11 security gate).
        raise FrontierError(
            "tavily research pass failed: request error") from exc
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise FrontierError("tavily response missing a results list")
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "content": r.get("content", "")} for r in results]


def research_pass(api_key: str, *, urlopen=urllib.request.urlopen,
                  timeout: int = 30) -> list[dict]:
    """One fixed query, top MAX_RESULTS results, one proposal per result.
    Simple and deterministic on purpose — the value is the proposal +
    approval plumbing, not analysis depth (task 11 design guidance #4)."""
    results = tavily_search(RESEARCH_QUERY, api_key, urlopen=urlopen,
                            timeout=timeout)
    proposals = []
    for r in results[:MAX_RESULTS]:
        title = (r.get("title") or r.get("url") or "untitled result")[:200]
        proposals.append({
            "title": title,
            "summary": (r.get("content") or "")[:500],
            "source": "research",
            "url": r.get("url", ""),
        })
    return proposals
