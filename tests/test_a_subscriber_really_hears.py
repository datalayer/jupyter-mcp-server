#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""A client that subscribes really is told, over a real connection.

Every other test of this publishes to a fake session on a fake bus and
asserts the fake was called. That is worth having — it pins which calls
announce and which do not — and it cannot see the thing that actually broke:
whether a *client* on the other end of a real Streamable HTTP connection ever
receives the notification.

It did not, until 2026-09-05. The registry of subscribed sessions was
weak-keyed, and nothing else holds a `ServerSession`, so every subscription
was collected between the request that made it and the next call. The server
advertised `resources.subscribe: true`, accepted the subscribe, reported that
it had published, and told nobody — the report came from the 2026-07-28 bus,
which publishes to its own subscribers and knows nothing of the 2025-11-25
client waiting on its stream.

Three things this test does that the others could not, each of which had to
be true to see the defect at all:

- it holds **no reference of its own** to the session. A test that keeps one
  passes against the broken code, which is how this stayed broken while its
  unit tests were green;
- it runs over **real TCP**. An in-process ASGI transport never establishes
  the client's standalone `GET` stream, and that stream is the channel a
  server-initiated notification travels on — so the whole thing would pass or
  fail for the wrong reason;
- it reads the wire, so the verdict does not depend on a client library
  routing the message to the right callback.

No Jupyter: what is under test is the delivery mechanism, and a notebook
would only add ways to fail that are not this one.

Launch the tests:
```
$ pytest tests/test_a_subscriber_really_hears.py -v
```
"""

import asyncio
import json
import socket
import threading

import httpx
import pytest
import uvicorn
from mcp.server import MCPServer
from mcp.types import EmptyResult, SubscribeRequestParams, UnsubscribeRequestParams

from jupyter_mcp_server import notifications

#: The notebook every test here subscribes to.
NOTEBOOK = "watched"

#: How long a notification gets to arrive before it is called absent. The
#: whole trip is one process talking to itself over the loopback, so this is
#: generous by two orders of magnitude; a real one is milliseconds.
ARRIVES_WITHIN = 5.0

#: The wire, as a 2025-11-25 client speaks it.
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
PROTOCOL = "2025-11-25"


def _a_free_port() -> int:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return int(held.getsockname()[1])


def _server(publishes: str = NOTEBOOK, cells: tuple = ()) -> MCPServer:
    """A server with the subscription handlers, registered as the real one does.

    Built the way `server.py` builds them — the same two `add_request_handler`
    calls with the same params models — so a change to how the real server
    registers them shows up here as a failure rather than as a test that
    quietly stops covering anything.
    """
    server = MCPServer("subscriber-test")

    async def on_subscribe(ctx, params) -> EmptyResult:
        notifications.legacy_subscribe(getattr(ctx, "session", None), str(params.uri))
        return EmptyResult()

    async def on_unsubscribe(ctx, params) -> EmptyResult:
        notifications.legacy_unsubscribe(getattr(ctx, "session", None), str(params.uri))
        return EmptyResult()

    server._lowlevel_server.add_request_handler(
        "resources/subscribe", SubscribeRequestParams, on_subscribe
    )
    server._lowlevel_server.add_request_handler(
        "resources/unsubscribe", UnsubscribeRequestParams, on_unsubscribe
    )

    @server.tool()
    async def touch_the_notebook() -> str:
        """Publish, exactly as a writing tool's decorator does on its way out."""
        told = await notifications.publish_notebook_updated(server, publishes, cells)
        return f"told={told}"

    return server


