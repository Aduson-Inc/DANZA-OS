"""danza init - idempotent scaffold of .claude/ + .danza/ into a target repo.

An activated repo gets its own COPIES of the DANZA system files (agents,
constitution, skills, hook settings) and bootstrap state - copies, not
symlinks, so activated repos survive OS upgrades (spec D1). The scaffold is
idempotent and encodes Rules 34-35: templates and state are never blind-
overwritten; every file lands as created, merged, or skipped with a reason,
and a user-edited file is never touched.

.danza/.scaffold-version records the package version and the sha256 of every
bundled file at scaffold time, so a future `danza init --upgrade` can diff
what the user changed against what the OS changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import danzaboss

SCAFFOLD_VERSION_RELPATH = Path(".danza") / ".scaffold-version"
CLAUDE_MD_BEGIN = ("<!-- DANZA:BEGIN managed by `danza init` "
                   "- do not edit inside this block -->")
CLAUDE_MD_END = "<!-- DANZA:END -->"

# payload dir name -> target dir name. Dotted names never appear inside the
# bundled payload (packaging globs and resource walkers skip dotfiles
# unreliably), so the mapping happens here at copy time.
_PAYLOAD_DIRS = {"claude": ".claude", "danza": ".danza"}

# runtime dirs the product needs but that ship empty: represented by generated
# .gitkeep entries rather than payload files (no dotfiles in package data).
_KEEP_FILES = (Path(".danza") / "logs" / ".gitkeep",
               Path(".danza") / "runtime" / ".gitkeep")


class ScaffoldError(ValueError):
    """Unusable target directory or missing/corrupt bundled payload."""


@dataclass(frozen=True)
class FileResult:
    """Outcome for one scaffolded file (repo-relative POSIX path)."""
    path: str
    status: str        # "created" | "merged" | "skipped"
    reason: str = ""   # "" | "up-to-date" | "user-modified"


def _payload_root():
    root = files("danzaboss.product") / "templates" / "scaffold"
    if not root.is_dir():
        raise ScaffoldError(
            "bundled scaffold payload missing - broken installation; "
            "reinstall danza-os")
    return root


def _walk(node, rel: Path):
    """Yield (relative Path, bytes) for every file under a Traversable."""
    for child in node.iterdir():
        if child.is_dir():
            yield from _walk(child, rel / child.name)
        else:
            yield rel / child.name, child.read_bytes()


def _iter_payload():
    """Every file the scaffold owns: (target-relative Path, content bytes),
    deterministically sorted. Includes the generated .gitkeep entries."""
    entries: list[tuple[Path, bytes]] = []
    root = _payload_root()
    for src_name, dst_name in _PAYLOAD_DIRS.items():
        base = root / src_name
        if not base.is_dir():
            raise ScaffoldError(f"payload dir {src_name!r} missing - broken install")
        entries.extend((Path(dst_name) / rel, content)
                       for rel, content in _walk(base, Path()))
    entries.extend((keep, b"") for keep in _KEEP_FILES)
    return sorted(entries, key=lambda e: e[0].as_posix())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_manifest(target: Path, entries) -> None:
    """Atomic write (tmp -> os.replace), same idiom as runners.save_runners."""
    manifest = {"version": danzaboss.__version__,
                "files": {rel.as_posix(): _sha256(content)
                          for rel, content in entries}}
    path = target / SCAFFOLD_VERSION_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def scaffold(target: str | os.PathLike) -> list[FileResult]:
    """Copy/merge the bundled payload into *target*. Returns one FileResult
    per file. Never overwrites a file that differs from the bundle (Rule 35);
    identical files skip as up-to-date, so re-runs are no-ops."""
    root = Path(target)
    if not root.is_dir():
        raise ScaffoldError(f"target is not a directory: {root}")

    entries = _iter_payload()
    results: list[FileResult] = []
    for rel, content in entries:
        dst = root / rel
        posix = rel.as_posix()
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content)
            results.append(FileResult(posix, "created"))
        elif dst.read_bytes() == content:
            results.append(FileResult(posix, "skipped", "up-to-date"))
        else:
            results.append(FileResult(posix, "skipped", "user-modified"))

    results.append(_merge_claude_md(root))
    _write_manifest(root, entries)
    return results


def _managed_block() -> str:
    body = (files("danzaboss.product") / "templates"
            / "claude-md-managed-block.md").read_text(encoding="utf-8").strip()
    return f"{CLAUDE_MD_BEGIN}\n{body}\n{CLAUDE_MD_END}"


def _merge_claude_md(root: Path) -> FileResult:
    """Create CLAUDE.md or maintain the DANZA managed block inside it.

    Only the text between the BEGIN/END markers is ever rewritten - the
    user's own CLAUDE.md content is untouchable (Rule 35). One marker
    without the other means a hand-mangled block: fail closed rather than
    guess where the user's content ends."""
    path = root / "CLAUDE.md"
    block = _managed_block()
    if not path.exists():
        path.write_text(block + "\n", encoding="utf-8")
        return FileResult("CLAUDE.md", "created")

    text = path.read_text(encoding="utf-8")
    n_begin, n_end = text.count(CLAUDE_MD_BEGIN), text.count(CLAUDE_MD_END)
    if (n_begin, n_end) not in ((0, 0), (1, 1)):
        # A lone or duplicated marker means a hand-mangled block; splitting
        # on the first occurrence would silently eat user content or leave a
        # dangling marker that corrupts every later merge. Fail closed.
        raise ScaffoldError(
            f"CLAUDE.md managed block markers are corrupt "
            f"({n_begin}x BEGIN, {n_end}x END; expected exactly one pair or "
            f"none) - repair the block by hand, then re-run danza init")
    if n_begin:
        pre, rest = text.split(CLAUDE_MD_BEGIN, 1)
        _machine_owned, post = rest.split(CLAUDE_MD_END, 1)
        merged = pre + block + post
        if merged == text:
            return FileResult("CLAUDE.md", "skipped", "up-to-date")
        path.write_text(merged, encoding="utf-8")
        return FileResult("CLAUDE.md", "merged")

    appended = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(appended, encoding="utf-8")
    return FileResult("CLAUDE.md", "merged")
