# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for managed Code Sandbox client creation."""

from unittest.mock import MagicMock, patch

from jupyter_mcp_server.sandbox_client import create_jupyter_sandbox_client


def test_create_jupyter_sandbox_client_starts_managed_client():
    fake_client = MagicMock()

    with patch(
        "code_sandboxes.CodeSandboxClient.create", return_value=fake_client
    ) as create:
        client = create_jupyter_sandbox_client(
            server_url="http://localhost:8888",
            token="MY_TOKEN",
        )

    assert client is fake_client
    create.assert_called_once_with(
        variant="jupyter",
        server_url="http://localhost:8888",
        token="MY_TOKEN",
        kernel_id=None,
        kernel_path=None,
        reuse_kernel=False,
    )
    fake_client.start.assert_called_once_with()


def test_create_jupyter_sandbox_client_preserves_borrowed_stop_contract():
    fake_client = MagicMock()

    with patch("code_sandboxes.CodeSandboxClient.create", return_value=fake_client):
        client = create_jupyter_sandbox_client(
            server_url="http://localhost:8888",
            token="MY_TOKEN",
            kernel_id="existing-kernel",
        )

    client.stop(shutdown_kernel=False)
    fake_client.stop.assert_called_once_with(shutdown_kernel=False)
