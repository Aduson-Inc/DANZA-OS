# DANZA — Market Scan + 10 Opportunities + Revenue Setups

**Date:** 2026-07-01 · **Window:** trending as of ~June 2026 · **Status:** research/strategy (no code).
**Honesty note:** GitHub-star and Skool-subscriber figures are as-reported by secondary sources and
move fast; treat them as directional, not audited. Skool "last-30-days" membership specifics were not
independently verifiable via search — flagged inline.

---

## 1. Landscape snapshot (what's hot right now)

| Tool | What it is | Why it matters to DANZA |
|---|---|---|
| **OpenClaw** | Self-hosted agentic assistant, ~9k→210k GitHub stars in weeks; 50+ native connectors (WhatsApp/Telegram/Slack/Discord), no external API routing | The connector + self-host pattern DANZA should adopt; proves demand for a governed, private agent OS |
| **Hermes Agent** (Nous Research, MIT, Feb 2026) | Self-hosted always-on agent; multi-layer memory across sessions; plan→execute→store→repeat loop; **turns tasks into reusable skills**; driven via Telegram/Discord | Near-mirror of DANZA's continuous mode + CORTEX + skill capture → strongest integration target |
| **Hostinger Managed Hermes** | One-click Docker VPS, visual UI, AI credits, Telegram, web scraping, email, anti-DDoS | The exact managed-VPS delivery model DANZA can copy or ride on |
| **Codex (GPT-5.5)** | Ranked #1 coding agent April 2026 | A DANZA driver option (Jonathan-builder backend) |
| **Claude Code** | Depth leader; headless `--print`, VPS/CI-CD, gateway auth | DANZA's primary driver; headless = 24/7 autonomous builds |
| **OpenCode** | 147k stars, 6.5M devs by April 2026; Copilot auth | Fast-growing open driver alternative |
| **Gemini CLI** | Free Gemini 3.1 Pro in terminal | Zero-cost driver for budget builds |
| **Make.com AI Agents** | 3000+ integrations + own MCP server | DANZA's "arms" for deploy/notify/CRM actions |
| **Vapi** | Developer-first voice agents (Assistants/Squads), custom-LLM endpoint, Evals/Sims | Voice layer for DANZA and for DANZA-built client apps |
| **n8n + Claude Code** | The Agentic Academy (Skool) stack | Community-proven workflow orchestration pattern |

**Where DANZA fits (positioning):** every tool above is either a *connector layer* (OpenClaw, Make),
a *driver* (Claude/Codex/Grok/Gemini), a *runtime* (Hermes, VPS), or a *channel* (Vapi, Telegram).
**None of them is a governed build OS.** DANZA's differentiators — a 45-rule constitution, verifiable-
task gate, capability security, machine-checkable turn state, and CORTEX cognitive memory — are exactly
the *governance + reasoning* layer this ecosystem lacks. DANZA is the **conductor**, not another instrument.

---

## 2. Ten opportunities (skills · features · connectors · VPS)

Each: what it is · DANZA fit · rough effort · revenue angle.

**1. Headless DANZA on a VPS (24/7 autonomous builder).**
Run DANZA in continuous mode on a Hostinger/any Ubuntu VPS via Claude Code headless (`--print`), Docker
isolation, API-key auth (`ANTHROPIC_BASE_URL`/`AUTH_TOKEN`). *Fit:* continuous mode + loop-safety valve
were built for exactly this. *Effort:* Low–Med. *Revenue:* managed-hosting + agency delivery.

**2. Hermes ↔ DANZA bridge (MCP).** Hermes as the always-on "front desk" (messaging, memory, scheduling);
DANZA as the governed builder it delegates code work to. Hermes takes a Telegram request → hands a build
job to DANZA → DANZA builds under constitution + CORTEX → returns result. *Fit:* both do skill-capture +
multi-layer memory; complementary, not competing. *Effort:* Med. *Revenue:* premium "governed Hermes."

**3. Multi-model driver adapter (Claude · Codex · Grok · Gemini).** DANZA already relays across AIs; add
driver adapters so `jonathan-builder` runs on the best/cheapest model per task (Codex GPT-5.5 for raw
codegen, Claude for architecture, Gemini CLI free for cheap passes, Grok for speed). *Fit:* extends the
existing relay + ports pattern. *Effort:* Med. *Revenue:* cost arbitrage + resilience selling point.

**4. Messaging connectors (Telegram · Discord · Slack · WhatsApp).** Trigger `Who's the Boss?` and receive
build progress / handoff / blocker alerts from chat — the OpenClaw/Hermes UX. *Fit:* maps to the notify
points already in the handoff cycle. *Effort:* Low–Med. *Revenue:* the "build from your phone" hook.

**5. Make.com connector (via Make's MCP server).** On build events, DANZA fires 3000+ app actions (deploy,
invoice, update CRM, post to socials); Make scenarios trigger DANZA builds. *Fit:* DANZA = brain, Make =
arms. *Effort:* Low. *Revenue:* end-to-end client automations, not just code.

**6. Vapi voice connector.** (a) Voice-drive DANZA ("call your OS, describe a feature"); (b) ship DANZA-built
client apps with a bundled Vapi voice agent. *Fit:* new input channel + a sellable add-on. *Effort:* Med.
*Cost flag:* Vapi's real cost ~$0.30/min all-in, not the $0.05 headline. *Revenue:* voice-enabled deliverables.

