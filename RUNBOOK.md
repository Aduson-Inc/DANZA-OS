# DANZABOSS — Runbook: try it on a real app

This is the one working set. Below is exactly how to point DANZA at a real app and run it.
Honest status is at the bottom — read it before your first run.

## The one working set (layout)

```
CLAUDE.md            Entry doc every AI reads first
.claude/             Live agent layer — 8 agents + constitution + "Who's the Boss?" skill
  settings.example.json   Hook wiring (rename to settings.json to activate; verify API first)
.danza/              Runtime state + auto-memory
danzaboss/          The Python brain (promoted, authoritative) — 124 tests
  kernel/ planning/ memory/ context/ security/ observability/ orchestration/ selftest/
  cortex/ hooks/ research/
  runtime/   scan (learn any repo) · verify (run real tests) · runner
  cli.py     the `danza` command the agents + hooks call
  tests/  run_tests.sh
docs/                Design docs (architecture, ADRs, research)
tools/research-pipeline/   YouTube→NotebookLM research helper
```

## Prove the brain works (30 seconds)

```bash
# from the repo root
./danzaboss/run_tests.sh                                   # 124 tests, should be green
PYTHONPATH=. python3 -m danzaboss.cli selftest             # cold-start harness, 8/8
```

## Try it on a real app

**1. Learn the app** (works on any stack — TS, Python, Go, …):
```bash
PYTHONPATH=. python3 -m danzaboss.cli scan /path/to/your/app --domain "what it is"
# prints the learned AppProfile: languages, frameworks, databases, features, confidence
```

**2. (Optional) Turn on the governance hooks** so the build can't fake work or regress:
```bash
# verify Claude Code's current hooks API, then:
cp .claude/settings.example.json .claude/settings.json
```

**3. Build features** — in Claude Code with DANZA installed, type:
```
Who's the Boss?
```
Tony D runs onboarding (learns intent, uses the AppProfile), then the build cycle:
Samantha maps → Jonathan builds → Bonnie verifies → Angela logs. The hooks (if on) enforce
capability/hard-stop/anti-theatre/verify/regression.

**4. Verify a change** with the app's own tests (the QA gate):
```bash
PYTHONPATH=. python3 -m danzaboss.cli verify "npm test" /path/to/your/app     # or: pytest, go test, …
# exit 0 = pass; feeds "verify before done" + the regression gate
```

## Honest status (read before first run)

- ✅ **The brain is real and tested:** scan, verify, selftest, hooks logic, CORTEX memory,
  kernel, capabilities — 124 unit tests, and the CLI runs live (it scanned this repo).
- ◑ **The agent build loop** ("Who's the Boss?") runs in Claude Code where the 8 agents are
  registered. It is the original prompt/agent layer driving the build; it has **not yet been run
  end-to-end on a real app**, so expect rough edges on the first try.
- ◑ **Hooks are not active by default.** They're written and tested, but you must rename
  `settings.example.json` → `settings.json` AND verify the event names against Claude Code's
  current hooks docs first. Until then the guards enforce nothing at runtime.
- ⚠️ **Building is done by the agents, not the Python.** `danzaboss/` plans, remembers, verifies, and
  guards; it does not itself write code headlessly (that's the future API-key/SDK path).

## First recommended run
Point `danza scan` at a small, low-stakes app, eyeball the AppProfile it learns, then try one
tiny feature via "Who's the Boss?" with hooks OFF — watch how the agents behave — before turning
hooks on and trusting it unattended.
