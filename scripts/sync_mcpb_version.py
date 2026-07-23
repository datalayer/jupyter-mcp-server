#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Sync mcpb/manifest.json and mcpb/pyproject.toml's version fields to
jupyter_mcp_server/__version__.py, the single source of truth for the
package version (see #236).

Usage:
    python scripts/sync_mcpb_version.py          # rewrite the mcpb files in place
    python scripts/sync_mcpb_version.py --check  # exit 1 on drift, write nothing (for CI)
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "jupyter_mcp_server" / "__version__.py"
MANIFEST_FILE = ROOT / "mcpb" / "manifest.json"
PYPROJECT_FILE = ROOT / "mcpb" / "pyproject.toml"

PACKAGE_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
MANIFEST_VERSION_RE = re.compile(r'("version":\s*")[^"]+(")')
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_package_version(path: Path = VERSION_FILE) -> str:
    match = PACKAGE_VERSION_RE.search(path.read_text())
    if not match:
        raise SystemExit(f"could not find __version__ in {path}")
    return match.group(1)


def read_manifest_version(path: Path = MANIFEST_FILE) -> str:
    return json.loads(path.read_text())["version"]


def read_pyproject_version(path: Path = PYPROJECT_FILE) -> str:
    match = PYPROJECT_VERSION_RE.search(path.read_text())
    if not match:
        raise SystemExit(f"could not find version in {path}")
    return match.group(1)


def write_manifest_version(version: str, path: Path = MANIFEST_FILE) -> None:
    text = path.read_text()
    new_text, count = MANIFEST_VERSION_RE.subn(rf"\g<1>{version}\g<2>", text, count=1)
    if count != 1:
        raise SystemExit(f"could not find version in {path}")
    path.write_text(new_text)


def write_pyproject_version(version: str, path: Path = PYPROJECT_FILE) -> None:
    text = path.read_text()
    new_text, count = PYPROJECT_VERSION_RE.subn(f'version = "{version}"', text, count=1)
    if count != 1:
        raise SystemExit(f"could not find version in {path}")
    path.write_text(new_text)


def find_drift(package_version: str, manifest_version: str, pyproject_version: str) -> list:
    """Return one message per mcpb file whose version does not match package_version."""
    drift = []
    if manifest_version != package_version:
        drift.append(f"mcpb/manifest.json is {manifest_version}, expected {package_version}")
    if pyproject_version != package_version:
        drift.append(f"mcpb/pyproject.toml is {pyproject_version}, expected {package_version}")
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the mcpb files match the package version without writing",
    )
    args = parser.parse_args()

    package_version = read_package_version()
    manifest_version = read_manifest_version()
    pyproject_version = read_pyproject_version()

    if args.check:
        drift = find_drift(package_version, manifest_version, pyproject_version)
        if drift:
            for line in drift:
                print(line, file=sys.stderr)
            print("run `python scripts/sync_mcpb_version.py` to fix", file=sys.stderr)
            return 1
        print(f"mcpb version files match package version {package_version}")
        return 0

    if manifest_version != package_version:
        write_manifest_version(package_version)
        print(f"mcpb/manifest.json: {manifest_version} -> {package_version}")
    if pyproject_version != package_version:
        write_pyproject_version(package_version)
        print(f"mcpb/pyproject.toml: {pyproject_version} -> {package_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
