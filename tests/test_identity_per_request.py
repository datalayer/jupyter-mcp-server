# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The caller's credential, per request.

A server serving one person has one token in its configuration, and every
request uses it. A server serving many cannot: the configured token belongs to
somebody, and using it for everyone means one user's requests run with
another's authority.

These cover the mechanism that makes the credential travel with the request
instead — and, as much as unit tests can, that it does not leak between two
requests being served at once.
"""

from __future__ import annotations

import asyncio

import pytest

from jupyter_mcp_server.config import get_config, reset_config, set_config
from jupyter_mcp_server.identity import (
    Identity,
    IdentityMiddleware,
    current_identity,
    identity_from_access_token,
    reset_current_identity,
    set_current_identity,
)


class _AccessToken:
    """The shape the MCP SDK hands to a verifier's caller."""

    def __init__(self, token="tok", client_id="cli", scopes=(), subject="user"):
        self.token = token
        self.client_id = client_id
        self.scopes = list(scopes)
        self.subject = subject


class _AuthenticatedUser:
    def __init__(self, access_token):
        self.access_token = access_token


@pytest.fixture(autouse=True)
def _clean_config():
    reset_config()
    yield
    reset_config()


class TestIdentityCarriesTheCredential:
    def test_the_access_token_becomes_the_identity_token(self):
        identity = identity_from_access_token(_AccessToken(token="abc123"))
        assert identity.token == "abc123"

    def test_a_verifier_may_withhold_it(self):
        # An AccessToken with no usable token means "use what is configured",
        # which is how a deployment opts out of credential passthrough.
        identity = identity_from_access_token(_AccessToken(token=""))
        assert identity.token == ""

    def test_an_identity_without_a_token_is_still_valid(self):
        # JUPYTER_SERVER mode builds identities with no token at all.
        assert Identity(username="alice").token == ""


class TestConfigPrefersTheCaller:
    def test_the_configured_token_is_used_when_nobody_is_calling(self):
        set_config(document_url="https://example.test", document_token="configured")
        assert get_config().resolved_document_token() == "configured"

    def test_the_caller_credential_wins(self):
        set_config(document_url="https://example.test", document_token="configured")
        token = set_current_identity(Identity(username="alice", token="alice-token"))
        try:
            assert get_config().resolved_document_token() == "alice-token"
        finally:
            reset_current_identity(token)

    def test_the_configured_token_returns_once_the_caller_is_gone(self):
        # The regression that would matter most: a credential outliving the
        # request that brought it.
        set_config(document_url="https://example.test", document_token="configured")
        token = set_current_identity(Identity(username="alice", token="alice-token"))
        reset_current_identity(token)
        assert get_config().resolved_document_token() == "configured"

    def test_an_identity_without_a_credential_falls_back(self):
        set_config(document_url="https://example.test", document_token="configured")
        token = set_current_identity(Identity(username="alice"))
        try:
            assert get_config().resolved_document_token() == "configured"
        finally:
            reset_current_identity(token)

    def test_the_sandbox_token_follows_the_same_rule(self):
        set_config(code_sandbox_token="configured")
        token = set_current_identity(Identity(username="alice", token="alice-token"))
        try:
            assert get_config().resolved_code_sandbox_token() == "alice-token"
        finally:
            reset_current_identity(token)


class TestMiddleware:
    """Setting and — more importantly — unsetting the identity."""

    @staticmethod
    def _scope(access_token=None):
        scope = {"type": "http", "method": "POST", "headers": []}
        if access_token is not None:
            scope["user"] = _AuthenticatedUser(access_token)
        return scope

    @pytest.mark.asyncio
    async def test_the_tool_sees_the_caller(self):
        seen = {}

        async def app(scope, receive, send):
            identity = current_identity()
            seen["token"] = identity.token if identity else None

        await IdentityMiddleware(app)(
            self._scope(_AccessToken(token="alice-token")), None, None
        )
        assert seen["token"] == "alice-token"

    @pytest.mark.asyncio
    async def test_the_identity_does_not_outlive_the_request(self):
        async def app(scope, receive, send):
            return None

        await IdentityMiddleware(app)(self._scope(_AccessToken()), None, None)
        assert current_identity() is None

    @pytest.mark.asyncio
    async def test_it_is_reset_even_when_the_request_fails(self):
        async def app(scope, receive, send):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await IdentityMiddleware(app)(self._scope(_AccessToken()), None, None)
        # A failed request that left its identity behind would hand it to
        # whichever request the task served next.
        assert current_identity() is None

    @pytest.mark.asyncio
    async def test_an_unauthenticated_request_passes_through(self):
        called = {}

        async def app(scope, receive, send):
            called["identity"] = current_identity()

        await IdentityMiddleware(app)(self._scope(), None, None)
        assert called["identity"] is None

    @pytest.mark.asyncio
    async def test_a_non_http_scope_is_left_alone(self):
        called = {}

        async def app(scope, receive, send):
            called["ran"] = True

        await IdentityMiddleware(app)({"type": "lifespan"}, None, None)
        assert called["ran"]

    @pytest.mark.asyncio
    async def test_two_concurrent_requests_keep_their_own_credential(self):
        """The property the whole design rests on.

        Two callers served at once must never see each other's credential.
        Each request runs in its own task, and a contextvar set in one task is
        invisible to the other — this asserts that rather than trusting it.
        """
        observed = {}

        async def app(scope, receive, send):
            name = dict(scope["headers"])[b"x-name"].decode()
            # Yield, so the two requests are genuinely interleaved rather than
            # running one after the other.
            await asyncio.sleep(0)
            identity = current_identity()
            observed[name] = identity.token if identity else None

        middleware = IdentityMiddleware(app)

        async def request(name, token):
            scope = self._scope(_AccessToken(token=token))
            scope["headers"] = [(b"x-name", name.encode())]
            await middleware(scope, None, None)

        await asyncio.gather(
            request("alice", "alice-token"), request("bob", "bob-token")
        )
        assert observed == {"alice": "alice-token", "bob": "bob-token"}
