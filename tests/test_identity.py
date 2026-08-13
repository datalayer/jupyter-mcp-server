# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unit tests for the configurable identity layer
(jupyter_mcp_server.identity): no server needed.

Launch the tests:
```
$ pytest tests/test_identity.py -v
```
"""

import contextvars
from types import SimpleNamespace

import pytest

from jupyter_mcp_server.identity import (
    TOKEN_VERIFIER_CLASS_ENV,
    Identity,
    TokenVerifier,
    current_identity,
    identity_from_access_token,
    identity_from_jupyter_user,
    load_token_verifier_class,
    reset_current_identity,
    resolve_token_verifier,
    set_current_identity,
)


class AcceptingVerifier:
    """A verifier a deployment could plug in, accepting anything."""

    async def verify_token(self, token: str):
        return SimpleNamespace(token=token, client_id="test-client", scopes=["a:b"])


class NotAVerifier:
    """Deliberately missing `verify_token`."""


class TestIdentityScopes:
    """`has_scope` distinguishes a delegated credential from a direct one."""

    def test_unscoped_identity_allows_everything(self):
        """A Jupyter token or a personal access token delegates nothing, so it
        carries the user's whole authority rather than none of it."""
        identity = Identity(username="alice")

        assert identity.has_scope("notebooks:read")
        assert identity.has_scope("code:execute")
        assert identity.has_scope("anything:at:all")

    def test_scoped_identity_allows_only_what_was_granted(self):
        identity = Identity(
            username="alice",
            client_id="claude-code",
            scopes=("notebooks:read", "code:execute"),
        )

        assert identity.has_scope("notebooks:read")
        assert identity.has_scope("code:execute")
        assert not identity.has_scope("notebooks:write")

    def test_describe_names_the_client_when_there_is_one(self):
        assert Identity(username="alice").describe() == "alice via direct"
        assert Identity(username="alice", client_id="codex").describe() == "alice via codex"


class TestIdentityFromAccessToken:
    """MCP_SERVER mode: what the SDK produces becomes an `Identity`."""

    def test_reads_subject_client_and_scopes(self):
        access_token = SimpleNamespace(
            subject="alice", client_id="claude-code", scopes=["notebooks:read"]
        )

        identity = identity_from_access_token(access_token)

        assert identity.username == "alice"
        assert identity.client_id == "claude-code"
        assert identity.scopes == ("notebooks:read",)

    def test_falls_back_to_client_id_when_there_is_no_subject(self):
        """A shared-secret token names no user; the client is the best label."""
        access_token = SimpleNamespace(client_id="mcp-client", scopes=[])

        identity = identity_from_access_token(access_token)

        assert identity.username == "mcp-client"
        assert identity.scopes == ()


class TestIdentityFromJupyterUser:
    """JUPYTER_SERVER mode: what Jupyter resolved becomes the same `Identity`."""

    def test_reads_a_jupyter_user_object(self):
        identity = identity_from_jupyter_user(SimpleNamespace(username="alice"))

        assert identity.username == "alice"
        # Jupyter has no notion of scopes, so the identity is unscoped and
        # therefore allowed everything the user is allowed.
        assert identity.scopes == ()
        assert identity.has_scope("code:execute")

    def test_reads_a_dict_user(self):
        identity = identity_from_jupyter_user({"username": "bob"})

        assert identity.username == "bob"

    def test_anonymous_when_there_is_no_user(self):
        assert identity_from_jupyter_user(None).username == "anonymous"

    def test_an_identity_provider_may_supply_scopes(self):
        """A platform identity provider can narrow a Jupyter session too."""
        user = SimpleNamespace(username="alice", mcp_scopes=["notebooks:read"])

        identity = identity_from_jupyter_user(user)

        assert identity.scopes == ("notebooks:read",)
        assert not identity.has_scope("notebooks:write")


