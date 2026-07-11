# Tre — Working Style for DANZABOSS

- Plan-then-confirm with an approval gate by default; but Tre can grant "work to the end
  without asking" for a specific task (as on 2026-07-01) — honor that scope, then revert to
  confirm mode next task unless told otherwise.
- Verify before claiming done: show command/test output or diffs, not narration.
- Warn before heavy token spend; flag tools/skills that make work more focused.
- Concise, lead with the answer. Professional, current best-practice code; don't change the
  stack without discussing.
- Project mandate: optimize over expand. Every change should reduce complexity/tokens/
  hallucination or raise reliability/speed/maintainability, with evidence and a stated WHY.

## Standing rule (2026-07-01): surface human blockers immediately
When a task is blocked by something only Tre can do (account signup, API key, billing,
OAuth/Google auth, secrets, a purchase, an external config value), PAUSE and:
1. Explain what's blocked and why it needs him.
2. Give explicit step-by-step instructions on what to do or try.
3. Never paste/request secrets in chat — instruct him to store keys as local env vars and
   tell Claude only the variable NAMES to code against.
Do not stall silently, guess around it, or claim an integration works when it needs his input.
