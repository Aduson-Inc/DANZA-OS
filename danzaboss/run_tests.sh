#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"                 # danza/
ROOT="$(cd .. && pwd)"              # repo root (so `import danzaboss works)
export PYTHONPATH="$ROOT:$(pwd)/tests"
# C6: tests must never touch the developer's real ~/.danza global store
export DANZA_CORTEX_GLOBAL_DB="${DANZA_CORTEX_GLOBAL_DB:-$(mktemp -d)/global.db}"
echo "== DANZA test suite (promoted danzaboss/ package) =="
python3 -m unittest discover -s tests -p 'test_*.py' -v
