---
name: danza
description: "Activate Tony-D — The Boss in a DANZA APP_BUILD project when the user asks: Who's the Boss?"
allowed-tools: Agent
---

# DANZA — Who’s the Boss?

When the user says **"Who's the Boss?"**, respond exactly:

`TONY DANZA!`

Then spawn `tony-d-orchestrator`. Tony-D — The Boss must:

1. Read `.danza/runtime/turn-brief.md` first when present — assigned units,
   last turn, and prior CORTEX knowledge in one file. Only research beyond
   it via `danza cortex search`/`danza cortex get`; do not re-scan the repo
   for facts the brief already gives.
2. Read `CLAUDE.md`, `.claude/rules/constitution.md`, `.danza/handoff.md`,
   `.danza/runtime/team-state.json`, `.danza/features.json`, and
   `.danza/plan.json` when present.
3. Determine new-project or continuation mode from the handoff and validate
   turn ownership before doing work.
4. Load relevant CORTEX context and create the next numbered run log.
5. For a new project, complete PROJECT discovery, interview, scope approval,
   and decomposition before BUILD.
6. For an approved project, select the configured quota of 2–5 verified atomic
   units from the executable plan.
7. Use `danza unit start`, delegate the unit to the authoritative named
   specialist, require Bonnie's evidence, then use `danza unit verify` and
   `danza unit conclude`. Use `danza unit block` when work cannot proceed.
8. Dispatch selectively by unit type — code → Jonathan, architecture question
   → Samantha, tests/verification → Bonnie, UI/UX → Hank, external research
   → Carmella (approval required), security-flagged unit → Billy is
   mandatory, plan audit → Angela. Never the full roster by reflex, and never
   skip a specialist the constitution mandates.
9. Update state and write a compact handoff containing pointers to canonical
   project, plan, CORTEX, and evidence files.

Tony-D orchestrates. The named specialists perform the work.
