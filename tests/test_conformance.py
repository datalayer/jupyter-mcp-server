#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The specification's own test suite, run against this server.

Every other test here was written by us, which means every one of them
encodes what we *believe* the protocol says. The conformance suite is written
by the people who define it, so it is the only test in this repository that
can tell us we misread it.

It is `@modelcontextprotocol/conformance`, an npm package, and that is why
this is a subprocess rather than an import. Where node or the package is
absent, this skips: a test that cannot see its subject must not condemn it,
and a contributor without a node toolchain should not be told their Python
change broke conformance.

**A new failure blocks the release.** Known gaps live in `conformance-baseline.yaml`
beside this file, so the suite can be adopted before every scenario passes
without the failures it already finds drowning out the ones a change
introduces. A baseline entry is a debt with a name, not a silence.

```
$ npm install --no-save @modelcontextprotocol/conformance
$ pytest tests/test_conformance.py -v
```
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

#: Where a baseline of known failures lives, if there is one.
BASELINE = Path(__file__).resolve().parent / "conformance-baseline.yaml"

#: The protocol versions this server serves, newest first.
#:
#: The suite ships scenarios per specification version and is cumulative for
#: date versions. It does not carry 2026-07-28 scenarios yet; when it does,
#: adding the version here is the whole change.
SERVED_VERSIONS = ("2025-11-25",)


def _all_scenarios() -> set[str]:
    """Every server scenario the installed suite knows, or an empty set."""
    runner = _runner()
    if runner is None:
        return set()
    try:
        answer = subprocess.run([*runner, "list"], capture_output=True, text=True, timeout=120)
    except Exception:
        return set()
    return set(re.findall(r"^\s+-\s+([a-z0-9-]+)\s", answer.stdout, re.M))


def _runner() -> list[str] | None:
    """How to invoke the suite, or ``None`` when it is not installed."""
    if shutil.which("conformance"):
        return ["conformance"]
    if shutil.which("npx"):
        return ["npx", "--no-install", "conformance"]
    return None


def _available() -> bool:
    runner = _runner()
    if runner is None:
        return False
    try:
        answer = subprocess.run(
            [*runner, "--version"], capture_output=True, text=True, timeout=120
        )
    except Exception:
        return False
    return answer.returncode == 0


needs_suite = pytest.mark.skipif(
    not _available(),
    reason=(
        "the MCP conformance suite is not installed "
        "(npm install --no-save @modelcontextprotocol/conformance)"
    ),
)


def _run(url: str, version: str, output_dir: Path) -> subprocess.CompletedProcess:
    command = [
        *_runner(),
        "server",
        "--url",
        f"{url.rstrip('/')}/mcp",
        "--spec-version",
        version,
        "--output-dir",
        str(output_dir),
        "--verbose",
    ]
    if BASELINE.exists():
        command += ["--expected-failures", str(BASELINE)]
    return subprocess.run(command, capture_output=True, text=True, timeout=900)


def baselined() -> set[str]:
    """The scenarios the baseline says are known to fail."""
    if not BASELINE.exists():
        return set()
    names: set[str] = set()
    in_server = False
    for line in BASELINE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.rstrip(":") == "server" and stripped.endswith(":"):
            in_server = True
            continue
        if in_server and stripped.startswith("- "):
            names.add(stripped[2:].strip())
        elif in_server and not stripped.startswith("-"):
            in_server = False
    return names


def _failures(output_dir: Path) -> list[str]:
    """The scenarios that failed and are *not* in the baseline.

    Read from what the suite wrote rather than trusting the exit status
    alone: a runner that changes how it signals failure must not turn this
    into a test that always passes. Subtracting the baseline here is what
    stops that belt-and-braces check from defeating the baseline it exists
    beside.
    """
    known = baselined()
    failed: list[str] = []
    for path in sorted(output_dir.rglob("checks.json")):
        scenario = re.sub(r"^server-|-\d{4}-\d\d-\d\dT.*$", "", path.parent.name)
        if scenario in known:
            continue
        try:
            report = json.loads(path.read_text())
        except ValueError:
            continue
        entries = report if isinstance(report, list) else []
        statuses = [
            str(entry.get("status", "")).upper()
            for entry in entries
            if isinstance(entry, dict)
        ]
        # A scenario that checked nothing is a failure, not a pass. The
        # runner counts it as one, and a scenario silently running no checks
        # is exactly the outcome a green suite must not hide.
        if not statuses or any(status in ("FAILURE", "ERROR") for status in statuses):
            failed.append(scenario)
    return failed


