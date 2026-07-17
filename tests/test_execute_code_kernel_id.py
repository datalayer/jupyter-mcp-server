# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for execute_code(kernel_id=...) kernel targeting in MCP_SERVER mode.

These run against the real Jupyter server fixture with two real kernels, since
what is under test is which kernel the code actually reaches.
"""

import pytest
from jupyter_kernel_client import KernelClient
from jupyter_server_client import JupyterServerClient

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool
from jupyter_mcp_server.utils import safe_extract_outputs, wait_for_kernel_idle

from .conftest import JUPYTER_TOKEN


@pytest.fixture
def targeting_setup(jupyter_server):
    """Two live kernels, each holding a distinct MARKER, with the first bound to
    the current notebook. Yields (notebook_manager, server_client, raw_kernel_id).
    """
    set_config(runtime_url=jupyter_server, runtime_token=JUPYTER_TOKEN)
    server_client = JupyterServerClient(base_url=jupyter_server, token=JUPYTER_TOKEN)

    current_kernel = KernelClient(server_url=jupyter_server, token=JUPYTER_TOKEN)
    current_kernel.start()
    raw_kernel = KernelClient(server_url=jupyter_server, token=JUPYTER_TOKEN)
    raw_kernel.start()

    try:
        # Give each kernel its own identity so the assertion cannot pass by luck.
        current_kernel.execute("MARKER = 'current-notebook-kernel'")
        raw_kernel.execute("MARKER = 'raw-kernel'")

        notebook_manager = NotebookManager()
        notebook_manager.add_notebook(
            "nb",
            current_kernel,
            server_url=jupyter_server,
            token=JUPYTER_TOKEN,
            path="nb.ipynb",
        )
        notebook_manager.set_current_notebook("nb")

        yield notebook_manager, server_client, raw_kernel.id
    finally:
        current_kernel.stop()
        raw_kernel.stop()
        reset_config()


async def _execute(notebook_manager, server_client, code, kernel_id=None):
    def _no_kernel_expected():
        raise AssertionError("the current notebook already has a kernel")

    return await ExecuteCodeTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=server_client,
        notebook_manager=notebook_manager,
        code=code,
        timeout=30,
        kernel_id=kernel_id,
        ensure_kernel_alive_fn=_no_kernel_expected,
        wait_for_kernel_idle_fn=wait_for_kernel_idle,
        safe_extract_outputs_fn=safe_extract_outputs,
    )


@pytest.mark.asyncio
async def test_execute_code_runs_in_the_requested_kernel(targeting_setup):
    """kernel_id must select the kernel the code runs in, not be discarded."""
    notebook_manager, server_client, raw_kernel_id = targeting_setup

    outputs = await _execute(
        notebook_manager, server_client, "print(MARKER)", kernel_id=raw_kernel_id
    )

    assert "raw-kernel" in "".join(str(output) for output in outputs)


@pytest.mark.asyncio
async def test_execute_code_leaves_the_targeted_kernel_running(targeting_setup):
    """The targeted kernel is borrowed, so it must survive the call and keep its
    state: releasing the connection must not shut a kernel down."""
    notebook_manager, server_client, raw_kernel_id = targeting_setup

    await _execute(notebook_manager, server_client, "print(MARKER)", kernel_id=raw_kernel_id)

    assert any(kernel.id == raw_kernel_id for kernel in server_client.kernels.list_kernels())

    outputs = await _execute(
        notebook_manager, server_client, "print(MARKER)", kernel_id=raw_kernel_id
    )
    assert "raw-kernel" in "".join(str(output) for output in outputs)


@pytest.mark.asyncio
async def test_execute_code_without_kernel_id_uses_the_current_notebook(targeting_setup):
    """Omitting kernel_id keeps the documented default: the current notebook's kernel."""
    notebook_manager, server_client, _ = targeting_setup

    outputs = await _execute(notebook_manager, server_client, "print(MARKER)")

    assert "current-notebook-kernel" in "".join(str(output) for output in outputs)


@pytest.mark.asyncio
async def test_execute_code_reports_an_unknown_kernel_id(targeting_setup):
    """An unknown kernel_id must be reported, never silently redirected to
    whichever kernel happens to be current."""
    notebook_manager, server_client, _ = targeting_setup

    outputs = await _execute(
        notebook_manager, server_client, "print(MARKER)", kernel_id="no-such-kernel"
    )

    joined = "".join(str(output) for output in outputs)
    assert "no-such-kernel" in joined and "not found" in joined
    assert "current-notebook-kernel" not in joined
