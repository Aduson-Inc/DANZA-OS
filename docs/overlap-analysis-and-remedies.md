# Overlap Analysis & Remedies — DANZABOSS

**Status:** LEGACY analysis with useful context. Mona references below are RETIRED/LEGACY. Current baseline: CORTEX is the active memory direction, while older `.danza/*.md` and `memory/store.py` surfaces still exist as overlapping/partial systems.

Goal: identify every place where two components claim the same responsibility, assign a
**single owner** to each function, and record the remedy. "Remedy" is either **code-enforced**
(a v2 module makes the overlap structurally impossible) or **doc-level** (a boundary rule added
to the affected agent/rule). Nothing is left ambiguous — every function has exactly one owner.

## Method
Cross-read all 9 agent definitions, the constitution, and the `.danza/` state files; list each
functional responsibility; flag any claimed by more than one owner; assign a single owner + remedy.

---

## O1 — Memory triple-counting (HIGH)
**Overlap:** `decision-log.md` (Angela), `turn-log.md` (Tony D), and `build-history.md` (Mona, now RETIRED/LEGACY)
all record "what happened this turn." The same event was written in three places with no
reconciliation — a divergence risk and a token waste.
**Single owner:** the **episodic memory stream** (`memory/store.py`, scope=`episodic`).
**Remedy — CODE-ENFORCED (Upgrade #7):** all three become *projections* of one append-only
event log. Angela tags decision events, Tony D tags turn events, and the retired Mona role is now represented by CORTEX build-history observations; each
"file" is just a filtered view. One write, many reads.
**Evidence:** `test_memory.py::test_append_only_persists_across_instances`, `::test_retrieve_ranks_by_relevance`.

## O2 — Jonathan self-verify vs Bonnie QA (MEDIUM)
**Overlap:** Jonathan is told to "verify your own work" and hand back "proof"; Bonnie is "the
last gate." Two agents verifying invites either double work or a false sense of done.
**Single owner of the *authoritative* gate:** **Bonnie (QA)**. Jonathan performs a *pre-flight
smoke check* only; it never counts as verification.
**Remedy — DOC-LEVEL:** boundary rule added — "Only Bonnie's PASS satisfies Constitution Rule 5.
Jonathan's self-check is a courtesy pre-flight, not a gate." Distinct verification *kinds* are
also encoded in `planning/decompose.py` (`VerificationKind`) so a task's acceptance test is
owned by the plan, not improvised by the builder.

## O3 — Carmella research vs Billy security (MEDIUM)
**Overlap:** both may investigate security topics (OWASP, OAuth, PKCE).
**Single owner split by direction:** **Carmella = inbound knowledge** ("how should X be done
securely?", external sources). **Billy = outbound audit** ("is *our* code secure?", scans the
codebase). Carmella never audits our code; Billy never does external literature research —
he asks Carmella.
**Remedy — DOC-LEVEL + CAPABILITY:** Carmella holds `research_net`, Billy does not
(`security/capabilities.py DEFAULT_GRANTS`). The capability boundary makes the split enforceable.

## O4 — Dual onboarding surfaces (MEDIUM)
**Overlap:** Tony D's `onboarding-template.md` §7 (UI/look-and-feel) duplicates Hank's built-in
"design onboarding"; Tony D's stack questions duplicate `stack-philosophy.md`.
**Single owner:** **Hank** owns all design questions; **`stack-philosophy.md`** owns all stack
guidance.
**Remedy — DOC-LEVEL:** onboarding-template §7 becomes a one-line *delegation* ("spawn Hank for
the design interview") and §8 references stack-philosophy instead of restating it. Removes ~2
duplicated question sets and the risk of divergent prompts.

## O5 — `checkpoints.json` dual ownership (LOW)
**Overlap:** listed as owned by "Samantha + Angela."
**Single owner:** **Samantha writes** checkpoints (she owns structure). Angela *contributes*
danger-zone flags through the episodic log, which Samantha reads.
**Remedy — DOC-LEVEL:** "single writer, multiple contributors" rule. Mirrors how `system-map.md`
Danger Zones are Samantha-written from Angela-sourced flags.

## O6 — `patterns.md` append-only vs "evolving" (LOW, rule conflict)
**Overlap:** Constitution Rule 36 marks `patterns.md` append-only; Mona's retired brief says patterns
"evolve/update," which contradicts append-only.
**Resolution:** patterns are **append-only records**; the "current best pattern" is a **derived
view** (latest record with confidence ≥ threshold). Nothing is edited in place.
**Remedy — CODE-ENFORCED (Upgrade #7):** `memory/store.py` is append-only; retrieval returns the
most recent/relevant, so "the current pattern" is computed, never mutated. Rule 36 upheld.

## O7 — "Exactly 2 features" vs "1–2 features" (LOW, rule conflict)
**Overlap:** Constitution Rule 3 says *exactly 2*; the SKILL prompt says *1–2*; the target model
is *configurable*.
**Resolution:** the cap becomes a **config knob** (`max_features_per_turn`), not a constant.
**Remedy — CODE-ENFORCED (Upgrade #1/#2):** relay mode defaults the knob to 2; continuous mode
sets it to `null` (no cap). Rule 3 is reinterpreted as "the relay-mode default is 2."
**Evidence:** `test_state.py::test_continuous_has_no_cap`, `test_scheduler.py::test_relay_hands_off_at_cap`.

## O8 — Orchestrator both owns state AND orchestrates its writers (LOW, structural)
**Overlap:** Tony D writes several state files *and* directs the agents who feed them → SPOF.
**Remedy — CODE-ENFORCED (Upgrade #2/#10):** state writes now go through the validated
`StateManager` (deterministic transitions + turn lock), and `write_state` is a capability held
only by the orchestrator. The concentration remains by design (single scheduler) but is now
*guarded* — an invalid or out-of-turn write fails closed instead of corrupting state.

---

## Responsibility matrix (single owner per function — nothing uncovered)

| Function | Single owner | Contributors (read/flag only) | Enforcement |
|---|---|---|---|
| Orchestration / turn control | Tony D — Orchestrator | — | `kernel/scheduler.py`, `state.py` |
| Machine turn state | Tony D (via StateManager) | — | capability `write_state` |
| Writing code | Jonathan — Builder | Hank (design assets only) | capability `write_code` |
| Codebase structure map | Samantha — Mapper | Angela (danger flags) | doc-level |
| Decisions / audit / loops | Angela — Auditor | — | episodic memory tags |
| Authoritative verification | Bonnie — QA | Jonathan (pre-flight only) | Rule 5 + decompose gate |
| External knowledge | Carmella — Researcher | Billy (requests) | capability `research_net` |
| Codebase security audit | Billy — Security | Carmella (patterns) | scheduled in back half |
| Build history / patterns | CORTEX (Mona retired/legacy) | all (emit events) | append-only episodic / observations |
| Design system | Hank — Designer | — | owns onboarding §7 |
| Turn ownership truth | `team-state.json` | all (read) | schema + turn lock |
| Event/decision history | episodic memory stream | all (tagged writes) | append-only JSONL |

## Coverage check (is everything covered?)
Every constitution responsibility, every `.danza/` state file, and every agent brief maps to
exactly one owner above. No function is unowned; no function has two owners without an explicit
contributor/owner split. Remaining SPOF (single orchestrator) is intentional and now guarded.

## Findings — room for next round
- **F1:** O2/O3/O4/O5 remedies are currently doc-level. Next round: encode the Jonathan↔Bonnie
  and Carmella↔Billy boundaries as capability checks too, so they are code-enforced like O1/O6/O7.
- **F2:** The episodic stream unifies three logs, but the *live* `.danza/*.md` files still exist
  for backward compatibility. Next round: generate those files as rendered views from the stream
  so there is truly one source, not two.
- **F3:** Responsibility matrix should itself become a machine-checkable file the self-test reads,
  so a future agent that claims an out-of-lane responsibility fails cold-start.
