#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Bump the version, in every file that carries a copy of it.

The version lives in four places. `pyproject.toml` does **not** carry a
fifth: hatch reads it from `__version__.py`, which is why that file is the
one this script treats as the source of truth — the others are copies, and a
copy that gets missed ships a package whose manifest disagrees with the
module it installs.

    python dev/bump_version.py patch     # 2.1.3 -> 2.1.4
    python dev/bump_version.py minor     # 2.1.3 -> 2.2.0
    python dev/bump_version.py major     # 2.1.3 -> 3.0.0
    python dev/bump_version.py           # asks

Nothing is written unless **every** file can be updated. A run that bumped
two of four and then hit a file whose format had changed would leave the tree
in a state where the next `make build` produces a package that is wrong in a
way nobody looks at. Either all of them move or none do.

@module dev.bump_version
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The file the version is read *from*. Hatch reads it too
#: (`[tool.hatch.version] path`), which is what makes it the source rather
#: than a fourth copy.
SOURCE = ROOT / "jupyter_mcp_server" / "__version__.py"

PARTS = ("major", "minor", "patch")


class Unbumpable(Exception):
    """A file this script cannot update, named with what it expected.

    Raised before anything is written. The alternative — updating what it
    can and reporting the rest — is how a release goes out with a manifest
    that disagrees with the module.
    """


def read_version() -> str:
    text = SOURCE.read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if match is None:
        raise Unbumpable(f"{SOURCE.relative_to(ROOT)} has no __version__ = \"...\"")
    return match.group(1)


def bump(version: str, part: str) -> str:
    """The next version, or a refusal naming what it could not read.

    Only `major.minor.patch`. A pre-release or a build tag would need rules
    about what bumping means for it — does `2.2.0rc1` patch to `2.2.0rc2` or
    to `2.2.1`? — and guessing one is worse than saying so.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise Unbumpable(
            f"{version!r} is not major.minor.patch; bump it by hand and say "
            "here what the next one should be"
        )
    major, minor, patch = (int(value) for value in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _replace_once(path: Path, pattern: str, replacement: str, current: str) -> str:
    """One substitution, refusing zero and refusing more than one.

    Zero means the file's format changed and this script is now editing
    nothing while reporting success. More than one means the pattern is
    matching something else as well — a dependency's version, say — and
    rewriting it would be a silent, wrong edit in a file nobody diffs.
    """
    text = path.read_text()
    # Multiline: the TOML pattern anchors `version =` to the start of a line,
    # which is what keeps it off `python-version` and off a dependency's pin.
    found = re.findall(pattern, text, flags=re.M)
    if len(found) != 1:
        raise Unbumpable(
            f"{path.relative_to(ROOT)}: expected exactly one "
            f"{current!r} matching {pattern!r}, found {len(found)}"
        )
    return re.sub(pattern, replacement, text, count=1, flags=re.M)


def planned_edits(current: str, new: str) -> dict[Path, str]:
    """Every file's new content, or an exception. Nothing is written here."""
    escaped = re.escape(current)
    edits: dict[Path, str] = {}

    edits[SOURCE] = _replace_once(
        SOURCE,
        rf'(__version__\s*=\s*")({escaped})(")',
        rf"\g<1>{new}\g<3>",
        current,
    )

    manifest = ROOT / "extensions" / "mcpb" / "manifest.json"
    edits[manifest] = _replace_once(
        manifest,
        rf'("version"\s*:\s*")({escaped})(")',
        rf"\g<1>{new}\g<3>",
        current,
    )

    mcpb_pyproject = ROOT / "extensions" / "mcpb" / "pyproject.toml"
    edits[mcpb_pyproject] = _replace_once(
        mcpb_pyproject,
        rf'(^version\s*=\s*")({escaped})(")',
        rf"\g<1>{new}\g<3>",
        current,
    )

    # The published server card. Its `version` is the *server's*, nested
    # under `server`; the file also carries `mcpSpec` and `mcpVersion`, which
    # are the protocol's and must not move with a release of ours.
    sourcey = ROOT / "docs" / "sourcey" / "mcp.json"
    edits[sourcey] = _replace_once(
        sourcey,
        rf'("version"\s*:\s*")({escaped})(")',
        rf"\g<1>{new}\g<3>",
        current,
    )

    return edits


def check_json(edits: dict[Path, str]) -> None:
    """Every JSON file still parses. A regex that produced valid-looking but
    broken JSON would be found by whoever installs the extension."""
    for path, text in edits.items():
        if path.suffix == ".json":
            try:
                json.loads(text)
            except ValueError as error:
                raise Unbumpable(f"{path.relative_to(ROOT)} would not parse: {error}")


def ask() -> str:
    print(f"Current version: {read_version()}")
    for index, part in enumerate(PARTS, start=1):
        print(f"  {index}) {part:5s} -> {bump(read_version(), part)}")
    while True:
        answer = input("Which? [major/minor/patch] ").strip().lower()
        if answer in PARTS:
            return answer
        if answer in ("1", "2", "3"):
            return PARTS[int(answer) - 1]
        print(f"Say one of: {', '.join(PARTS)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", nargs="?", choices=PARTS, help="what to bump")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would change and write nothing",
    )
    arguments = parser.parse_args(argv)

    try:
        current = read_version()
        part = arguments.part or ask()
        new = bump(current, part)
        edits = planned_edits(current, new)
        check_json(edits)
    except Unbumpable as error:
        print(f"Refused: {error}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1

    for path, text in sorted(edits.items()):
        if not arguments.dry_run:
            path.write_text(text)
        print(f"{'would bump' if arguments.dry_run else 'bumped'} {path.relative_to(ROOT)}")
    print(f"{current} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
