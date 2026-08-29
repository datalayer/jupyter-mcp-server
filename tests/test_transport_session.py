# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Whether the Streamable HTTP transport issues a session id.

Stateless is right for a server many people reach: each request runs in its
own context, so `IdentityMiddleware` sees the caller of *that* request rather
than whoever opened the session.

It is the wrong default for a worker the Datalayer gateway starts, where
there is one process per user — every request on it is the same caller by
construction, so the reason does not apply, and the cost is real: a stateless
server issues no `Mcp-Session-Id`, and a client that expects one from a
Streamable HTTP server gets nothing.

Launch the tests:
```
$ pytest tests/test_transport_session.py -v
```
"""

from __future__ import annotations

import pytest

from jupyter_mcp_server.utils import _env_flag


class TestTheFlag:
    def test_not_set_is_neither_on_nor_off(self, monkeypatch):
        """"Not set" means *use the default for this way of running*.

        Collapsing it into `False` would make an unset variable
        indistinguishable from one somebody set to `false` on purpose, and
        the two want different things: one takes the default, the other
        overrides it.
        """
        monkeypatch.delenv("JUPYTER_MCP_STATEFUL", raising=False)
        assert _env_flag("JUPYTER_MCP_STATEFUL") is None

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_the_spellings_that_mean_yes(self, monkeypatch, value):
        monkeypatch.setenv("JUPYTER_MCP_STATEFUL", value)
        assert _env_flag("JUPYTER_MCP_STATEFUL") is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "nonsense"])
    def test_everything_else_means_no(self, monkeypatch, value):
        monkeypatch.setenv("JUPYTER_MCP_STATEFUL", value)
        assert _env_flag("JUPYTER_MCP_STATEFUL") is False


class TestWhatTheTransportDoes:
    def test_the_default_is_stateless(self, monkeypatch):
        """Unchanged for anybody running this server directly."""
        monkeypatch.delenv("JUPYTER_MCP_STATEFUL", raising=False)
        assert (_env_flag("JUPYTER_MCP_STATEFUL") is not True) is True

    def test_only_an_explicit_yes_turns_sessions_on(self, monkeypatch):
        """`is not True` rather than `not ...`, so an unset flag and an
        explicit `false` both stay stateless — and only somebody who meant it
        gets sessions."""
        for value, stateless in (("true", False), ("false", True), (None, True)):
            if value is None:
                monkeypatch.delenv("JUPYTER_MCP_STATEFUL", raising=False)
            else:
                monkeypatch.setenv("JUPYTER_MCP_STATEFUL", value)
            assert (_env_flag("JUPYTER_MCP_STATEFUL") is not True) is stateless

    def test_the_app_is_built_with_the_choice(self, monkeypatch):
        """The signature this passes through has to keep accepting it: a
        rename upstream would otherwise leave the flag silently inert, which
        is the failure it exists to fix."""
        import inspect

        from jupyter_mcp_server.server import MCPServerWithCORS

        parameters = inspect.signature(MCPServerWithCORS.streamable_http_app).parameters
        assert "stateless_http" in parameters
        assert parameters["stateless_http"].default is True
