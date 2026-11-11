# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Does a cell executed by `execute_cell` show its output while it runs?

A cell run from the JupyterLab UI writes each output into the notebook as the
kernel produces it. A cell run through `execute_cell` in MCP_SERVER mode used
not to: it executed on the code-sandboxes client, whose `execute_interactive`
collects the outputs and replays them into the notebook only when the
execution ends. Until then, anybody reading the cell — a person in JupyterLab,
another agent, a `read_cell` on another request — saw no output at all. Cells
now execute on the sandbox's own kernel client (`cell_execution_client`),
which hands the notebook each output as it arrives.

The cell under test prints a first tag and raises a flag, waits for the test
to say go, prints a second tag and raises a second flag, then hangs. The
kernel and this test share a filesystem, so a raised flag proves the print
before it has already happened; whatever the notebook shows from then on is
what a reader would see.

* `TestOutputIsVisibleWhileTheCellRuns` reads the cell after each print while
  it still runs. The second print catches an implementation that publishes
  once and buffers everything after.
* `TestOutputSurvivesStoppingTheCell` stops the cell — with an interrupt of
  its kernel, as the UI's Stop button does, or by letting the tool's own
  timeout expire — and reads it again. The printed tag must still be there,
  and the stop must have come from the mechanism under test: the tool's
  timeout interrupts through the same client the cell executes on.

MCP_SERVER mode only (`mcp_client`): the mode the code-sandboxes client is in.

Launch the tests:
```
$ pytest tests/test_execute_cell_streams_outputs_live.py -v
```
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest

from .conftest import JUPYTER_TOKEN

CONTENT_DIR = Path("dev/content")

#: How long a streamed output may take to reach the notebook once printed.
#: Live, it takes well under a second; this only absorbs a loaded CI machine.
STREAM_GRACE_SECONDS = 10

#: The tool's own deadline when a test does not want it to fire. Bounds the
#: hanging cell if the cleanup interrupt never lands.
SAFETY_TIMEOUT_SECONDS = 120

#: The tool's deadline when the test stops the cell by letting it expire.
#: Long enough for the first execution to connect to the kernel.
TOOL_TIMEOUT_SECONDS = 20


@dataclass
class Scratch:
    """A notebook of its own, two unique tags, and the files the cell uses."""

    file: str
    first_tag: str
    second_tag: str
    first_printed: Path
    go: Path
    second_printed: Path

    @property
    def name(self) -> str:
        return self.file.removesuffix(".ipynb")


@dataclass
class Running:
    """A cell whose `execute_cell` call is in flight."""

    execution: asyncio.Task
    kernel_id: str
    started: float


@pytest.fixture
def scratch(tmp_path) -> Scratch:
    notebook_file = f"streaming_{uuid.uuid4().hex[:8]}.ipynb"
    yield Scratch(
        file=notebook_file,
        first_tag=f"FIRST-{uuid.uuid4().hex}",
        second_tag=f"SECOND-{uuid.uuid4().hex}",
        first_printed=tmp_path / "first.flag",
        go=tmp_path / "go.flag",
        second_printed=tmp_path / "second.flag",
    )
    (CONTENT_DIR / notebook_file).unlink(missing_ok=True)


def _assembled(tag: str) -> str:
    """The tag as an expression built at run time.

    `read_cell` returns the source along with the outputs, so a tag written
    out whole in the source would be "found" whether or not the cell ever
    printed it.
    """
    return f"{tag[: len(tag) // 2]!r} + {tag[len(tag) // 2 :]!r}"


