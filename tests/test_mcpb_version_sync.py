# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression test for #236: mcpb/manifest.json and mcpb/pyproject.toml must
track jupyter_mcp_server/__version__.py rather than drift independently.
"""

import json
import re
from pathlib import Path

from scripts.sync_mcpb_version import find_drift

ROOT = Path(__file__).resolve().parent.parent


def _package_version() -> str:
    text = (ROOT / "jupyter_mcp_server" / "__version__.py").read_text()
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def test_manifest_version_matches_package_version():
    manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text())
    assert manifest["version"] == _package_version()


def test_mcpb_pyproject_version_matches_package_version():
    text = (ROOT / "mcpb" / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match.group(1) == _package_version()


def test_find_drift_reports_each_mismatched_file():
    assert find_drift("1.0.7", "1.0.7", "1.0.7") == []
    assert find_drift("1.0.7", "0.22.1", "1.0.7") == [
        "mcpb/manifest.json is 0.22.1, expected 1.0.7"
    ]
    assert find_drift("1.0.7", "0.22.1", "1.0.0") == [
        "mcpb/manifest.json is 0.22.1, expected 1.0.7",
        "mcpb/pyproject.toml is 1.0.0, expected 1.0.7",
    ]
