# DANZA-OS Architecture

## Layer boundary

```text
Layer 0 OS_DEV source
        │ packages
        ▼
Layer 1 installable DANZA-OS
        │ danza init
        ▼
Layer 2 APP_BUILD target repository
        │ PROJECT approval → BUILD execution
        ▼
Target application source + project-scoped CORTEX
```

Layer 0 contains Python source, tests, current documentation, and development
configuration that cannot activate customer agents. Layer 1 contains the CLI,
dashboard, runners, kernel, hooks, planning schemas, CORTEX, and the canonical
payload at `danzaboss/product/templates/scaffold/`. Layer 2 contains generated
`.claude/` instructions, `.danza/` state, canonical PROJECT and BUILD data,
and the application being built.

## Product components

- `danzaboss/product/` owns deterministic scaffolding and parses the visible
  roster from the eight canonical character prompts.
- `danzaboss/workstation/` serves the local dashboard and implements SETUP,
  PROJECT, BUILD, runner routing, session hosting, and live progress APIs.
- `danzaboss/planning/` owns specifications, feature decomposition, executable
  plan schema, and verified atomic-unit lifecycle.
- `danzaboss/kernel/` owns execution profiles, team state, scheduling, and
  verification tiers.
- `danzaboss/hooks/` enforces target-project runtime gates.
- `danzaboss/cortex/` is the canonical observation, retrieval, context,
  learning, graph, dashboard, and MCP subsystem. Adaptive budgeting uses task
  complexity and available memory rather than a fixed token setting.

Tony-D — The Boss is the visible orchestrator. The dashboard obtains Tony-D,
Jonathan, Samantha, Angela, Bonnie, Carmella, Hank, and Billy from the same
canonical prompts installed into APP_BUILD projects. Runtime plumbing remains
an implementation detail and is not a character.

The package is declared by `pyproject.toml`; package-data rules ship prompts,
rules, settings, bootstrap state, schemas, and static assets. Root customer
payload copies are intentionally absent so OS_DEV cannot masquerade as an
application project.
