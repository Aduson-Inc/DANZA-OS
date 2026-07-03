# DANZABOSS — Architecture

OS-layer mapping: boot loader (SKILL.md) -> kernel (constitution + orchestrator) -> 8 drivers
(specialist agents) -> state services (.danza/) -> reference config (templates) -> external
tools (research pipeline). Topology is a STAR: only the orchestrator spawns drivers; drivers
never call each other. Coordination is via the orchestrator + shared .danza/ files (blackboard).

## Agent roster (role-tagged names, renamed 2026-07-01)
- tony-d-orchestrator (Tony D — Orchestrator): kernel; only agent that spawns others
- jonathan-builder (Jonathan — Builder): ONLY agent that writes code
- samantha-mapper (Samantha — Mapper): 6-pass system map
- angela-auditor (Angela — Auditor): decisions, loops, alerts
- bonnie-qa (Bonnie — QA): authoritative verification gate
- carmella-researcher (Carmella — Researcher): external knowledge (YouTube+NotebookLM)
- hank-designer (Hank — Designer): design tokens/templates
- billy-security (Billy — Security): OWASP/auth audit, back half of build

## Learnings
- 2026-07-01: Agent files renamed to carry role in name + heading + all Agent()/subagent_type
  refs + constitution roster. Filenames now match ids (e.g. tony-d-orchestrator.md).

## Learnings
- 2026-07-01: Agent roster consolidated 9 -> 8. mona-historian RETIRED (redundant): its function (build history, patterns, build orders, learning) is now owned by CORTEX in code. All references rerouted to CORTEX; removed from Tony D tool grants + constitution roster + CLAUDE.md. File tombstoned (Cowork blocks hard delete).
