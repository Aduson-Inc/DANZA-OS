# docs/archive — frozen historical snapshots

These files are **completed-work records and superseded documentation**, moved here
2026-07-10 during a doc↔code reconciliation pass. They are kept for provenance only.
**Do not treat their contents as current** — they describe earlier states of the OS and
carry stale figures (e.g. test counts of 124 / 401 / 672 / 694; "no engine code written yet").

For current truth, read the live docs instead:
`CLAUDE.md`, `README.md`, `STATUS.md`, `ARCHITECTURE.md`, `CORTEX.md`, `ROADMAP.md`, `RUNBOOK.md`, `INSTALL.md`.

## Contents

- `DONE-CHANGELOG-REPORT.md` — 2026-07-01 build changelog snapshot (41 modules / 124 tests).
- `DONE-mission-2-plan-token-efficiency.md`, `DONE-overlap-analysis-and-remedies.md` — completed mission/analysis records.
- `10-upgrade-implementation-plan.md` — the v2 upgrade plan; all 10 upgrades have shipped into `danzaboss/`.
- `post-improvement-bottleneck-report.md` — historical audit snapshot.
- `danza-market-opportunities.md`, `danza-paid-research-tools.md` — earlier strategy/research notes (orphaned).
- `plans/DONE-*.md` — completed CORTEX (C1/C4/C6) and Workstation (W1-P1…P4) build journals. The shipped code and tests are the source of truth; these are the design records.
- `danza-memory/*.md` — the legacy `.danza/memory/` OS self-notes (2026-07-01). This role is **superseded by CORTEX** (`.danza/cortex/` + `danzaboss/cortex/`) for cognitive memory and by claude-mem for session history. No OS code read these files. Restored from git and parked for review before being archived here.

Everything is recoverable via git history (originally committed in `c023598`).
