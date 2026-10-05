# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for connect_to_jupyter checking the server before switching to it.

Switching the configuration does not touch the server, so a typo'd URL, a dead
port or a wrong token used to come back as "Successfully connected". These
tests stub `requests.get`, so no running Jupyter server is required.
"""

import asyncio
from types import SimpleNamespace

import pytest
import requests

from jupyter_mcp_server.config import get_config, reset_config, set_config
from jupyter_mcp_server.tools import ServerMode, connect_jupyter_tool
from jupyter_mcp_server.tools.connect_jupyter_tool import ConnectJupyterTool

GOOD_URL = "http://localhost:8888"


def setup_function():
    reset_config()
    set_config(code_sandbox_url=GOOD_URL, document_url=GOOD_URL, code_sandbox_token="good")


def teardown_function():
    reset_config()


def _stub_get(monkeypatch, status_code=200, raises=None):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(SimpleNamespace(url=url, headers=headers or {}))
        if raises is not None:
            raise raises
        return SimpleNamespace(status_code=status_code)

    monkeypatch.setattr(connect_jupyter_tool.requests, "get", fake_get)
    return calls


async def _connect(**kwargs):
    return await ConnectJupyterTool().execute(mode=ServerMode.MCP_SERVER, **kwargs)


@pytest.mark.asyncio
async def test_a_reachable_server_is_checked_with_the_token_then_used(monkeypatch):
    calls = _stub_get(monkeypatch, status_code=200)
    result = await _connect(jupyter_url="http://localhost:8889/", jupyter_token="abc")
    assert "Successfully connected" in result
    assert calls[0].url == "http://localhost:8889/api/status"
    assert calls[0].headers == {"Authorization": "token abc"}
    assert get_config().code_sandbox_url == "http://localhost:8889/"


@pytest.mark.asyncio
async def test_an_unreachable_server_is_an_error_and_keeps_the_old_connection(monkeypatch):
    _stub_get(monkeypatch, raises=requests.exceptions.ConnectionError("refused"))
    with pytest.raises(Exception, match=r"could not reach.*previous connection is unchanged"):
        await _connect(jupyter_url="http://localhost:1")
    assert get_config().code_sandbox_url == GOOD_URL
    assert get_config().code_sandbox_token == "good"  # noqa: S105 (test fixture, not a real secret)


@pytest.mark.asyncio
async def test_a_url_without_a_scheme_is_an_error(monkeypatch):
    _stub_get(monkeypatch, raises=requests.exceptions.InvalidSchema("No connection adapters"))
    with pytest.raises(Exception, match="could not reach"):
        await _connect(jupyter_url="localhost:8888")
    assert get_config().code_sandbox_url == GOOD_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_a_rejected_token_is_an_error(monkeypatch, status_code):
    _stub_get(monkeypatch, status_code=status_code)
    with pytest.raises(Exception, match="rejected the token"):
        await _connect(jupyter_url=GOOD_URL, jupyter_token="wrong")
    assert get_config().code_sandbox_token == "good"  # noqa: S105 (test fixture, not a real secret)


@pytest.mark.asyncio
async def test_a_server_error_is_an_error(monkeypatch):
    _stub_get(monkeypatch, status_code=500)
    with pytest.raises(Exception, match="returned 500"):
        await _connect(jupyter_url=GOOD_URL)


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "", "None"])
async def test_no_token_sends_no_authorization_header(monkeypatch, token):
    calls = _stub_get(monkeypatch, status_code=200)
    await _connect(jupyter_url=GOOD_URL, jupyter_token=token)
    assert calls[0].headers == {}


@pytest.mark.asyncio
async def test_a_non_jupyter_document_provider_is_not_checked(monkeypatch):
    calls = _stub_get(monkeypatch, raises=AssertionError("should not be called"))
    await _connect(jupyter_url="https://prod1.datalayer.run", document_provider="datalayer")
    assert calls == []


@pytest.mark.asyncio
async def test_the_check_does_not_block_a_server_on_the_same_event_loop(monkeypatch):
    # Inside the Jupyter server extension the tool runs on the server's own
    # event loop, so connecting to that same server must not hold the loop
    # while it waits for `/api/status`, or the server can't answer and the
    # check times out.
    async def answer(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(connect_jupyter_tool, "_STATUS_TIMEOUT_SECONDS", 3.0)
    try:
        result = await _connect(jupyter_url=f"http://127.0.0.1:{port}", jupyter_token="abc")
    finally:
        server.close()
        await server.wait_closed()
    assert "Successfully connected" in result
