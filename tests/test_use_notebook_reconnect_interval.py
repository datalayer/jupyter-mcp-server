# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`reconnect_interval` reaches the sandbox that runs the code.

Opening a notebook no longer creates a kernel — reading cells needs none, and
building one there always built a *Jupyter* sandbox whatever the configured
variant said. The kernel is created on the first execution instead, by the
shared factory, and that is where this setting has to arrive.
"""

import logging
from unittest.mock import patch

import pytest

from jupyter_mcp_server.config import reset_config, set_config


class _FakeContents:
    @staticmethod
    def create_notebook(path, content=None):
        return None

    @staticmethod
    def list_directory(path):
        return []


class _FakeKernels:
    @staticmethod
    def list_kernels():
        return []


class FakeServerClient:
    """Stand-in for JupyterServerClient: no live server needed, only the
    surface use_notebook touches before it reaches kernel creation."""

    contents = _FakeContents
    kernels = _FakeKernels

    def get_status(self):
        return {}


class FakeKernel:
    id = "kernel-1"


@pytest.fixture
def configured_reconnect():
    reset_config()
    set_config(reconnect_interval=5, execution_timeout=300)
    yield
    reset_config()


def _created_with(**config_kwargs):
    """The kwargs the shared factory hands the sandbox client."""
    from jupyter_mcp_server import utils

    reset_config()
    config = set_config(**config_kwargs)
    seen = {}

    class _Kernel:
        id = "k1"

    def fake_client(**kwargs):
        seen.update(kwargs)
        return _Kernel()

    with patch(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", fake_client
    ):
        with patch(
            "jupyter_mcp_server.extensions.get_extension_manager"
        ) as manager:
            manager.return_value.create_code_sandbox.return_value = None
            utils.create_code_sandbox(config, logging.getLogger("test"))
    reset_config()
    return seen


def test_the_configured_reconnect_interval_reaches_the_sandbox():
    seen = _created_with(code_sandbox_url="http://localhost:8888", reconnect_interval=7)
    assert seen["reconnect_interval"] == 7


def test_it_defaults_to_zero():
    # Zero disables auto-reconnect, which is the documented default.
    seen = _created_with(code_sandbox_url="http://localhost:8888")
    assert seen["reconnect_interval"] == 0


def test_an_extension_takes_over_for_another_variant():
    """A non-jupyter variant must not reach the Jupyter client at all.

    This is the regression that stalled `use_notebook` for two minutes: a
    Jupyter sandbox was built whatever the variant said, then waited for an
    `/api/status` that a Datalayer endpoint never answers.
    """
    from jupyter_mcp_server import utils

    reset_config()
    config = set_config(sandbox_variant="datalayer", code_sandbox_url="https://prod1.datalayer.run")

    class _Sandbox:
        id = "sandbox-1"

    def must_not_run(**kwargs):  # pragma: no cover - the point of the test
        raise AssertionError("the Jupyter client must not be built for a datalayer variant")

    with patch(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", must_not_run
    ):
        with patch("jupyter_mcp_server.extensions.get_extension_manager") as manager:
            manager.return_value.create_code_sandbox.return_value = _Sandbox()
            kernel = utils.create_code_sandbox(config, logging.getLogger("test"))
    reset_config()
    assert kernel.id == "sandbox-1"
