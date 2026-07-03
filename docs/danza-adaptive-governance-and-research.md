# DANZA — Adaptive Governance + Research Loop (build reference)

Single reference for the batch built this round. Everything here is **app-agnostic** (profile-driven,
ports + adapters) and **unit-tested** unless explicitly labelled as needing live credentials.

**Test status:** full test suite **116 tests green** (was 76; +40 this batch). Run: `./danzaboss/run_tests.sh`.

---

## 1. Governance hooks (`danzaboss_v2/hooks/`) — 23 tests

The "when" layer that fires the existing "what" (capabilities, trace, state, harness) at Claude Code
lifecycle events. Guards fire only on the dangerous/dishonest minority of actions; trivial work is never slowed.

| Hook | Event | Enforces | Rule(s) |
|---|---|---|---|
| `capability_guard` | PreToolUse | orchestrator can't write code; only `jonathan-builder` | 42, Upgrade #10 |
| `hard_stop_guard` | PreToolUse | auth/payment/schema/delete need user elevation | 13–16 |
| `turn_lock_guard` | PreToolUse | only current boss writes turn state (W1 defense-in-depth) | 38, 45 |
| `file_protection_guard` | PreToolUse | templates read-only, `.claude/` immutable, logs append-only | 34–37 |
| `scope_guard` | PreToolUse | no build action outside the approved plan (anti gold-plating) | — |
| `context_budget_guard` | PreToolUse | reject oversized sub-agent dispatch → use compiled context | token discipline |
| `anti_theatre_gate` | Stop | claimed sub-agent work must have trace/SubagentStop evidence | 42–43 |
| `verify_before_done_gate` | Stop | a feature is done only with a passing verification | 5 |
| `regression_gate` | Stop | test suite/harness must be green before handoff | never-regress |

`dispatcher.py` maps events → guards/gates (first denial wins, fail-closed). `settings.example.json` is
the Claude Code wiring — **verify event names + return contract against the live hooks docs before use**;
the logic itself is pure and tested.

## 2. App Profile (`danzaboss_v2/cortex/app_profile.py`) — 6 tests

The adaptability foundation. DANZA **learns any app** into an `AppProfile` (stack, domain, features,
goals, conventions, config) and every agent/script/query reads it at runtime — no app-specific literals.
`learn_profile()` consumes language-agnostic scan facts; `diff_profiles()` detects change (e.g. a stack
migration) so DANZA **adjusts**. Proven app-agnostic by tests across a TS/Neon app and a Python/SQLite app.

## 3. Research loop (`danzaboss_v2/research/`) — 11 tests

The "research team that grills you" loop, entirely profile-parameterized:

- `sources.py` — **MultiSourceCollector**: fuses lanes (web / youtube / github / rss / arxiv as swappable
  `SourceLane` ports), dedupes, ranks **newest-first**. Honest design: YouTube is *one* lane, not the star,
  because video lags written sources for technical research.
- `summarizer.py` — **Summarizer port**: DANZA hands off URLs + a brief and reads only the distilled
  result (token win). NotebookLM adapter present but **fragile/unverified** → swappable (see §5).
- `proposal.py` — **Proposal**: the chat message you approve/deny remotely.
- `throttle.py` — **ProposalThrottle**: ceiling-not-quota, impact gate, scheduled windows — all config.
- `messaging.py` — **MessagingChannel port**: Console adapter (tested) + Telegram adapter (documented).
- `squad.py` — **ResearchSquad**: per big feature → collect → summarize → propose → throttle → send.
  Deep research only for `is_big` features (cost control).

## 4. Paid research tools — recommendation (see `danza-paid-research-tools.md`)
- **Pay for the summarizer:** make **Perplexity Sonar** (or Firecrawl deep-research) the default; it's an
  official cited-answer API — more reliable + better than NotebookLM automation, for single-digit $/mo.
- **Start free on the collector:** **Tavily** free tier (1,000/mo), add **Exa** for big features.
- Keep NotebookLM only as a $0 fallback. All swap behind the ports already built.

## 5. Honest integration ledger (what's tested vs what needs credentials)

| Piece | Status |
|---|---|
| All guard/gate logic, App Profile, collector ranking, throttle, proposal, squad orchestration | ✅ built + unit-tested |
| Claude Code hook wiring (`settings.json`) | ◑ example provided; **verify against live hooks API** |
| NotebookLM summarizer | ⚠️ **could not verify here** — no CLI, no `yt_dlp`, Google network blocked (403). Verify on your machine, or replace with a paid API |
| Telegram/live messaging | ◑ port + adapter written; needs bot token + chat id |
| Live source lanes (web/youtube/github APIs) | ◑ ports written; need API keys/network |

## 6. What remains (next rounds)
- Wire hooks into live Claude Code `settings.json` (after API verification).
- Bind a real collector lane (Tavily) + summarizer (Perplexity Sonar) with keys.
- Feed `learn_profile()` from Samantha's real repo scan (tree-sitter analyzers).
- Connect the approval reply path (`parse_reply`) back into `scope_guard`'s approved-task set,
  closing the loop: remote APPROVE → task becomes buildable.
- CORTEX P2+ (knowledge graph, hybrid retrieval, assembler) remains separate roadmap.

*Nothing app-specific was hardcoded. No integration was claimed to work that was not verified.*
