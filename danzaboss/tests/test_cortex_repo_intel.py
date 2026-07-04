"""Repo intelligence: stdlib analyzers -> file/module/symbol graph (C4).

The acceptance test at the bottom runs the scanner over THIS repository and
asserts real dependency closures — "what breaks if observation.py changes"
must include store.py and retrieve.py (spec section 8, C4 acceptance).
"""
import os
import tempfile
import textwrap
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore
from danzaboss.cortex.repo_intel import PythonAnalyzer, RegexAnalyzer, scan_repo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPythonAnalyzer(unittest.TestCase):
    def test_module_imports_and_symbols(self):
        src = textwrap.dedent("""\
            import json
            import pkg.util
            from pkg.core import thing
            from .sibling import x
            from ..other import y

            def top(): ...

            class Widget: ...
        """)
        fi = PythonAnalyzer().analyze("pkg/sub/mod.py", src)
        self.assertEqual(fi.module, "pkg.sub.mod")
        self.assertIn("json", fi.imports)
        self.assertIn("pkg.util", fi.imports)
        self.assertIn("pkg.core.thing", fi.imports)
        self.assertIn("pkg.sub.sibling", fi.imports)   # level 1
        self.assertIn("pkg.other", fi.imports)          # level 2
        self.assertIn(("function", "top"), fi.symbols)
        self.assertIn(("class", "Widget"), fi.symbols)

    def test_init_module_name(self):
        fi = PythonAnalyzer().analyze("pkg/__init__.py", "")
        self.assertEqual(fi.module, "pkg")

    def test_syntax_error_yields_empty_intel(self):
        fi = PythonAnalyzer().analyze("bad.py", "def broken(:")
        self.assertEqual(fi.imports, [])
        self.assertEqual(fi.symbols, [])


class TestRegexAnalyzer(unittest.TestCase):
    def test_js_imports_and_symbols(self):
        src = 'import { a } from "./util.js";\nconst b = require("lodash");\n' \
              'export function draw() {}\nclass Panel {}\n'
        fi = RegexAnalyzer().analyze("web/app.js", src)
        self.assertIn("./util.js", fi.imports)
        self.assertIn("lodash", fi.imports)
        self.assertIn(("function", "draw"), fi.symbols)
        self.assertIn(("class", "Panel"), fi.symbols)


class TestScanRepo(unittest.TestCase):
    def test_scan_builds_file_to_file_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"))
            open(os.path.join(tmp, "pkg", "__init__.py"), "w").close()
            with open(os.path.join(tmp, "pkg", "core.py"), "w") as fh:
                fh.write("VALUE = 1\n")
            with open(os.path.join(tmp, "pkg", "api.py"), "w") as fh:
                fh.write("from pkg.core import VALUE\nimport os\n")
            g = GraphStore(":memory:")
            stats = scan_repo(tmp, "p", g)
            self.assertEqual(stats["imports_resolved"], 1)
            self.assertEqual(
                g.impact("file:pkg/core.py"), [("file:pkg/api.py", 1)])
            n = g.neighbors("file:pkg/api.py", relation="imports")
            self.assertIn(("module:os", "imports"), n["out"])

    def test_scan_skips_ignore_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "__pycache__"))
            with open(os.path.join(tmp, "__pycache__", "junk.py"), "w") as fh:
                fh.write("import os\n")
            g = GraphStore(":memory:")
            scan_repo(tmp, "p", g)
            self.assertEqual(g.stats()["nodes"], 0)


class TestSelfRepoAcceptance(unittest.TestCase):
    """C4 acceptance: correct dependency closures on this repository itself."""

    @classmethod
    def setUpClass(cls):
        cls.g = GraphStore(":memory:")
        scan_repo(REPO_ROOT, "DANZA-OS", cls.g)

    def test_impact_of_observation_py(self):
        broke = {nid for nid, _ in
                 self.g.impact("file:danzaboss/cortex/observation.py", max_depth=6)}
        self.assertIn("file:danzaboss/cortex/store.py", broke)
        self.assertIn("file:danzaboss/cortex/retrieve.py", broke)
        self.assertIn("file:danzaboss/cortex/commands.py", broke)

    def test_dependencies_of_retrieve_py(self):
        deps = {nid for nid, _ in
                self.g.dependencies("file:danzaboss/cortex/retrieve.py", max_depth=1)}
        self.assertIn("file:danzaboss/cortex/intent.py", deps)
        self.assertIn("file:danzaboss/cortex/observation.py", deps)
        self.assertIn("file:danzaboss/cortex/store.py", deps)

    def test_symbols_declared(self):
        self.assertIsNotNone(
            self.g.node("symbol:danzaboss/cortex/graph.py::GraphStore"))


if __name__ == "__main__":
    unittest.main()
