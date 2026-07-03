#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"                 # danza/
ROOT="$(cd .. && pwd)"              # repo root (so `import danzaboss works)
export PYTHONPATH="$ROOT:$(pwd)/tests"
echo "== DANZA test suite (promoted danzaboss/ package) =="
python3 -m unittest discover -s tests -p 'test_*.py' -v
