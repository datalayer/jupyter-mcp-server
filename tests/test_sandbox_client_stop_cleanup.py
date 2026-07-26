# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for sandbox-backed kernel client cleanup behavior."""

from unittest.mock import MagicMock, patch

from jupyter_mcp_server.sandbox_client import create_jupyter_sandbox_client


class _FakeKernelClient:
    def __init__(self) -> None:
        self.stop_calls: list[tuple[tuple, dict]] = []

    def stop(self, *args, **kwargs):
        self.stop_calls.append((args, kwargs))
        return "client-stop"


def test_create_jupyter_sandbox_client_stop_releases_backing_sandbox():
    """Normal client.stop() must release the backing sandbox runtime."""
    fake_client = _FakeKernelClient()
    fake_sandbox = MagicMock()
    fake_sandbox.kernel_client = fake_client

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox):
        client = create_jupyter_sandbox_client(
            server_url="http://localhost:8888",
            token="MY_TOKEN",
        )

    client.stop()

    fake_sandbox.start.assert_called_once_with()
    fake_sandbox.stop.assert_called_once_with()
    assert fake_client.stop_calls == []


def test_create_jupyter_sandbox_client_stop_shutdown_false_keeps_kernel_only():
    """Borrowed-kernel cleanup must not stop the backing sandbox runtime."""
    fake_client = _FakeKernelClient()
    fake_sandbox = MagicMock()
    fake_sandbox.kernel_client = fake_client

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox):
        client = create_jupyter_sandbox_client(
            server_url="http://localhost:8888",
            token="MY_TOKEN",
        )

    client.stop(shutdown_kernel=False)

    fake_sandbox.start.assert_called_once_with()
    fake_sandbox.stop.assert_not_called()
    assert len(fake_client.stop_calls) == 1
    assert fake_client.stop_calls[0][1]["shutdown_kernel"] is False
