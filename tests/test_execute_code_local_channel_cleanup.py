# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression test for execute_code_local leaking the kernel client's channels.

stop_channels() is reached on the timeout and success paths only, so an
exception raised after the channels are open falls through to the generic
handler with the sockets still bound. A BEFORE_EXECUTE hook with
propagate_errors=True is the shortest supported way to raise there.
"""

import pytest

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.utils import execute_code_local


class FailingBeforeExecuteHandler:
    """Raises out of BEFORE_EXECUTE, which fires just after start_channels()."""

    propagate_errors = True

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        if event == HookEvent.BEFORE_EXECUTE:
            raise RuntimeError("handler failed")


class FakeKernelClient:
    def __init__(self):
        self.channels_running = False
        self.start_calls = 0
        self.stop_calls = 0

    def start_channels(self):
        self.start_calls += 1
        self.channels_running = True

    def stop_channels(self):
        self.stop_calls += 1
        self.channels_running = False


class FakeKernel:
    def __init__(self, client):
        self.session = object()
        self._client = client

    def client(self):
        return self._client


class FakeKernelManager:
    """Stands in for the pinned_superclass.get_kernel(manager, kernel_id) lookup."""

    def __init__(self, kernel):
        self._kernel = kernel

    @property
    def pinned_superclass(self):
        return self

    def get_kernel(self, kernel_manager, kernel_id):
        return self._kernel


class FakeServerApp:
    def __init__(self, kernel_manager):
        self.kernel_manager = kernel_manager


@pytest.fixture(autouse=True)
def reset_registry():
    HookRegistry.reset()
    yield
    HookRegistry.reset()


@pytest.mark.asyncio
async def test_channels_stopped_when_execution_raises():
    client = FakeKernelClient()
    serverapp = FakeServerApp(FakeKernelManager(FakeKernel(client)))
    HookRegistry.get_instance().register(FailingBeforeExecuteHandler())

    result = await execute_code_local(serverapp, "notebook.ipynb", "1 + 1", "kernel-1")

    assert result == ["[ERROR: handler failed]"]
    assert client.start_calls == 1
    assert client.stop_calls == 1
    assert client.channels_running is False


@pytest.mark.asyncio
async def test_no_cleanup_attempted_when_the_kernel_lookup_fails():
    class ExplodingKernelManager:
        @property
        def pinned_superclass(self):
            return self

        def get_kernel(self, kernel_manager, kernel_id):
            raise KeyError(kernel_id)

    result = await execute_code_local(
        FakeServerApp(ExplodingKernelManager()), "notebook.ipynb", "1 + 1", "missing"
    )

    assert result == ["[ERROR: 'missing']"]
