"""Put the REPO ROOT on sys.path so `import danzaboss.<module>` resolves, and the
tests dir so `import _bootstrap` works, regardless of where tests are launched."""
import os
import sys
import tempfile

_TESTS = os.path.dirname(os.path.abspath(__file__))          # .../danza/tests
_PKG = os.path.dirname(_TESTS)                                # .../danza
_ROOT = os.path.dirname(_PKG)                                 # repo root (parent of danza)
for p in (_ROOT, _TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

# C6 hermeticity at the right depth: every test imports this module, so tests
# can never touch the developer's real ~/.danza global store — even when run
# directly (IDE, `python3 -m unittest tests.test_x`) instead of run_tests.sh.
os.environ.setdefault(
    "DANZA_CORTEX_GLOBAL_DB",
    os.path.join(tempfile.mkdtemp(prefix="danza-test-global-"), "global.db"))
os.environ.setdefault("DANZA_CORTEX_GLOBAL_DSN", "")