class _Running:
    """A server on the loopback, and the wire to it."""

    def __init__(self, server: MCPServer) -> None:
        self.port = _a_free_port()
        # Stateful, as a worker is: a stateless server hands out no session,
        # and what is under test is what happens to one that exists.
        app = server.streamable_http_app(stateless_http=False)
        self._uvicorn = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self._thread = threading.Thread(target=self._uvicorn.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    async def __aenter__(self) -> "_Running":
        self._thread.start()
        for _ in range(100):
            if self._uvicorn.started:
                return self
            await asyncio.sleep(0.05)
        raise AssertionError("the server never started")

    async def __aexit__(self, *_exception) -> None:
        self._uvicorn.should_exit = True
        self._thread.join(timeout=5)


def _rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _frames(response: httpx.Response) -> list[dict]:
    """The JSON of every SSE `data:` line in a response."""
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def _connected(client: httpx.AsyncClient, url: str) -> dict[str, str]:
    """Initialize, and answer the headers every later request carries."""
    answer = await client.post(
        url,
        json=_rpc(
            1,
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "subscriber-test", "version": "0"},
            },
        ),
        headers=HEADERS,
    )
    assert answer.status_code == 200, answer.text
    session_id = answer.headers.get("mcp-session-id")
    assert session_id, "a stateful server hands back a session id"
    headers = {
        **HEADERS,
        "Mcp-Session-Id": session_id,
        "MCP-Protocol-Version": PROTOCOL,
    }
    await client.post(
        url,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    return headers


@pytest.mark.asyncio
async def test_a_subscriber_is_told_over_a_real_connection():
    """The claim `resources.subscribe: true` makes to a 2025-11-25 client.

    A server that advertises the capability, accepts the subscription and
    then tells nobody is worse than one that advertises nothing: the client
    stops polling because it was promised it would be told.
    """
    notifications.use_publisher(None)
    heard: list[dict] = []

    async with _Running(_server()) as running:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await _connected(client, running.url)

            async def listen() -> None:
                async with client.stream("GET", running.url, headers=headers) as stream:
                    assert stream.status_code == 200, "no standalone stream to be told on"
                    async for line in stream.aiter_lines():
                        if line.startswith("data: "):
                            heard.append(json.loads(line[len("data: ") :]))

            listening = asyncio.create_task(listen())
            await asyncio.sleep(0.5)

            subscribed = await client.post(
                running.url,
                json=_rpc(2, "resources/subscribe", {"uri": f"notebook://{NOTEBOOK}"}),
                headers=headers,
            )
            assert subscribed.status_code == 200, subscribed.text

            called = await client.post(
                running.url,
                json=_rpc(
                    3, "tools/call", {"name": "touch_the_notebook", "arguments": {}}
                ),
                headers=headers,
            )
            said = _frames(called)[0]["result"]["structuredContent"]["result"]
            assert said == "told=True", f"the server did not think it told anybody: {said}"

            deadline = asyncio.get_running_loop().time() + ARRIVES_WITHIN
            while asyncio.get_running_loop().time() < deadline and not heard:
                await asyncio.sleep(0.05)
            listening.cancel()

    assert heard, (
        "the subscriber was never told: the server accepted the subscription, "
        "reported that it published, and nothing was ever written to the stream "
        "it was listening on"
    )
    assert heard[0]["method"] == "notifications/resources/updated"
    assert heard[0]["params"]["uri"] == f"notebook://{NOTEBOOK}"


@pytest.mark.asyncio
async def test_a_subscriber_hears_nothing_about_another_notebook():
    """A notification for a notebook nobody subscribed to is not delivered.

    The other half of the promise: a client told about everything learns to
    ignore the channel, which costs it the notification it did want.
    """
    notifications.use_publisher(None)
    heard: list[dict] = []

    async with _Running(_server(publishes="somebody-elses")) as running:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await _connected(client, running.url)

            async def listen() -> None:
                async with client.stream("GET", running.url, headers=headers) as stream:
                    async for line in stream.aiter_lines():
                        if line.startswith("data: "):
                            heard.append(json.loads(line[len("data: ") :]))

            listening = asyncio.create_task(listen())
            await asyncio.sleep(0.5)
            await client.post(
                running.url,
                json=_rpc(2, "resources/subscribe", {"uri": f"notebook://{NOTEBOOK}"}),
                headers=headers,
            )
            await client.post(
                running.url,
                json=_rpc(
                    3, "tools/call", {"name": "touch_the_notebook", "arguments": {}}
                ),
                headers=headers,
            )
            await asyncio.sleep(1.0)
            listening.cancel()

    assert [message["params"]["uri"] for message in heard] == []


@pytest.mark.asyncio
async def test_a_subscriber_to_one_cell_really_hears_about_that_cell():
    """The cell half, over the same real connection.

    Naming the cell is only worth anything if the frame naming it reaches a
    client. This subscribes to a cell *and* to the notebook on one session,
    publishes one edit that names the cell, and reads both frames off the
    wire in the order they were written.

    Two subscriptions rather than one because the interesting claim is that
    the cell frame is an **addition**: a client watching the notebook must
    still hear the notebook, or a deleted cell — whose id nobody can read
    afterwards — would go unannounced.
    """
    notifications.use_publisher(None)
    heard: list[dict] = []
    cell = "cell-that-moved"

    async with _Running(_server(cells=(cell,))) as running:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await _connected(client, running.url)

            async def listen() -> None:
                async with client.stream("GET", running.url, headers=headers) as stream:
                    assert stream.status_code == 200, "no standalone stream to be told on"
                    async for line in stream.aiter_lines():
                        if line.startswith("data: "):
                            heard.append(json.loads(line[len("data: ") :]))

            listening = asyncio.create_task(listen())
            await asyncio.sleep(0.5)

            for request_id, uri in (
                (2, f"notebook://{NOTEBOOK}"),
                (3, f"notebook://{NOTEBOOK}/cells/{cell}"),
            ):
                subscribed = await client.post(
                    running.url,
                    json=_rpc(request_id, "resources/subscribe", {"uri": uri}),
                    headers=headers,
                )
                assert subscribed.status_code == 200, subscribed.text

            called = await client.post(
                running.url,
                json=_rpc(4, "tools/call", {"name": "touch_the_notebook", "arguments": {}}),
                headers=headers,
            )
            said = _frames(called)[0]["result"]["structuredContent"]["result"]
            assert said == "told=True", f"the server did not think it told anybody: {said}"

            deadline = asyncio.get_running_loop().time() + ARRIVES_WITHIN
            while asyncio.get_running_loop().time() < deadline and len(heard) < 2:
                await asyncio.sleep(0.05)
            listening.cancel()

    assert [message["params"]["uri"] for message in heard] == [
        f"notebook://{NOTEBOOK}",
        f"notebook://{NOTEBOOK}/cells/{cell}",
    ], "the cell frame did not reach the client, or it arrived instead of the notebook's"
    assert {message["method"] for message in heard} == {"notifications/resources/updated"}


@pytest.mark.asyncio
async def test_a_subscriber_to_one_cell_hears_nothing_about_another_cell():
    """The other half of the promise, at cell granularity.

    Without this, subscribing to a cell would be subscribing to the notebook
    with extra steps — and an agent watching one cell of a hundred would be
    woken by all hundred.
    """
    notifications.use_publisher(None)
    heard: list[dict] = []

    async with _Running(_server(cells=("a-different-cell",))) as running:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await _connected(client, running.url)

            async def listen() -> None:
                async with client.stream("GET", running.url, headers=headers) as stream:
                    async for line in stream.aiter_lines():
                        if line.startswith("data: "):
                            heard.append(json.loads(line[len("data: ") :]))

            listening = asyncio.create_task(listen())
            await asyncio.sleep(0.5)
            await client.post(
                running.url,
                json=_rpc(
                    2,
                    "resources/subscribe",
                    {"uri": f"notebook://{NOTEBOOK}/cells/the-one-i-care-about"},
                ),
                headers=headers,
            )
            await client.post(
                running.url,
                json=_rpc(3, "tools/call", {"name": "touch_the_notebook", "arguments": {}}),
                headers=headers,
            )
            await asyncio.sleep(1.0)
            listening.cancel()

    assert [message["params"]["uri"] for message in heard] == []
