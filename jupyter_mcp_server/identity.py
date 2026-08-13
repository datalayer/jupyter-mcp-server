# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Who is calling the MCP server, in either mode.

The server runs in two modes, and each authenticates through a different
mechanism of the stack it is embedded in:

``MCP_SERVER``
    A FastMCP application over streamable HTTP. The MCP SDK authenticates a
    request with a *token verifier*: an object with
    ``async verify_token(token) -> AccessToken | None``. When one is set, the
    SDK installs its bearer-auth middleware and refuses anything unverified.

``JUPYTER_SERVER``
    Tornado handlers inside a Jupyter Server. Jupyter authenticates a request
    with its *identity provider*, and the handlers read the result from
    ``self.current_user``.

Both are pluggable, but only through mechanisms owned by two different
projects, which makes "authenticate MCP clients the way my platform does"
harder than it should be. This module gives that a single shape:

- :class:`Identity` — what a verified caller is, the same in both modes;
- :func:`resolve_token_verifier` — build the MCP_SERVER verifier from
  configuration, so a deployment can supply its own without patching code;
- :func:`identity_from_access_token` and :func:`identity_from_jupyter_user` —
  turn what each mode produces into the same :class:`Identity`;
- :func:`current_identity` / :func:`set_current_identity` — reach it from a
  tool, whichever mode registered it.

A deployment that wants its own authentication implements a verifier and names
it in ``JUPYTER_MCP_TOKEN_VERIFIER_CLASS``; nothing else has to change.

@module jupyter_mcp_server.identity
"""

from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from jupyter_mcp_server.log import logger

if TYPE_CHECKING:
    # Only for the annotations: the contract is the MCP SDK's `AccessToken`,
    # and naming it here documents it without making this module import the
    # SDK at startup.
    from mcp.server.auth.provider import AccessToken

#: Import path of the token verifier to use in MCP_SERVER mode, as
#: ``package.module:ClassName`` or ``package.module.ClassName``. The class is
#: instantiated with no arguments, so it reads whatever configuration it needs
#: from the environment.
TOKEN_VERIFIER_CLASS_ENV = "JUPYTER_MCP_TOKEN_VERIFIER_CLASS"  # noqa: S105


@dataclass(frozen=True)
class Identity:
    """A verified caller, in whichever mode verified them.

    The tools care about three things, and they mean the same in both modes:
    who the user is, which client is acting for them, and what that client was
    allowed to do.
    """

    #: Stable identifier of the user. In JUPYTER_SERVER mode this is the
    #: Jupyter username; in MCP_SERVER mode whatever the verifier resolved.
    username: str
    #: The client acting on their behalf, when the credential names one.
    client_id: str = ""
    #: What the credential allows. Empty means "unscoped", which a platform
    #: treats as full authority for that user, not as no authority.
    scopes: tuple[str, ...] = ()
    #: Anything the verifier wants to carry through to the tools.
    extra: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, scope: str) -> bool:
        """Whether the credential allows this kind of operation.

        An unscoped credential — a Jupyter token, a personal access token —
        allows everything the user can do, because nothing was delegated.
        """
        return not self.scopes or scope in self.scopes

    def describe(self) -> str:
        return f"{self.username} via {self.client_id or 'direct'}"


#: The identity of the request being served, so a tool can consult it without
#: every tool signature having to carry it.
_current_identity: contextvars.ContextVar[Identity | None] = contextvars.ContextVar(
    "jupyter_mcp_current_identity", default=None
)


def current_identity() -> Identity | None:
    """The caller of the request being served, when it was authenticated."""
    return _current_identity.get()


def set_current_identity(identity: Identity | None) -> contextvars.Token:
    """Record the caller for the duration of a request.

    Returns the token to pass to :func:`reset_current_identity`, so concurrent
    requests cannot leak an identity into one another.
    """
    return _current_identity.set(identity)


def reset_current_identity(token: contextvars.Token) -> None:
    """Forget the caller again."""
    _current_identity.reset(token)


@runtime_checkable
class TokenVerifier(Protocol):
    """What MCP_SERVER mode needs to authenticate a bearer token.

    The shape is the MCP SDK's, so anything satisfying it can be handed
    straight to FastMCP.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        """The access token behind a bearer token, or ``None`` to refuse it."""
        ...


def identity_from_access_token(access_token: AccessToken) -> Identity:
    """The :class:`Identity` behind an MCP ``AccessToken``."""
    scopes = tuple(getattr(access_token, "scopes", ()) or ())
    return Identity(
        username=str(
            getattr(access_token, "subject", "")
            or getattr(access_token, "client_id", "")
            or "unknown"
        ),
        client_id=str(getattr(access_token, "client_id", "") or ""),
        scopes=scopes,
    )


def identity_from_jupyter_user(user: Any) -> Identity:
    """The :class:`Identity` behind a Jupyter ``current_user``.

    Jupyter's identity model has no notion of scopes, so the identity is
    unscoped and therefore carries the user's full authority — which is what a
    Jupyter token has always meant. An identity provider that does know about
    scopes can attach them under the ``mcp_scopes`` attribute.
    """
    if user is None:
        return Identity(username="anonymous")
    username = (
        getattr(user, "username", None)
        or (user.get("username") if isinstance(user, dict) else None)
        or str(user)
    )
    scopes = getattr(user, "mcp_scopes", None)
    if scopes is None and isinstance(user, dict):
        scopes = user.get("mcp_scopes")
    return Identity(
        username=str(username),
        client_id=str(getattr(user, "client_id", "") or ""),
        scopes=tuple(scopes or ()),
    )


def load_token_verifier_class(path: str) -> type:
    """Import a verifier class named as ``module:Class`` or ``module.Class``."""
    if ":" in path:
        module_name, class_name = path.split(":", 1)
    else:
        module_name, _, class_name = path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Cannot read '{path}' as a class path; use 'package.module:ClassName' "
            "or 'package.module.ClassName'."
        )
    module = import_module(module_name)
    return getattr(module, class_name)


def resolve_token_verifier(default_token: str | None = None) -> TokenVerifier | None:
    """The token verifier this deployment wants, if any.

    Resolution order, most specific first:

    1. ``JUPYTER_MCP_TOKEN_VERIFIER_CLASS`` — a class supplied by the
       deployment, which is how a platform plugs in its own OAuth;
    2. ``default_token`` — the shared secret of ``--mcp-token``, the simple
       case that needs no code;
    3. nothing, leaving the endpoint unauthenticated, which the caller is
       expected to refuse unless it was asked for explicitly.
    """
    class_path = (os.environ.get(TOKEN_VERIFIER_CLASS_ENV) or "").strip()
    if class_path:
        verifier_class = load_token_verifier_class(class_path)
        verifier = verifier_class()
        if not isinstance(verifier, TokenVerifier):
            raise TypeError(
                f"{class_path} does not implement "
                "'async verify_token(token) -> AccessToken | None'."
            )
        logger.info("MCP endpoint authentication delegated to %s", class_path)
        return verifier

    if default_token:
        from jupyter_mcp_server.server import CodeSandboxTokenVerifier

        logger.info("MCP endpoint token authentication enabled (using MCP_TOKEN)")
        return CodeSandboxTokenVerifier(default_token)

    return None
