# DANZABOSS — Overview

DANZABOSS is a multi-AI development operating system: prompts + state files that let one or
more AI environments build a *target app* under a fixed 45-rule constitution. It is NOT an app.

- Source of truth = the LOCAL repo. Never compare to GitHub; local is authoritative.
- Trigger phrase "Who's the Boss?" boots the orchestrator (Tony D).
- Execution model (as of 2026-07): evolving from "2 features per turn, relay handoff" to a
  **configurable dual-mode** system — `continuous` (loop to goal) or `relay` (handoff at cap).

## Learnings
- 2026-07-01: Repo is 32 files, ~66 KB, only 113 lines of executable code (yt_search.py). The
  "OS" is 26 markdown prompts + 3 JSON state files. System had never run end-to-end.
