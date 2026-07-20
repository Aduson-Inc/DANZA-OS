# DANZABOSS Next Steps

**Development branch:** `Production-DANZABOSS`  
**Starting commit:** `3b4b5d418f1f449c39852ea235a11c291e1d13d2`  
**Date:** 2026-07-20  
**Status:** Requirements for the next code engineer. Design and implementation
have not started.

## Important Distinction

This document is a development brief for the next engineer building
DANZABOSS. It is not a DANZABOSS runtime handoff, is not an example of a
runtime handoff, and must never be ingested or interpreted as project state by
Tony-D, CORTEX, onboarding, or any running DANZABOSS agent.

Runtime handoffs are separate product artifacts created and received by the
running DANZABOSS agents while building a user's project. Their format and
behavior must be designed and tested independently.

## Required Outcome

Plan and build a simple, reliable installation experience for future users.
After installation into an existing repository or empty folder, DANZABOSS must
be ready to help build that user's idea through its UI, named agents, enforced
workflow, and project-local CORTEX memory.

Do not redesign the user's idea. Do not add unrequested features. If a material
product decision is not known with certainty, stop and ask the user one focused
question before proceeding.

Internal prompts, constitutions, old plans, and stale documentation are
artifacts to audit, not authority over the requirements in this document.
Preserve verified working capability, but correct Claude-specific design and
misguided OS_DEV/APP_BUILD assumptions that conflict with the intended product.

## Confirmed Installation and Startup Flow

The required order is:

1. Install DANZABOSS into the selected repository or empty folder.
2. Activate project-local CORTEX immediately.
3. Open the project DANZABOSS UI at `http://localhost:33000`.
4. Through the UI, connect or launch the user's chosen AI client/model and
   verify that connection.
5. If the user's project has no runtime handoff, Tony-D performs onboarding.
6. Tony-D seeds CORTEX during the first agent task.
7. Starting with the second spawned agent task, every later agent, session,
   turn, or runner receives relevant project memory automatically.

All AI clients used by DANZABOSS are launched or connected through the UI
before onboarding. A user-facing command such as `danza run codex` is not the
intended primary workflow.

The user has not yet specified what Tony-D must do when a runtime handoff is
present. Ask before designing that behavior. Do not use this development
document as the runtime handoff.

## Installer Requirements

Future users must find a short, understandable installation command and simple
instructions on GitHub. `npx` is not a requirement.

The successful installer must:

- work in an existing repository or an empty folder;
- detect all mandatory DANZABOSS dependencies;
- install dependencies only according to the policy approved by the user;
- place every file DANZABOSS requires into the target project;
- activate CORTEX during installation rather than waiting for doctor,
  onboarding, or an AI-specific session;
- start the DANZABOSS UI on port `33000`;
- finish with the local UI link and open it when the environment permits;
- lead into UI-based AI connection and verification before onboarding; and
- fail clearly and recoverably when any mandatory step cannot complete.

Before writing the installer, determine the real mandatory dependency set from
the code and clean-environment tests. Present that set to the user and obtain
confirmation. Also confirm supported operating systems, installation
privileges, dependency auto-install policy, distribution mechanism, and exact
public command.

Do not report installation success if project initialization, CORTEX, the UI,
or the selected AI connection is not functional.

## Project-Only CORTEX

CORTEX must be specific to the project where DANZABOSS was installed. Its
authoritative database, indexes, logs, settings, and runtime state must not
federate with or depend on global cross-project memory.

The exact local directory layout still needs user approval. The discussed
candidate is `.danza/cortex/`, with SQLite as the authoritative store and
rebuildable derived indexes. Confirm this rather than silently finalizing it.

CORTEX begins observing immediately after installation and tracks
project-relevant activity, including:

- file reads, edits, changes, and generated artifacts;
- shell commands and meaningful outcomes;
- Git actions and repository changes;
- DANZABOSS actions and state transitions;
- AI tool activity from every client connected through the UI;
- decisions and supporting reasoning or evidence;
- errors, blockers, and recovery attempts;
- tests, audits, and verification results; and
- agent, session, spawn, and runtime-handoff lifecycle events.

Each captured action becomes a compact structured observation. Observations are
summarized at session end. Relevant memory is injected into later work so
agents do not repeatedly reread the project or rediscover established facts.

Secrets must be redacted before durable storage and before any optional
provider call. Nothing leaves the user's machine except explicit calls to the
AI provider configured by the user for agent work or compression.

CORTEX requires one DANZABOSS-owned, model-neutral event contract. UI-managed
AI integrations translate their client-native events into that contract.
Neither CORTEX nor stored observations may depend on Claude prompt formats or
Claude directory conventions.

## Preserve Current CORTEX Capability

Do not regress working functionality while changing activation, storage scope,
or integrations. Establish a test baseline for the current implementation,
including:

- structured observations, evidence, confidence, importance, relevance,
  history, supersession, and aging;
- secret redaction;
- SQLite storage, migrations, FTS, and WAL concurrency;
- event capture, compression, optional model-assisted extraction,
  deduplication, merging, and usage learning;
