# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""``use_notebook(kernel_id=...)`` in MCP_SERVER mode binds that kernel (#425).

Since #372 the id was only checked for existence and then dropped: execution
went to a kernel built from the configuration. A caller attaching the MCP to
the kernel a human already has open never shared its variables.
"""

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
EXISTING_KERNEL_ID = "afd51e4a-existing"


class FakeServerClient:
    contents = SimpleNamespace(
        list_directory=lambda path: [SimpleNamespace(name="nb.ipynb")],
        get=lambda path: {"content": {"cells": []}},
    )
    kernels = SimpleNamespace(list_kernels=lambda: [SimpleNamespace(id=EXISTING_KERNEL_ID)])

    def get_status(self):
        return {}


@pytest.fixture
def recorded_sandbox_kwargs(monkeypatch):
    seen = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(id=kwargs["kernel_id"], is_alive=lambda: True)

    monkeypatch.setattr(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", fake_client
    )
    # add_notebook starts a watcher that would make a real HTTP request.
    monkeypatch.setattr("jupyter_mcp_server.watchers.watchers.watch", lambda name, manager: False)
    monkeypatch.setattr(
        "jupyter_mcp_server.extensions.get_extension_manager",
        lambda: SimpleNamespace(create_code_sandbox=lambda config, logger: None),
    )
    monkeypatch.setattr(
        "jupyter_mcp_server.server_context.ServerContext.get_instance",
        staticmethod(
            lambda: SimpleNamespace(
                document_server_client=FakeServerClient(),
                document_auth_headers={},
                code_sandbox_auth_headers={},
            )
        ),
    )
    reset_config()
    yield seen
    reset_config()


async def _use_notebook(notebook_manager, kernel_id):
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=FakeServerClient(),
        notebook_manager=notebook_manager,
        notebook_name="demo",
        notebook_path="nb.ipynb",
        use_mode="connect",
        code_sandbox_url=SANDBOX_URL,
        kernel_id=kernel_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("start_new_code_sandbox", [True, False])
async def test_use_notebook__binds_the_requested_kernel(
    recorded_sandbox_kwargs, start_new_code_sandbox
):
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=start_new_code_sandbox)
    notebook_manager = NotebookManager()

    reply = await _use_notebook(notebook_manager, EXISTING_KERNEL_ID)

    assert recorded_sandbox_kwargs["kernel_id"] == EXISTING_KERNEL_ID
    assert notebook_manager.get_code_sandbox_id("demo") == EXISTING_KERNEL_ID
    assert f"Connected to kernel '{EXISTING_KERNEL_ID}'" in reply


@pytest.mark.asyncio
async def test_use_notebook__without_kernel_id_stays_lazy(recorded_sandbox_kwargs):
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    notebook_manager = NotebookManager()

    await _use_notebook(notebook_manager, None)

    assert recorded_sandbox_kwargs == {}
    assert notebook_manager.get_code_sandbox("demo") is None


@pytest.mark.asyncio
async def test_use_notebook__rejects_an_unknown_kernel_id(recorded_sandbox_kwargs):
    set_config(code_sandbox_url=SANDBOX_URL)

    reply = await _use_notebook(NotebookManager(), "no-such-kernel")

    assert "not found" in reply
    assert recorded_sandbox_kwargs == {}


@pytest.mark.asyncio
async def test_use_notebook__hands_the_id_to_the_extension_for_another_variant(
    monkeypatch, recorded_sandbox_kwargs
):
    """The extension reads `code_sandbox_id`; a per-call id must arrive there."""
    set_config(code_sandbox_url=SANDBOX_URL, sandbox_variant="datalayer")
    seen_config = {}

    def extension_sandbox(config, logger):
        seen_config["code_sandbox_id"] = config.code_sandbox_id
        return SimpleNamespace(id=config.code_sandbox_id, is_alive=lambda: True)

    monkeypatch.setattr(
        "jupyter_mcp_server.extensions.get_extension_manager",
        lambda: SimpleNamespace(create_code_sandbox=extension_sandbox),
    )
    notebook_manager = NotebookManager()

    await _use_notebook(notebook_manager, EXISTING_KERNEL_ID)

    assert seen_config["code_sandbox_id"] == EXISTING_KERNEL_ID
    assert notebook_manager.get_code_sandbox_id("demo") == EXISTING_KERNEL_ID
    assert recorded_sandbox_kwargs == {}, "the Jupyter client must not be built"