class TestCurrentIdentity:
    """The identity of a request must not leak into another one."""

    def test_is_none_before_anything_sets_it(self):
        assert current_identity() is None

    def test_set_then_reset(self):
        token = set_current_identity(Identity(username="alice"))
        try:
            assert current_identity().username == "alice"
        finally:
            reset_current_identity(token)

        assert current_identity() is None

    def test_is_isolated_between_contexts(self):
        """Concurrent requests each run in their own context, so one setting an
        identity must not be visible to another."""
        set_in_other_context = {}

        def other_request():
            set_current_identity(Identity(username="bob"))
            set_in_other_context["seen"] = current_identity().username

        token = set_current_identity(Identity(username="alice"))
        try:
            contextvars.copy_context().run(other_request)

            assert set_in_other_context["seen"] == "bob"
            assert current_identity().username == "alice"
        finally:
            reset_current_identity(token)


class TestLoadTokenVerifierClass:
    """A deployment names its verifier as a string, so the parsing matters."""

    def test_loads_a_colon_separated_path(self):
        loaded = load_token_verifier_class("tests.test_identity:AcceptingVerifier")

        assert loaded is AcceptingVerifier

    def test_loads_a_dotted_path(self):
        loaded = load_token_verifier_class("tests.test_identity.AcceptingVerifier")

        assert loaded is AcceptingVerifier

    def test_rejects_a_path_without_a_module(self):
        with pytest.raises(ValueError, match=r"package\.module:ClassName"):
            load_token_verifier_class("AcceptingVerifier")

    def test_raises_when_the_module_does_not_exist(self):
        with pytest.raises(ModuleNotFoundError):
            load_token_verifier_class("no.such.module:Verifier")

    def test_raises_when_the_class_does_not_exist(self):
        with pytest.raises(AttributeError):
            load_token_verifier_class("tests.test_identity:NoSuchVerifier")


class TestResolveTokenVerifier:
    """How a deployment chooses who may call the MCP endpoint."""

    def test_returns_none_without_configuration(self, monkeypatch):
        """Nothing configured means nothing verified; the caller decides
        whether to refuse to start."""
        monkeypatch.delenv(TOKEN_VERIFIER_CLASS_ENV, raising=False)

        assert resolve_token_verifier(None) is None

    def test_falls_back_to_the_shared_secret(self, monkeypatch):
        monkeypatch.delenv(TOKEN_VERIFIER_CLASS_ENV, raising=False)
        from jupyter_mcp_server.server import CodeSandboxTokenVerifier

        verifier = resolve_token_verifier("secret-token")

        assert isinstance(verifier, CodeSandboxTokenVerifier)

    def test_a_named_class_wins_over_the_shared_secret(self, monkeypatch):
        """The point of the hook: a platform's own OAuth takes precedence."""
        monkeypatch.setenv(TOKEN_VERIFIER_CLASS_ENV, "tests.test_identity:AcceptingVerifier")

        verifier = resolve_token_verifier("secret-token")

        assert isinstance(verifier, AcceptingVerifier)

    def test_rejects_a_class_that_cannot_verify(self, monkeypatch):
        """Failing at startup beats failing on the first request."""
        monkeypatch.setenv(TOKEN_VERIFIER_CLASS_ENV, "tests.test_identity:NotAVerifier")

        with pytest.raises(TypeError, match="verify_token"):
            resolve_token_verifier(None)

    def test_ignores_a_blank_setting(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VERIFIER_CLASS_ENV, "   ")

        assert resolve_token_verifier(None) is None

    @pytest.mark.asyncio
    async def test_the_resolved_verifier_is_usable(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VERIFIER_CLASS_ENV, "tests.test_identity:AcceptingVerifier")

        verifier = resolve_token_verifier(None)
        access_token = await verifier.verify_token("anything")

        assert identity_from_access_token(access_token).client_id == "test-client"


class TestTokenVerifierProtocol:
    """The protocol is what the two modes agree on."""

    def test_an_object_with_verify_token_satisfies_it(self):
        assert isinstance(AcceptingVerifier(), TokenVerifier)

    def test_an_object_without_it_does_not(self):
        assert not isinstance(NotAVerifier(), TokenVerifier)