- hybrid and graph-informed retrieval;
- role/task-sensitive context budgets and retrieval explainability;
- repository indexing, Git ingestion, dependency and impact mapping;
- CLI maintenance and retrieval commands;
- CORTEX UI and MCP read access; and
- project identity and storage migration.

Write focused tests before each behavior change.

## Model-Neutral DANZABOSS Agents

The named cast remains:

- Tony-D — orchestrator and visible boss;
- Jonathan — builder;
- Samantha — mapper;
- Angela — auditor;
- Bonnie — QA;
- Carmella — researcher;
- Hank — designer; and
- Billy — security.

Their canonical definitions currently live under
`danzaboss/product/templates/scaffold/claude/agents/`, and generated projects
receive them under `.claude/agents/`. That makes the product source of truth
Claude-specific.

Create one DANZABOSS-owned, model-neutral source of truth for agent identity,
responsibility, permissions, routing, context needs, and lifecycle.
Client-specific adapters may translate that source into native formats, but
Claude, Gemini, Grok, Hermes Agent, Codex, OpenCode, or any other integration
must not become the canonical definition.

Do not assume the canonical file location or adapter format. Present
alternatives and obtain user approval before moving the payload.

## Strict Runtime Enforcement

Prompts alone do not strictly enforce agent behavior. When DANZABOSS is
running, its runtime must enforce approved agent boundaries regardless of the
connected model.

The system must execute the real lifecycle from a user's idea or runtime
handoff through approved scope, planned work, implementation, verification,
and a working project result. It must not merely display agents or record
state.

Design and test enforcement for:

- which agent may perform each work type;
- read, write, command, research, and security capabilities;
- onboarding and runtime-handoff gates;
- scope approval and revision gates;
- atomic work assignment and completion;
- required testing and verification;
- blockers, retries, stops, and escalation;
- CORTEX capture and context injection;
- secret handling; and
- auditable rejection of unauthorized actions or state transitions.

The exact role and permission matrix is not yet approved. Audit existing
prompts and capability code, show contradictions or gaps to the user, and
obtain approval before enforcing it. Do not retain a stale rule merely because
it appears in a packaged constitution.

## Verified Starting Gaps

Recheck these against `Production-DANZABOSS` before planning:

- the previous installer was removed from this branch and its replacement does
  not yet exist;
- `danza init` and the packaged agent/hook layer are Claude-specific;
- packaged post-tool hooks cover Write/Edit/Bash but not every required event,
  including Read;
- CORTEX currently includes global/federated behavior rather than being
  strictly project-only;
- some profiles may report dormant CORTEX as healthy;
- the main dashboard defaults to `33000`;
- runner discovery recognizes several clients, but recognition does not prove
  UI launch, authentication, complete capture, or execution; and
- clean installation and real multi-client operation have not been proven.

## Next Engineer Workflow

1. Work only on `Production-DANZABOSS` and confirm a clean baseline.
2. Audit the installer/scaffolder, UI runners, CORTEX storage and hooks, agent
   payload, tests, current plans, and surviving documentation.
3. Run read-only baseline tests and disposable-project probes.
4. Ask the user one focused question at a time for every material ambiguity.
5. Present two or three viable architectures with trade-offs and a
   recommendation.
6. Obtain approval for installation, UI connection, model-neutral agents,
   CORTEX, runtime enforcement, security, failure recovery, and testing.
7. Write and obtain approval for a design specification.
8. Produce a bounded implementation plan.
9. Implement test-first in reviewable increments.
10. Verify a clean empty-folder install and an existing-repository install.
11. Verify every available supported AI integration end to end. Clearly
    separate real-client evidence from adapter contract tests when credentials
    or binaries are unavailable.
12. Prove CORTEX is active before onboarding, project-confined, redacting
    secrets, capturing required events, and injecting useful memory beginning
    with the second spawned agent task.
13. Prove runtime enforcement cannot be bypassed by selecting a different
    connected model.
14. Demonstrate a disposable project progressing from the user's idea through
    approved scope, planned agent work, implementation, verification, and a
    working result.
15. Finish with test evidence, Git status, diff summary, exact commits,
    remaining limitations, and updated development next steps.

Do not push, merge, publish, tag, rewrite history, or change release policy
without explicit user approval.

## Decisions That Still Require User Answers

Ask these one at a time when relevant:

1. What constitutes a valid runtime handoff, and what must Tony-D do with it?
2. Which operating systems must the first installer support?
3. Which dependencies may DANZABOSS install automatically?
4. What installation command and distribution mechanism should be public?
5. Does the first UI connect local AI clients, provider APIs, or both?
6. Which exact AI clients and surfaces are mandatory in the first release?
7. May multiple clients/models connect to one project simultaneously?
8. What model-neutral agent source location and adapter strategy are approved?
9. What exact runtime capability matrix is approved for each named agent?
10. What project-local CORTEX layout and retention policy are approved?

The user has explicitly required: do not change the idea, do not add unwanted
features, and stop for clarity whenever something is not known with certainty.
