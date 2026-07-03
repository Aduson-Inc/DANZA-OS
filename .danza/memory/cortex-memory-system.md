# CORTEX — Cognitive Memory & Context System

Design decision (2026-07): DANZA OS will host a cognitive memory/context system, codename CORTEX,
that every project DANZA builds inherits. Positioned as an upgrade over claude-mem, memsearch, CTX,
context-mode (which do transcript-compression + hybrid keyword/vector + progressive disclosure).

CORTEX adds what they lack: typed knowledge graph + traversal ("what breaks if X changes"),
layered memory L0-L5 with per-layer policy, intent-driven dynamic token budget, observation
evolution/merge + confidence + when_relevant/when_not anti-relevance, decision memory (the WHY),
cross-project reusable knowledge (L5), context quality scoring, explainability, multi-signal RRF
fusion, language-agnostic analyzers (tree-sitter).

Key locked decisions:
- Engine lives in DANZA (Python); understands ANY target-app stack (TS/Python/etc.) via pluggable
  language analyzers. Tre's SaaS is now mostly TypeScript on Neon DB — non-issue for engine language.
- Multi-stack/multi-DB via ports+adapters. Storage: SQLite local default + Neon/Postgres shared.
- Exposed to external tooling (TS SaaS, Claude Code) via MCP wrapper.
- Builds on v2 seeds: memory/store.py -> ObservationStore; context/pipeline.py -> ContextAssembler.

Deferred ADR-002 (embeddings): recommendation = pluggable, off by default, auto-enable when a
VectorIndex adapter (Neon+pgvector or local ONNX) is bound. Decide with a retrieval eval at P3.

Spec: docs/cognitive-memory-architecture.md. First deliverable was the architecture spec
(Tre chose spec-first). No engine code written yet; roadmap P1-P8 defined.

## Build log
- 2026-07-01: ADRs approved by Tre. P1 BUILT + TESTED. New package danzaboss/cortex/:
  observation.py (full Observation schema: reasoning, when_relevant/when_not, confidence sources,
  importance+TTL aging, evolution history), ports.py (StorageBackend port + Query/Scored),
  sqlite_backend.py (ADR-005 SQLite adapter, stdlib sqlite3), store.py (ObservationStore L2:
  evolve/merge upsert, anti-relevance-aware query, aging). 14 new tests; both P1 acceptance
  criteria proven: (1) upsert merges near-duplicates instead of duplicating; (2) when_not_relevant
  measurably raises precision. Full suite now 76 tests green. W1 turn-lock fix re-verified (6/6).
- NEXT (Tre's request): discuss adding HOOKS to prevent arbitrary self-reassigning agents
  (defense-in-depth on top of the W1 state.py fix). Then P2 (knowledge graph + repo intelligence).

## Market/opportunity research (2026-07-01)
Scan of trending agentic systems + integration/revenue paths in docs/danza-market-opportunities.md.
Key: OpenClaw (self-host, 50+ connectors, ~210k stars), Hermes Agent (Nous Research MIT, self-host,
multi-layer memory, task->reusable-skill capture, Telegram-driven; Hostinger offers Managed Hermes VPS)
is DANZA's strongest integration target. DANZA's positioning = the GOVERNED conductor (constitution +
verifiable tasks + capability security + CORTEX) the ecosystem lacks; other tools are connectors/drivers/
runtimes/channels. Top play sequence: headless DANZA on VPS -> Hermes<->DANZA MCP bridge -> multi-model
driver adapter (Claude/Codex/Grok/Gemini) -> Make/n8n/Vapi action+voice layer. Revenue: autonomous-dev
retainer $2-5k/mo, managed VPS, CORTEX memory SaaS $19-49/mo, skill marketplace, Skool community.

## Catch-up build (2026-07-01, batch)
Built + tested (116 tests total, all green): (1) Governance hooks danzaboss_v2/hooks/ (6 PreToolUse guards
+ 3 Stop gates + dispatcher + settings.example.json; anti-theatre/verify/regression spine; app-agnostic).
(2) App Profile danzaboss_v2/cortex/app_profile.py (learn ANY app -> profile drives everything at runtime;
diff detects migrations; proven across TS/Neon + Python/SQLite). (3) Research loop danzaboss_v2/research/
(MultiSourceCollector w/ swappable SourceLane ports, newest-first; Summarizer port; Proposal; ProposalThrottle
ceiling-not-quota+impact+windows; MessagingChannel port; ResearchSquad, deep-research only for is_big features).
Paid-tools verdict: pay for summarizer (Perplexity Sonar/Firecrawl > fragile NotebookLM), start free collector
(Tavily), Exa for big features. NotebookLM could NOT be verified here (no CLI/yt_dlp, Google blocked 403) -
reported honestly. Docs: danza-adaptive-governance-and-research.md, danza-paid-research-tools.md.
Next: wire hooks to live CC settings (verify API first), bind Tavily+Sonar keys, feed profile from Samantha scan,
close approval->scope_guard loop. CORTEX P2+ still roadmap.

## Consolidation into one working set (2026-07-01)
Promoted the Python brain out of sandbox to an authoritative root package `danza/` (package
renamed danzaboss_v2 -> danza; all imports/tests updated; 124 tests green at new location).
Added runtime glue: danza/runtime/scan.py (learn AppProfile from ANY real repo, heuristic
language/framework detection), verify.py (run target app's real tests -> pass/fail QA gate),
runner.py (DanzaSession binds a target dir). Added danza/cli.py — the entrypoint agents + hooks
call: `danza scan|verify|selftest|hook`. Wired .claude/settings.example.json to route CC hooks to
`python3 -m danzaboss.cli hook ...` (NOT active until renamed + API verified). Promoted docs -> docs/.
Wrote RUNBOOK.md (drop app -> scan -> Who's the Boss? -> verify). CLAUDE.md updated to danza/ layout.
Model = Claude Code-native (agents build; danza/ = brain+guards+verify). danzaboss/ authoritative; sandbox/ later deleted by Tre
(Cowork blocks delete). Live end-to-end proven: learns a fake TS/Next app, verify pass/fail works,
hooks block orchestrator code-write + allow builder. NOT yet run: the actual "Who's the Boss?" agent
build loop on a real app (runs in Claude Code where agents are registered).
