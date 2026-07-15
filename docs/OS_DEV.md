# OS_DEV

`OS_DEV` is the permanent execution profile for developing DANZA-OS itself.
The source checkout is Layer 0 and must never activate as a customer project.

## Profiles

| Profile | Purpose | Runtime agents and hooks |
|---|---|---|
| `OS_DEV` | Develop and test the operating system | inactive |
| `OS_BOOT_TEST` | Validate a packaged payload in a disposable repository | active |
| `APP_BUILD` | Build a real target application | active |

Profile resolution lives in `danzaboss/kernel/profile.py`. APP_BUILD requires
project-scoped runtime state; OS_BOOT_TEST is explicitly selected in a fixture.
The source root has neither and therefore resolves to OS_DEV.

## Development contract

- Edit product payload only at
  `danzaboss/product/templates/scaffold/`, then test `danza init` in a
  temporary target repository.
- Do not create or trust root activation prompts, settings, hooks, or bootstrap
  `.danza` state.
- Treat CORTEX as the canonical product memory/context subsystem. External
  memory utilities may assist development but must not enter dependencies,
  prompts, hooks, or documentation as product requirements.
- Use test-driven changes and the verification tier reported by `danza tier`.
  A Task 11 commit requires the full Python suite and payload boot coverage.
- Preserve Tony-D — The Boss and the seven named specialists as product
  identity; internal automation remains hidden.

CORTEX is dormant in OS_DEV sessions because customer capture and injection
belong to application projects. Packaged SessionStart, PostToolUse, and Stop
hooks are verified in fixtures. In APP_BUILD, adaptive CORTEX budgeting selects
context from task complexity, agent needs, and available memory independently
of the configured verified-unit quota.
