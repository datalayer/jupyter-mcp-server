# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for kernel clients inheriting the manager's ZMQ identity.

``KernelManager.client()`` clones the manager's ``Session``, and the clone keeps
the session id — which jupyter_client passes as the ZMQ socket identity. ipykernel
sets ``ROUTER_HANDOVER``, so a second client claiming an identity that is already
in use takes it over and the first client silently stops reaching the kernel.

The live test below fails without ``create_isolated_kernel_client``: the
long-lived client's second execute never reaches the kernel and times out.
"""

import asyncio
import inspect

import pytest

from jupyter_mcp_server.utils import create_isolated_kernel_client

pytest.importorskip("ipykernel", reason="the live test needs a real kernel to connect to")

from jupyter_client.manager import AsyncKernelManager  # noqa: E402

EXECUTE_TIMEOUT = 15.0


class _FakeSession:
    def __init__(self, session_id):
        self.session = session_id


class _FakeClient:
    def __init__(self, session=None):
        if session is not None:
            self.session = session


class _FakeKernel:
    """Mimics KernelManager.client(): a fresh client carrying a Session clone."""

    def __init__(self, session_id="shared-identity", with_session=True):
        self.session_id = session_id
        self.with_session = with_session

    def client(self):
        if not self.with_session:
            return _FakeClient()
        return _FakeClient(_FakeSession(self.session_id))


def test_client_does_not_inherit_the_kernel_session_id():
    kernel = _FakeKernel(session_id="shared-identity")

    first = create_isolated_kernel_client(kernel)
    second = create_isolated_kernel_client(kernel)

    assert first.session.session != "shared-identity"
    assert second.session.session != "shared-identity"
    assert first.session.session != second.session.session


def test_client_without_a_session_is_returned_unchanged():
    """Remote/websocket-backed clients expose no Session; they must still work."""
    client = create_isolated_kernel_client(_FakeKernel(with_session=False))

    assert client is not None
    assert not hasattr(client, "session")


async def _execute(client, code):
    """Return the execution status, or 'TIMEOUT' when the request never lands."""
    result = client.execute_interactive(code, output_hook=lambda msg: None, stdin_hook=None)
    if inspect.isawaitable(result):
        result = asyncio.ensure_future(result)
    try:
        reply = await asyncio.wait_for(result, timeout=EXECUTE_TIMEOUT)
    except asyncio.TimeoutError:
        return "TIMEOUT"
    return reply["content"]["status"]


@pytest.mark.asyncio
async def test_second_client_does_not_orphan_a_long_lived_one():
    """A short-lived client must not evict a long-lived client's ZMQ identity."""
    manager = AsyncKernelManager(kernel_name="python3")
    await manager.start_kernel()
    long_lived = None
    short_lived = None
    try:
        long_lived = manager.client()
        long_lived.start_channels()
        await long_lived.wait_for_ready(timeout=EXECUTE_TIMEOUT)
        assert await _execute(long_lived, "x = 1") == "ok"

        short_lived = create_isolated_kernel_client(manager)
        short_lived.start_channels()
        await short_lived.wait_for_ready(timeout=EXECUTE_TIMEOUT)
        assert await _execute(short_lived, "y = 2") == "ok"

        # Without the fix this times out: the kernel never receives the request.
        assert await _execute(long_lived, "z = 3") == "ok"
    finally:
        for client in (short_lived, long_lived):
            if client is not None and client.channels_running:
                client.stop_channels()
        await manager.shutdown_kernel(now=True)
