"""Phase-1 T1 packaging: pyproject metadata matches D1/D2 and the version has
a single source of truth in danzaboss.__version__.

tomllib is 3.11+; the assertions are skipped (not failed) on 3.10 — the
package still builds there because setuptools does its own TOML parsing.
"""
import re
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa
import danzaboss

REPO = Path(__file__).resolve().parents[2]


class VersionAttr(unittest.TestCase):
    def test_version_is_semver_string(self):
        self.assertTrue(re.fullmatch(r"\d+\.\d+\.\d+", danzaboss.__version__),
                        f"bad __version__: {danzaboss.__version__!r}")


@unittest.skipUnless(sys.version_info >= (3, 11), "tomllib requires 3.11+")
class PyprojectMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tomllib
        with open(REPO / "pyproject.toml", "rb") as fh:
            cls.data = tomllib.load(fh)

    def test_identity_and_zero_deps(self):
        proj = self.data["project"]
        self.assertEqual(proj["name"], "danza-os")
        self.assertEqual(proj["dependencies"], [])
        self.assertEqual(proj["requires-python"], ">=3.10")

    def test_console_script(self):
        self.assertEqual(self.data["project"]["scripts"]["danza"],
                         "danzaboss.cli:main")

    def test_neon_extra_is_optional(self):
        self.assertEqual(self.data["project"]["optional-dependencies"]["neon"],
                         ["psycopg[binary]"])

    def test_version_is_dynamic_from_package(self):
        self.assertIn("version", self.data["project"]["dynamic"])
        self.assertEqual(
            self.data["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "danzaboss.__version__")

    def test_package_data_ships_all_runtime_assets(self):
        pkg_data = self.data["tool"]["setuptools"]["package-data"]
        self.assertIn("templates/**/*", pkg_data["danzaboss.product"])
        self.assertIn("static/*", pkg_data["danzaboss.cortex.ui"])
        self.assertIn("plan_schema.json", pkg_data["danzaboss.planning"])
        self.assertIn("spec_template.md", pkg_data["danzaboss.planning"])
        self.assertIn("templates/stacks/*.json", pkg_data["danzaboss.workstation"])
        self.assertIn("team_state.schema.json", pkg_data["danzaboss.kernel"])

    def test_tests_excluded_from_wheel(self):
        find = self.data["tool"]["setuptools"]["packages"]["find"]
        self.assertIn("danzaboss.tests*", find["exclude"])
