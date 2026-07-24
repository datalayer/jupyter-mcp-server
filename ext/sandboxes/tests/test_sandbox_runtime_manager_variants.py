# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Variant coverage tests for SandboxRuntimeManager launch routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jupyter_mcp_sandboxes.manager import SandboxRuntimeManager


@pytest.fixture
def fake_sandbox() -> MagicMock:
    sandbox = MagicMock()
    sandbox.sandbox_id = "sandbox-id"
    sandbox.info = SimpleNamespace(variant="unknown", status="running")
    sandbox.config = SimpleNamespace(environment="env", gpu="gpu")
    return sandbox


@pytest.mark.parametrize("variant", ["eval", "docker", "monty"])
def test_launch_forwards_generic_variant_kwargs(variant: str, fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create:
        manager.launch(
            sandbox_name="s1",
            variant=variant,
            timeout=60,
            environment="env-name",
            gpu="T4",
            python_version="3.12",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["variant"] == variant
    assert kwargs["timeout"] == 60
    assert kwargs["environment"] == "env-name"
    assert kwargs["gpu"] == "T4"
    assert "python_version" not in kwargs


def test_launch_modal_forwards_python_version(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create:
        manager.launch(
            sandbox_name="modal-1",
            variant="modal",
            timeout=30,
            environment="agent-env",
            gpu="A100",
            python_version="3.12",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["variant"] == "modal"
    assert kwargs["gpu"] == "A100"
    assert kwargs["python_version"] == "3.12"


def test_launch_colab_forwards_runtime_fields(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create:
        manager.launch(
            sandbox_name="colab-1",
            variant="colab",
            timeout=45,
            server_url="https://colab.example",
            kernel_id="kernel-1",
            proxy_token="proxy-token",
            channels_url="wss://colab.example/channels",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["variant"] == "colab"
    assert kwargs["server_url"] == "https://colab.example"
    assert kwargs["kernel_id"] == "kernel-1"
    assert kwargs["proxy_token"] == "proxy-token"
    assert kwargs["channels_url"] == "wss://colab.example/channels"


def test_launch_kaggle_forwards_runtime_fields(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create:
        manager.launch(
            sandbox_name="kaggle-1",
            variant="kaggle",
            timeout=45,
            server_url="https://kaggle.example/proxy",
            kernel_id="kernel-2",
            channels_url="wss://kaggle.example/channels",
            token="kaggle-token",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["variant"] == "kaggle"
    assert kwargs["server_url"] == "https://kaggle.example/proxy"
    assert kwargs["kernel_id"] == "kernel-2"
    assert kwargs["channels_url"] == "wss://kaggle.example/channels"
    assert kwargs["token"] == "kaggle-token"


def test_launch_datalayer_forwards_token_and_run_url(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create:
        manager.launch(
            sandbox_name="d1",
            variant="datalayer",
            timeout=20,
            token="api-token",
            run_url="https://run.example",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["variant"] == "datalayer"
    assert kwargs["token"] == "api-token"
    assert kwargs["run_url"] == "https://run.example"


def test_launch_sets_active_and_prevents_duplicates(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()

    with patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox):
        first = manager.launch(sandbox_name="dup", variant="eval", timeout=10)

    assert manager.get_active_name() == "dup"
    assert first["name"] == "dup"

    with pytest.raises(ValueError, match="already exists"):
        manager.launch(sandbox_name="dup", variant="eval", timeout=10)


def test_use_terminate_and_terminate_all(fake_sandbox: MagicMock):
    manager = SandboxRuntimeManager()
    fake_sandbox_2 = MagicMock()
    fake_sandbox_2.sandbox_id = "sandbox-2"
    fake_sandbox_2.info = SimpleNamespace(variant="docker", status="running")
    fake_sandbox_2.config = SimpleNamespace(environment=None, gpu=None)

    with patch("code_sandboxes.Sandbox.create", side_effect=[fake_sandbox, fake_sandbox_2]):
        manager.launch(sandbox_name="a", variant="eval", timeout=10)
        manager.launch(sandbox_name="b", variant="docker", timeout=10)

    assert manager.get_active_name() == "a"
    assert manager.use("b") == "b"
    assert manager.get_active_name() == "b"
    assert manager.use(None) is None

    assert manager.terminate("missing") is False
    assert manager.terminate("a") is True
    fake_sandbox.stop.assert_called_once()

    manager.terminate_all()
    fake_sandbox_2.stop.assert_called_once()
    assert manager.list() == []