def _two_print_cell(s: Scratch) -> str:
    return (
        "import pathlib, time\n"
        f"print({_assembled(s.first_tag)}, flush=True)\n"
        f"pathlib.Path({str(s.first_printed)!r}).touch()\n"
        f"while not pathlib.Path({str(s.go)!r}).exists():\n"
        "    time.sleep(0.1)\n"
        f"print({_assembled(s.second_tag)}, flush=True)\n"
        f"pathlib.Path({str(s.second_printed)!r}).touch()\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    )


def _text(result) -> str:
    """Everything a tool result says, text and structured, as one string."""
    parts = [getattr(c, "text", "") for c in result.content]
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        parts.append(json.dumps(structured))
    return "\n".join(parts)


async def _read_cell(session, cell_index: int = 0) -> str:
    result = await asyncio.wait_for(
        session.call_tool("read_cell", {"cell_index": cell_index, "include_outputs": True}),
        timeout=30,
    )
    return _text(result)


async def _read_until(session, tag: str, seconds: float = STREAM_GRACE_SECONDS) -> str:
    """Read the cell until the tag shows up or `seconds` pass; the last read."""
    deadline = time.monotonic() + seconds
    seen = await _read_cell(session)
    while tag not in seen and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        seen = await _read_cell(session)
    return seen


async def _wait_for_flag(flag: Path, execution: asyncio.Task, seconds: float = 60) -> None:
    """Until the kernel has raised `flag`; fails if the execution ends first."""
    deadline = time.monotonic() + seconds
    while not flag.exists():
        if execution.done():
            outcome = execution.exception() or _text(execution.result())
            pytest.fail(f"execute_cell returned before the cell raised {flag.name}: {outcome!r}")
        if time.monotonic() > deadline:
            pytest.fail(f"the cell did not raise {flag.name} within {seconds}s")
        await asyncio.sleep(0.1)


def _jupyter(jupyter_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=jupyter_url, headers={"Authorization": f"token {JUPYTER_TOKEN}"}, timeout=10
    )


async def _kernel_of(jupyter_url: str, notebook_file: str) -> str | None:
    """The kernel of the Jupyter session this server registered for the notebook."""
    async with _jupyter(jupyter_url) as http:
        sessions = (await http.get("/api/sessions")).json()
    for session in sessions:
        path = session.get("path") or ""
        if path == notebook_file or path.endswith(f"/{notebook_file}"):
            return session["kernel"]["id"]
    return None


async def _interrupt(jupyter_url: str, kernel_id: str) -> None:
    """What the UI's Stop button does, for this notebook's kernel only."""
    async with _jupyter(jupyter_url) as http:
        (await http.post(f"/api/kernels/{kernel_id}/interrupt")).raise_for_status()


@asynccontextmanager
async def running_cell(client, jupyter_url: str, s: Scratch, timeout: int):
    """Start the cell, wait for its first print, and always stop it after.

    Everything from the moment the `execute_cell` task exists is inside the
    `finally`, so a failure anywhere — the flag never raised, the kernel not
    found, an assertion in the test body — still interrupts the cell and
    waits for the tool call to return.
    """
    await client.use_notebook(s.name, s.file, mode="create")
    await client.insert_cell(0, "code", _two_print_cell(s))
    before = await _read_cell(client._session)
    assert s.first_tag not in before and s.second_tag not in before, (
        f"a tag is readable before the cell ran, so finding it proves nothing:\n{before}"
    )

    started = time.monotonic()
    execution = asyncio.create_task(
        client._session.call_tool("execute_cell", {"cell_index": 0, "timeout": timeout})
    )
    kernel_id = None
    try:
        await _wait_for_flag(s.first_printed, execution)
        kernel_id = await _kernel_of(jupyter_url, s.file)
        assert kernel_id, f"no Jupyter session for {s.file}, so no kernel to interrupt"
        yield Running(execution=execution, kernel_id=kernel_id, started=started)
    finally:
        if not execution.done():
            kernel_id = kernel_id or await _kernel_of(jupyter_url, s.file)
            if kernel_id:
                await _interrupt(jupyter_url, kernel_id)
            else:
                execution.cancel()
        try:
            await asyncio.wait_for(execution, timeout=60)
        except (Exception, asyncio.CancelledError) as e:
            # Cleanup only: the test already has its verdict.
            logging.warning("stopping the hanging cell: %r", e)


class TestOutputIsVisibleWhileTheCellRuns:
    @pytest.mark.asyncio
    async def test_each_print_is_readable_before_the_cell_finishes(
        self, mcp_client, jupyter_server, scratch
    ):
        """The kernel has printed; the notebook should say so, every time.

        Fails while execute_cell replays outputs only at the end of the run.
        """
        async with mcp_client as client:
            session = client._session
            async with running_cell(client, jupyter_server, scratch, SAFETY_TIMEOUT_SECONDS) as run:
                seen = await _read_until(session, scratch.first_tag)
                assert not run.execution.done(), "the cell stopped before it could be read"
                assert scratch.first_tag in seen, (
                    f"the cell printed {scratch.first_tag!r} but, {STREAM_GRACE_SECONDS}s "
                    f"later and still running, the notebook shows none of it:\n{seen}"
                )

                scratch.go.touch()
                await _wait_for_flag(scratch.second_printed, run.execution)
                seen = await _read_until(session, scratch.second_tag)
                assert not run.execution.done(), "the cell stopped before it could be read"
                assert scratch.second_tag in seen, (
                    f"the first print reached the notebook while the cell ran, but the "
                    f"second, {scratch.second_tag!r}, did not within "
                    f"{STREAM_GRACE_SECONDS}s:\n{seen}"
                )


class TestOutputSurvivesStoppingTheCell:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("stop", ["kernel_interrupt", "tool_timeout"])
    async def test_a_printed_tag_is_kept_when_the_cell_is_stopped(
        self, mcp_client, jupyter_server, scratch, stop
    ):
        """Stopped mid-run, the cell keeps what it printed before the stop."""
        timeout = SAFETY_TIMEOUT_SECONDS if stop == "kernel_interrupt" else TOOL_TIMEOUT_SECONDS
        async with mcp_client as client:
            async with running_cell(client, jupyter_server, scratch, timeout) as run:
                if stop == "kernel_interrupt":
                    await _interrupt(jupyter_server, run.kernel_id)
                answer = _text(await asyncio.wait_for(run.execution, timeout=timeout + 60))
                took = time.monotonic() - run.started

            seen = await _read_until(client._session, scratch.first_tag)

        if stop == "tool_timeout":
            assert "TIMEOUT" in answer, f"execute_cell did not say it timed out:\n{answer}"
            assert took >= TOOL_TIMEOUT_SECONDS, (
                f"execute_cell returned after {took:.1f}s, before its "
                f"{TOOL_TIMEOUT_SECONDS}s timeout could have stopped the cell"
            )
        else:
            assert "TIMEOUT" not in answer, (
                f"the kernel interrupt should have stopped the cell, not the timeout:\n{answer}"
            )
        assert "KeyboardInterrupt" in seen, f"the cell was not interrupted:\n{seen}"
        assert scratch.first_tag in seen, (
            f"the cell printed {scratch.first_tag!r} before it was stopped ({stop}), "
            f"but the notebook kept none of it:\n{seen}\n\nexecute_cell answered:\n{answer}"
        )
