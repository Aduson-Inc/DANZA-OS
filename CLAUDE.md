# DANZA-OS Contributor Guide

This checkout is Layer 0 `OS_DEV`. It develops the installable DANZA-OS
package; it is never an activated application project. Do not invoke the
APP_BUILD activation phrase here and do not create customer runtime state in
the repository root.

## Source boundaries

- `danzaboss/` contains the Python package and `danza` CLI.
- `danzaboss/product/templates/scaffold/` is the sole shipped APP_BUILD payload:
  named prompts, constitution, activation skill, hook settings, bootstrap
  `.danza` state, and the managed target-project guide.
- `danzaboss/workstation/` contains the dashboard, PROJECT and BUILD services,
  runner routing, and runtime automation.
- `danzaboss/cortex/` is the canonical product memory/context subsystem.
- Root `.claude/` and customer bootstrap `.danza/` files are not product
  authorities and must not activate this checkout.

Tony-D — The Boss is the visible boss and orchestrator. The active specialists
are Jonathan, Samantha, Angela, Bonnie, Carmella, Hank, and Billy. Internal
runtime infrastructure is not part of the cast.

## Development workflow

Read the current Phase 4.1 plan and `/home/tre/dev/DANZA-OS-CONTINUATION.md`
before changing behavior. Add a failing focused test first, make the smallest
compatible implementation, then broaden verification by risk. APP_BUILD boot
tests must use a temporary target repository created by `danza init`.

Useful commands:

```bash
python3 -m danzaboss.cli selftest
python3 -m danzaboss.cli profile
python3 -m unittest discover -s danzaboss/tests -p 'test_*.py'
./danzaboss/run_tests.sh
```

CORTEX context allocation is adaptive and independent of the configured
verified-unit quota. Never introduce a fixed token dial or a second product
memory system.

Do not push, publish, tag, merge, rewrite history, or claim release readiness
without explicit owner direction. Preserve user changes in a dirty tree.
