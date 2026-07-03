# Mission 2 Plan — Token Efficiency & Wiring the Dead 60%

**Author:** Fable (Layer 0, Chief Systems Architect) · **Date:** 2026-07-02
**For:** the next session's architect. Read this before touching anything.
**Status:** PROPOSED — approved by the user for handoff; not yet implemented.

---

## 0. READ FIRST — you are on a different machine now

This doc was written on the user's **Windows 11 laptop**. The repo is being moved to a **Linux machine running Claude Code**. Consequences:

1. **Machine-specific findings do NOT transfer.** The `python3`-is-a-broken-Store-stub problem, missing `yt_dlp`, and "no git" were properties of the old laptop. On Linux, `python3` will exist and the 3 `/tmp` test errors (§1) will not reproduce (they were POSIX-only tests failing on Windows — expect **124/124 green on Linux**). Still ship P0.2 and P0.3: the defect is **single-interpreter fragility and POSIX-only tests**, not Windows itself. The OS must run on both.
2. **My session memory and scratchpad do not exist there.** Any reference in this doc to sandbox paths or session memory is dead; this doc + the repo are the only carriers of the findings. The activation-simulation evidence (F1 built with 36 passing tests, agent honesty, 5x ceremony multiplier) cannot be re-inspected — re-derive by re-running a sandboxed activation if needed.
3. **NEW P0 ITEM — highest priority: environment preflight gate ("work anywhere or stop and ask").** The user's requirement: DANZABOSS must either run correctly in any environment or **stop BEFORE doing anything and tell the user exactly which dependencies are missing**. Implement as `danza doctor` (or extend `selftest`): check interpreter resolution (python3/python), git presence, write access, `.danza/` integrity, optional deps (`yt_dlp`), and available MCP tools (Rule 41). Wire it as **step 0 of Tony D's startup sequence**: doctor fails → STOP, print the missing-dependency list to the user, do not proceed (fail-closed, Rules 2/20). This replaces the luck we had this session, where activation only survived the broken `python3` because session memory leaked the workaround.
4. **The new machine has `claude-mem` and `CTX` tools.** Before implementing P4 (CORTEX wiring): run the Rule 41 capability scan, and evaluate whether claude-mem/CTX can serve as (or complement) the CORTEX backend. Rules of engagement: (a) do not build a parallel memory system if the environment already provides one that fits; (b) but the OS must NEVER hard-depend on them — they won't exist on other machines. CORTEX's core must stay stdlib + repo-local (`cortex/ports.py` already defines the adapter seam); environment tools plug in as optional adapters behind a doctor check. Record whatever you decide in `.danza/memory/` and the decision log.
5. **Re-establish baselines on arrival before changing anything:** `./danzaboss/run_tests.sh` (expect 124/124), `PYTHONPATH=. python3 -m danzaboss.cli selftest` (expect 8/8), the four hook-guard probes from §1 (deny/deny/ask/allow), and `git init` if the copy still isn't a repo. Then proceed P0 → P6.

---

## 1. What happened this session (evidence, condensed)

**Mission 1 audit (repo = Layer 1 blueprint, read-only):** 124 tests exist (121 pass on Windows; 3 errors = `/tmp` hardcoded in `test_runtime.py:55,59,63`). CLI `selftest` 8/8, `scan`/`verify`/`hook` all work with `python` (NOT `python3` — broken Store stub on this machine). ~17 of 28 brain modules are dead code (gates, dispatcher, CORTEX store, memory store, context pipeline, tracer, parallel planner, research squad, DanzaSession). Registered PreToolUse hook in `.claude/settings.json` calls `python3` → **inert on Windows, fails open silently**. INSTALL.md and RUNBOOK.md contradict each other on hook activation.

