# DANZA-OS Roadmap

This roadmap separates current reality from future intent.

## Current Truth

DANZA-OS is currently a real Python-based agent governance and memory toolkit with a functioning CORTEX memory subsystem. It is not yet a finished turnkey app-building OS. The end-to-end multi-agent app-building loop still needs verification and hardening.

## Near-Term Stabilization

- Documentation truth pass: keep top-level docs aligned with source reality.
- Installation audit: define and verify a clean install path.
- Test reporting: replace hardcoded test counts with current-run evidence.
- CORTEX runtime hardening: make read commands robust when global store paths are unavailable.
- Drift inventory: identify stale planning docs, legacy memory docs, and retired-agent references.

## Product Hardening

- Verify the Claude Code multi-agent app-building loop on a small real target app.
- Define the minimum supported environment and preflight checks.
- Clarify hook activation and failure modes without changing current operational settings.
- Decide how old JSONL memory and CORTEX should coexist or converge.
- Build or document a real workstation/product UI if that remains a product goal.

## CORTEX Roadmap

- Harden local/global store behavior.
- Improve observation quality and curation.
- Verify Neon/Postgres adapter with a live DSN.
- Validate dashboard behavior outside restricted sandboxes.
- Keep MCP surface read-only unless a future design explicitly approves writes.

## Not In This Docs Mission

- No runtime code changes.
- No hook changes.
- No CORTEX repairs.
- No agent prompt redesign.
- No archive/delete/cleanup actions.
- No operational Claude Code file edits.
