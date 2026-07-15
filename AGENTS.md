# DANZA-OS Development Guidance

This repository is Layer 0 `OS_DEV`: the source of the DANZA-OS application.
It is not an activated customer `APP_BUILD` project.

- Preserve the boundary between OS source and generated target projects.
- Never treat root `.claude/` or `.danza/` bootstrap state as product truth.
- The packaged payload under `danzaboss/product/templates/scaffold/` is the
  authority for generated APP_BUILD projects.
- CORTEX is the product memory and context subsystem. External memory tools
  are development aids, not product dependencies.
- Read the current Phase 4.1 plan and continuation handoff before implementation.
- Work on one bounded task at a time and write tests before behavior changes.
- Test activation only in disposable target repositories.
- Do not use subagents unless the user explicitly requests them.
- Do not rewrite history, push, publish, tag, merge, or change release policy
  without explicit approval.
- End implementation work with test evidence, Git status, diff summary, the
  exact commit, and an updated continuation handoff.

Keep this file concise. Product runtime law belongs in the packaged payload.