**7. n8n workflow connector.** DANZA orchestrates n8n workflows as tools and vice-versa — the exact
Claude Code + n8n stack the Agentic Academy Skool community sells. *Fit:* community-proven. *Effort:* Low–Med.
*Revenue:* slots DANZA into the biggest existing AAA training pattern.

**8. CORTEX-as-a-service (shared memory over MCP + Neon).** Expose CORTEX so external agents (Hermes,
OpenClaw, Make agents) read/write project memory; Neon backs the shared L3–L5 tiers. *Fit:* the spec's MCP
wrapper + ADR-005 Neon adapter. *Effort:* Med. *Revenue:* recurring "second-brain" SaaS ($19–49/mo/project).

**9. Reusable-skill capture + marketplace.** DANZA auto-captures successful builds as reusable skills
(Hermes-style), owned by Mona + CORTEX L5; package and sell skill/template packs. *Fit:* Mona's historian
role + L5 cross-project knowledge already exist. *Effort:* Med. *Revenue:* marketplace + template sales.

**10. One-click client-delivery VPS template (the agency stack).** A packaged DANZA + CORTEX + connectors
image agencies deploy per client — a governed autonomous dev team as a managed service. *Fit:* bundles 1–9.
*Effort:* Med–High. *Revenue:* the core productized-agency play (see §4).

---

## 3. Hermes + Claude/Codex/Grok — integration blueprint

The most powerful near-term combo is **Hermes as runtime/orchestration shell + DANZA as governance/brain +
Claude/Codex/Grok as interchangeable drivers**:

```
Telegram/Discord ──► Hermes Agent (always-on runtime, messaging, its own memory)
                         │  delegates "build/fix/ship" jobs (MCP)
                         ▼
                     DANZA-OS  ── constitution · verifiable tasks · capability security · CORTEX memory
                         │  dispatches jonathan-builder on the best driver per task
              ┌──────────┼───────────┬──────────────┐
              ▼          ▼           ▼              ▼
           Claude     Codex        Grok         Gemini CLI
        (architecture)(codegen)  (fast/cheap)   (free passes)
                         │  build → Bonnie verifies → CORTEX records → result
                         ▼
                Make.com / n8n / Vapi  ── deploy, notify, invoice, voice
```

Why it's strong: Hermes gives 24/7 presence + chat channels + its own skill memory; DANZA adds the *trust
layer* Hermes lacks (nothing arbitrary gets built — hard stops, verification, audit); the driver adapter
means you're never locked to one model's price or outages. CORTEX becomes the shared long-term memory both
Hermes and DANZA read from.

**Practical path:** (1) headless DANZA on a VPS (#1); (2) MCP bridge so Hermes calls DANZA (#2); (3) driver
adapter for Codex/Grok/Gemini alongside Claude (#3); (4) wire Make/n8n/Vapi as the action + voice layer.

---

## 4. Revenue-generating setups DANZA fits into

Grounded in 2026 AAA economics (productized $1.5–5k/mo; retainers $2–20k, avg ~$3.2k; solo founders cited
at ~$40k/mo with 5 clients at ~85% margins; agent subscriptions $19–49/mo; Skool challenge+community+agents
stacks cited at $15–30k/mo).

1. **"Autonomous Dev Team" retainer** — DANZA builds/maintains client apps under governance, human supervises.
   Productized $2–5k/mo per client. The flagship offer; DANZA's governance is the trust differentiator vs raw agents.
2. **Managed DANZA VPS** — Hostinger-Managed-Hermes model: setup fee + monthly hosting/ops. Recurring, low-touch.
3. **CORTEX memory SaaS** — per-project "second brain" ($19–49/mo/project). Sticky, scales without labor.
4. **Skill/template marketplace** — sell captured reusable builds (opportunity #9). Digital-product margins.
5. **Skool community + course** — teach the DANZA stack (the Agentic Academy pattern, $37–87/mo tiers) and sell
   the system + support. Community flags: exact sub counts unverified; model itself is well-proven.
6. **Voice-enabled deliverables** — bundle a Vapi agent into client apps as a priced add-on (mind the ~$0.30/min true cost).

**Highest-leverage sequence:** ship #1 (VPS) → package #10 (client template) → attach #3 (CORTEX SaaS) for
recurring revenue → grow via #5 (community). Governance + memory are the moat; connectors are the reach.

---

## 5. Caveats / what to verify before betting
- Star/subscriber numbers are secondary-source and volatile; re-check before quoting publicly.
- Vapi and enterprise voice carry real per-minute + compliance costs well above headline pricing.
- Grok/Codex-as-DANZA-driver depends on their current CLI/API terms; confirm before promising model-agnostic.
- Hermes is MIT/self-host today; a deep DANZA bridge should track its API stability.
- Skool "last-30-days" popularity claims could not be independently confirmed via search.

---

*Sources: OSSInsight/GitHub trending, ODSC & ByteByteGo repo roundups (OpenClaw, OpenCode, Langflow/Dify),
Hostinger Hermes docs + launch blog (Nous Research, MIT), Make.com AI Agents + MCP docs, Vapi pricing/reviews
(Lindy, Retell, CloudTalk), Claude Code headless/VPS guides (claude.com docs, amux, MindStudio), AAA pricing
guides (Digital Agency Network, Ciela, Medium/The AI Studio), Skool community reviews (Agentic Academy).*
