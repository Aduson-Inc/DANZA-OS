"""DANZABOSS — the promoted brain of DANZA-OS.

Single source of truth for the package version: pyproject.toml reads this
attribute via [tool.setuptools.dynamic], and scaffold.py stamps it into
.danza/.scaffold-version so `danza init --upgrade` (future) can diff.
"""
__version__ = "0.1.0"