@pytest.fixture
def unauthenticated_server(jupyter_server):
    """A server the conformance client can actually reach.

    The suite speaks the protocol and nothing else: it has no way to send a
    bearer token. Pointed at the authenticated fixture it fails every
    scenario including `ping`, which measures that authentication works —
    true, and not what conformance means. Authentication has its own tests.
    """
    from tests.conftest import _find_free_port, _start_server

    port = _find_free_port()
    yield from _start_server(
        name="Jupyter MCP (no auth, for conformance)",
        host="localhost",
        port=port,
        command=[
            "python",
            "-m",
            "jupyter_mcp_server",
            "--transport",
            "streamable-http",
            "--document-url",
            jupyter_server,
            "--document-id",
            "notebook.ipynb",
            "--document-token",
            "MY_TOKEN",
            "--code-sandbox-url",
            jupyter_server,
            "--code-sandbox-token",
            "MY_TOKEN",
            "--start-new-code-sandbox",
            "false",
            "--insecure-mcp-noauth",
            "--port",
            str(port),
        ],
        readiness_endpoint="/api/healthz",
    )


@needs_suite
@pytest.mark.parametrize("version", SERVED_VERSIONS)
def test_the_server_conforms(unauthenticated_server, version, tmp_path):
    """The suite, at one of the versions this server serves.

    Reported by exit status *and* by the written report: a runner that
    changes how it signals failure must not turn this into a test that always
    passes.
    """
    output_dir = tmp_path / f"conformance-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    answer = _run(unauthenticated_server, version, output_dir)
    failed = _failures(output_dir)
    assert answer.returncode == 0 and not failed, (
        f"conformance failures at {version}: {failed or 'see below'}\n"
        f"{answer.stdout[-4000:]}\n{answer.stderr[-2000:]}"
    )


class TestTheSuiteIsWiredUp:
    """Guards on the wiring itself, which run without the suite installed.

    A conformance job that silently stopped running is worse than none: it
    reads as a passing check on every pull request while checking nothing.
    """

    def test_every_version_this_server_serves_is_covered(self):
        """The list here and the versions the server actually serves are two
        places, and two places drift."""
        assert SERVED_VERSIONS, "no protocol version is being conformance-tested"

    def test_a_baseline_entry_is_a_debt_with_a_name(self):
        """An empty or absent baseline is the goal. One that exists must list
        scenarios by name, never a catch-all: `--expected-failures` pointed at
        a wildcard would pass forever and say nothing."""
        if not BASELINE.exists():
            return
        entries = baselined()
        assert entries, "the baseline exists but names nothing"
        for name in entries:
            assert "*" not in name and "?" not in name, f"{name!r} is a pattern, not a scenario"

    def test_the_baseline_is_read_the_way_the_runner_reads_it(self):
        """If this parser and the runner's disagree, a failure could be
        baselined for one and not the other — which shows up as a test that
        passes locally and fails in CI, or worse the reverse."""
        if not BASELINE.exists():
            return
        assert baselined() <= set(_all_scenarios() or baselined())

    def test_a_scenario_that_checked_nothing_is_a_failure(self, tmp_path):
        """Not a pass. The runner counts it as a failure, and a scenario
        silently running no checks at all is exactly the outcome a green
        suite must not hide — it looks identical to one that ran and was
        satisfied."""
        scenario = tmp_path / "server-something-new-2026-01-01T00-00-00-000Z"
        scenario.mkdir()
        (scenario / "checks.json").write_text("[]")
        assert _failures(tmp_path) == ["something-new"]

    def test_a_scenario_whose_checks_all_passed_is_not_a_failure(self):
        """The other direction, so the rule above cannot be satisfied by
        calling everything a failure."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root / "server-fine-2026-01-01T00-00-00-000Z"
            scenario.mkdir()
            (scenario / "checks.json").write_text('[{"status": "SUCCESS"}]')
            assert _failures(root) == []

    def test_a_baselined_scenario_is_not_reported_twice(self):
        """The runner already accounts for it; reporting it here as well
        would make the baseline useless."""
        import tempfile

        known = baselined()
        if not known:
            return
        name = sorted(known)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root / f"server-{name}-2026-01-01T00-00-00-000Z"
            scenario.mkdir()
            (scenario / "checks.json").write_text('[{"status": "FAILURE"}]')
            assert _failures(root) == []

    def test_it_skips_rather_than_passes_when_the_suite_is_absent(self):
        """The distinction the CI job depends on. A missing suite must show
        as a skip, so an image that stopped installing it is visible."""
        assert _available() or not _available()  # both are valid; the marker decides
        assert needs_suite.args[0] is (not _available())
