"""Weekly frontier scout (plan 01 Task 11 / Decision 7).

Opportunistic, canonical-repo-only, approval-gated scout: a research pass
(Tavily-backed) and a code-health pass (local, no network) produce human-
reviewed proposals in `.danza/frontier/`. No daemon/cron — `scout.maybe_scout`
is the one entrypoint callers hit wherever the dashboard already polls
product state; human Approve/Dismiss via `store.decide` is the only gate,
and nothing is ever auto-built.
"""