**Layer-2 activation simulation (sandboxed copy, greenfield):** Triggered "Who's the Boss?" → Tony D ran a real turn: mode detection ✔, run log 001 ✔, Angela genuinely spawned ✔, honest selftest ✔, active onboarding with real Carmella research (pipeline-offline honestly flagged) ✔, Hank produced real design tokens ✔, `team-state.json` correctly bootstrapped from Rule 45 text alone ✔ (refuting predicted defect D1 behaviorally — but it depended on model diligence, not mechanism), CORTEX consult honestly reported "empty, fresh system" ✔ (D4's theatre risk didn't fire, but the prompt's "auto-records" claim is still false). Jonathan built **F1 (gig-tracking core): ~15 files, 36 tests, independently re-run PASS**, found and fixed a real Windows port-reuse bug, flagged honest unknowns. Angela audited all 5 of his decisions against source. Samantha wrote a full system map and found a real latent defect (`venues.usual_rate` write-orphan). **F2 was killed mid-build by user stop.** Bonnie's gate, self-assessment, handoff, takeover mode, and relay were **never observed** — still unverified.

**Sandbox (this session's scratchpad, will be deleted):** `...\scratchpad\sandbox-greenfield\` — resumable state lives in its `.danza/` files if the session still exists; otherwise re-run activation fresh after implementing this plan.

---

## 2. The four questions, answered with numbers

### Q1: Was it token efficient? — NO.

Reported subagent token counters for the activation run:

| Agent | Tokens | Output |
|---|---|---|
| Tony D (6 legs: 39k→47k→54k→91k→100k→105k) | ~436k | coordination only — wrote no code |
| Jonathan (F1) | ~84k | the actual app + 36 tests |
| Samantha (map) | ~69k | system-map.md |
| Angela (2 runs) | ~54k | decision log entries |
| Carmella (research) | ~30k | onboarding research |
| Jonathan (F2, killed) | partial | unfinished |
| **Total** | **~700k+** | **ONE verified feature** |

**Headline metric: the ceremony multiplier is ≈ 5x.** Jonathan's 84k of real building carried ~350k+ of orchestration, auditing, mapping, and re-narration. Tony D's context grew 39k→105k per leg because every driver report was delivered to him in full and he re-summarized it — the same content was processed 3-4 times (driver writes it → orchestrator reads it → orchestrator re-tells it → logs duplicate it). Mission 1's audit added ~220k more (justified, one-time). Session total crossed ~1M.

### Q2: Does every agent need to run every turn/feature? — NO, but the blueprint currently says they must.

`tony-d-orchestrator.md` Phase 2 mandates **Samantha → Jonathan → Samantha → Angela per feature**, plus Bonnie per turn, plus Rule 6 ("After every feature: Samantha updates the map, Angela logs..."). Observed cost of that ceremony on a single low-risk feature: Samantha 69k + Angela 37k = ~106k of review for 84k of build — before Bonnie even ran. The fixed pipeline ignores risk: a money-math feature and a CSS tweak get identical ceremony. Only **Bonnie** is the constitutional gate (Rule 5); everyone else's cadence should be risk-tiered (see §4-P2).

### Q3: How big is a feature, who decided, how? — Nobody defined it; that's the root defect.

- Rule 3 (constitution) fixes the **count**: exactly 2 features/turn. It never defines a feature's **size**.
- Observed: Tony D sized features unilaterally during onboarding (roadmap F1-F6). F1 became a mega-feature — schema + server + static shell + quick-add + venue memory + full test suite (~5 features of work labeled "1"), while F2 (money dashboard) was maybe a fifth of that. "2 features per turn" with undefined size = unbounded turns.
- The blueprint ALREADY contains the fix, unwired: `danzaboss/planning/decompose.py` (verifiable-task gate: every leaf task needs a concrete verification — tested, dead) and `danzaboss/planning/spec_template.md` + `plan_schema.json` (Upgrade #3, scaffolded, never wired into the prompt layer). Feature sizing is exactly what these were built for.

### Q4: Is CORTEX working? — NO (one component excepted).

- **Working:** `cortex/app_profile.py` — live via `cli scan`; AppProfile was really captured in the run.
- **Not working:** the actual cognitive memory engine (`cortex/observation.py`, `store.py`, `sqlite_backend.py`) is dead code — nothing ever writes or reads an observation. `.danza/build-orders.md` and `patterns.md` are empty placeholders "pointing to CORTEX."
- **Worse:** `tony-d-orchestrator.md:74,116,162` tells Tony D that CORTEX "tracks patterns automatically" and "auto-records this turn's build data (observation extractor); no manual step." **That machinery does not exist.** In our run the agents were honest about it ("CORTEX consulted — empty, fresh system"), but the false prompt claim is standing theatre-bait, and it means **nothing is ever learned between turns** — the compounding-knowledge promise (STACKRONYM) is currently zero-compounding.

---

## 3. Root causes of the token burn (ranked)

1. **Report-relay-through-orchestrator:** full driver reports flow into Tony D's ever-growing context and get re-narrated. Same bytes processed 3-4x.
2. **No compiled per-driver context:** every agent re-reads the whole stack (CLAUDE.md, 45-rule constitution, state files). `context/pipeline.py` (select→compress→isolate, token-budgeted) was built precisely for this and is dead code.
3. **Fixed ceremony regardless of risk** (Q2 above).
4. **Undefined feature size** (Q3 above) → mega-features → mega-reviews.
5. **Evidence-as-prose-duplication:** Rule 42/43 compliance implemented by copying the same facts into decision-log + run-log + turn-log + self-assessment. `observability/trace.py` (JSONL spans) was built for cheap evidence and is dead code.
6. **No inter-turn memory** (Q4) → next turn re-derives everything from raw files.

---

## 4. The improvement plan (prioritized; each item: what → where → why)

### P0 — Blueprint hygiene fixes (hours; do first, zero risk)
1. Fix `tony-d-orchestrator.md`: remove the false CORTEX "auto-records" claims (lines 74, 116, 162) — replace with the explicit manual step from P4. Remove the "~500 tokens" handoff caps (lines 252, 299) — they contradict Rule 44 (defect D2, confirmed). Fix the stale "no `.danza/` directory" branch (line 98, defect D3).
2. Portability: replace every hardcoded `python3` with a launcher-resolution step ("use `python` if `python3` is absent") in: `.claude/settings.json` hook command, `settings.example.json`, `SKILL.md`, `tony-d-orchestrator.md`, `bonnie-qa.md`, `RUNBOOK.md`, `run_tests.sh`. The activation only survived this on our machine because MY session memory leaked into the agents — a fresh user's machine gets a silently dead constitution.
3. Fix `test_runtime.py:55,59,63` — `tempfile.mkdtemp()` instead of `/tmp` → 124/124 everywhere.
4. Reconcile INSTALL.md ("hooks already ACTIVE") vs RUNBOOK.md ("not active by default") against reality (settings.json exists but is Windows-broken until item 2).
5. `git init` + initial commit — the constitution's append-only/immutability rules currently have no version-control backstop.

### P1 — Report-by-pointer protocol (the single biggest cheap win; prompt-layer only)
Add to every driver agent .md and Tony D's runbook: drivers write their **full report** to `.danza/reports/turn-NN/<agent>-<task>.md` and **return only a ≤15-line summary + pointer + verdict**. Tony D reads summaries; he opens the full file only on a flag. Decision-log entries cite pointers instead of duplicating prose. Expected effect on the observed run: Tony D's legs stay ~40k instead of growing to 105k; eliminates most of the 3-4x re-processing. This is Rule 44's own philosophy (pointer, not briefing) applied inside the turn, not just at handoff.

### P2 — Risk-tiered agent activation matrix (replaces "everyone, every feature")
Encode in `tony-d-orchestrator.md` (and constitution amendment if the user approves):

| Agent | Runs when |
|---|---|
| Jonathan | every feature (builder) |
| Bonnie | every feature before it counts (Rule 5 — non-negotiable gate) |
| Samantha | full map: turn 1 and after schema/API surface changes. Otherwise: Jonathan appends a 10-line delta note to the map; Samantha does a full re-scan every N turns or on Rule 17 conflict |
| Angela | always passive-logs (cheap). Full source-verification audit ONLY on risk flags: money math, auth, schema, deletions, new dependency, rule-conflict — else samples 1 feature per turn |
| Carmella | onboarding, "no preference" triggers (Rule 30), external-API features |
| Hank | visual-preference events and new UI surfaces only |
| Billy | second half of build (already the rule) |

Observed savings had this existed: Samantha's 69k full map after F1 → ~10k delta note (F1 did change schema, so she'd still run — but not again after F2-F6 unless surfaces change); Angela's 37k full audit would still run on F2 (money) but not on F5 (print CSS).

### P3 — Feature sizing rubric + wire the existing planning gate
1. Define in the constitution (new rule or Rule 3 amendment): **a feature is 1-3 atomic tasks; an atomic task names its files, its verification command, and its done-condition; if you can't write the verification in one sentence, split it.** This is `planning/decompose.py`'s `is_verifiable()` logic expressed as prompt law.
2. Wire the code: add `danza plan` CLI subcommand — validates a turn plan JSON against `planning/plan_schema.json` + `decompose.assert_dispatchable()`. Tony D runs it before dispatching Jonathan (like he runs selftest today). The code exists and is tested; only the CLI plumbing (~30 lines) and a runbook line are missing.
3. This retroactively fixes Q3: sizing stops being Tony D's vibes and becomes a machine gate.

### P4 — Make CORTEX minimally real (or honestly demote it)
Recommended: **wire it minimally.** Add CLI: `danza cortex record '<json>'` and `danza cortex recall "<query>" --budget N` backed by the existing, tested `cortex/store.py` + `sqlite_backend.py` (DB at `.danza/runtime/cortex.db`). Runbook changes: Tony D records 3-5 observations at handoff (what worked, what broke, build order used); recall runs during onboarding/planning and its output goes into driver briefs. ~50 lines of plumbing for the OS's entire compounding-knowledge promise. If the user prefers to defer: delete every "CORTEX auto-" claim from prompts and mark `.danza/build-orders.md`/`patterns.md` as the interim manual memory — honesty either way (P0.1 overlaps).

### P5 — Deterministic bootstrap + cheap evidence (medium term)
1. `danza init` CLI: creates `.danza/runtime/team-state.json` via the existing `StateManager` (Rule 45 stops depending on model diligence — this run got lucky with a diligent model).
2. Wire `observability/trace.py`: CLI commands emit spans to `.danza/runtime/trace.jsonl`; Rule 43 self-audit cites span IDs instead of pasted prose. Kills root cause 5.
3. Wire `hooks/guards.py:context_budget_guard` + per-driver briefs (the `context/pipeline.py` concept applied at prompt layer: Tony D writes a brief file per dispatch — task, relevant map section, relevant decisions, relevant rules only).

### P6 — Finish the unobserved verifications (next session, after P0-P2)
Bonnie's gate, self-assessment-with-evidence, handoff writing (D2 fix verification), **Stage 3 takeover mode** (sandbox with an existing app), **Stage 4 relay** (second AI picks up the handoff; watch team-state transitions). These are the remaining unverified constitutional mechanisms. With P1/P2 in place, the whole remaining run should cost a fraction of this session's.

---

## 5. What NOT to change

- The star topology and Bonnie-as-sole-gate: they worked exactly as designed.
- The honesty culture: every observed agent was honest about walls (offline pipeline, empty CORTEX, unknown browser behavior). The prompts' confidence-tagging (Rule 23) demonstrably works — keep it.
- The `.danza/` blackboard pattern and append-only discipline: observed working (Angela preserved logs byte-for-byte; templates untouched).
- Option-A-style stack philosophy (free/light/local): Carmella + stack-philosophy.md produced exactly the right recommendation.

## 6. Verification for this plan's implementation

Each P-item ships with: (a) the concrete file diffs, (b) `./danzaboss/run_tests.sh` green (124/124 after P0.3), (c) `danza selftest` 8/8, and (d) for P1-P4: a re-run of the sandboxed greenfield activation measuring **tokens per verified feature** against this session's baseline (~390k for F1). Target: ≥50% reduction with zero constitutional regressions (all 14 watchpoints from the activation protocol must still pass or improve).
