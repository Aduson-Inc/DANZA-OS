# CORTEX Status

CORTEX is REAL and currently the strongest implemented subsystem in DANZA-OS.

It is a local memory/context system built around observations, capture logs, retrieval, graph links, and context assembly. It is not merely conceptual scaffolding.

## What Is Real

- Observation model with confidence, relevance controls, history, and lifecycle fields.
- SQLite persistence with FTS5 search.
- Session/event capture log with redaction.
- Observation merge/upsert behavior.
- Usage logging and deterministic learning by usage-count promotion.
- Retrieval package builder with intent detection, ranking, budget assembly, quality scoring, and explain traces.
- Knowledge graph storage and traversal.
- Local web dashboard for memory, console, workflow, stats, settings, explain, and graph views.
- MCP stdio read surface for search/get/retrieve/context.

## What Is Partial

- Default global federation can be environment-sensitive because it may open `~/.danza/cortex/global.db`.
- The current memory content is mostly DANZA-OS build history and implementation observations, not a validated user-app knowledge base.
- Learning is deterministic usage promotion, not semantic model training.
- Neon/Postgres support exists as an adapter but requires optional driver and live DSN verification.
- Dashboard is local-only and focused on CORTEX, not the whole DANZA product.

## What Is Not Current Reality

- CORTEX is not a hosted SaaS product.
- CORTEX does not make the full app-building OS turnkey by itself.
- CORTEX does not eliminate the older memory/context surfaces yet.
- CORTEX does not prove the Claude multi-agent build loop end to end.

## Persistence Reality

Known local CORTEX state exists under `.danza/cortex/cortex.db` for this repo. Audit evidence found observations, sessions, events, graph nodes, graph edges, and usage logs.

A second nested CORTEX database was also observed under `danzaboss/.danza/cortex/cortex.db`; that is a duplicate-state smell to address later, but this docs-only mission does not modify databases.

## Current Verdict

Status: REAL/PARTIAL.

CORTEX functions as a local memory/context system today. It still needs hardening around install defaults, global-store behavior, memory quality, and integration with the full agent loop.
