# DANZABOSS — Gaps Watchlist (evidence-backed)

- team-state.json (Rule 45) did not exist -> now implemented in sandbox (Upgrade #2); still
  needs promotion into live .danza/runtime/.
- CLAUDE.md/AGENTS.md missing at root -> CLAUDE.md now authored (2026-07-01); AGENTS.md still absent.
- System never ran end-to-end -> cold-start harness added (Upgrade #6) but live wiring pending.
- Single point of failure: orchestrator mediates everything -> now guarded by StateManager +
  capabilities, but structurally still one scheduler.
- Doc-level overlap remedies (Jonathan/Bonnie, Carmella/Billy, dual onboarding) not yet
  capability-enforced. See docs/DONE-overlap-analysis-and-remedies.md.
- yt_search.py depends on unpinned yt_dlp; no requirements.txt.
