# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Reaching a user's spaces through the Datalayer SDK.

The platform calls live in ``datalayer_core``, which is where they belong:
they are the platform's own API, useful to the CLI and to anything else that
talks to Datalayer, and duplicating them in an MCP extension would mean two
implementations drifting apart. This module is the adapter between that SDK
and what a tool needs.

Two things it has to reconcile.

**The credential is per request.** ``DatalayerClient`` resolves an API key
from its environment, which is right for a CLI run by one person and wrong
here: a server may act for several people over its life, and each request has
to use the token it arrived with. So a client is built per call, from the
identity of the request being served.

**The SDK is synchronous.** It uses ``requests``, and a blocking call inside an
async tool stalls the event loop — so the work goes to a thread. Building the
client there too keeps the whole round trip off the loop.

@module jupyter_mcp_spaces.spaces
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from datalayer_core import DatalayerClient
from datalayer_core.utils.urls import DatalayerURLs


logger = logging.getLogger(__name__)


class SpacesError(Exception):
    """The platform could not answer, in words worth showing an agent."""


def _caller_token() -> str:
    """The credential of the request being served."""
    try:
        from jupyter_mcp_server.identity import current_identity

        identity = current_identity()
    except Exception:  # noqa: BLE001 - no identity is not a failure
        return ""
    return (identity.token if identity else "") or ""


def _client() -> DatalayerClient:
    """A client bound to this request's caller."""
    token = _caller_token()
    if not token:
        raise SpacesError(
            "This request carried no Datalayer credential, so your spaces "
            "could not be read."
        )
    from jupyter_mcp_server.config import get_config

    # The server was started with the platform as its document URL, so that
    # is the spacer; the environment fills in the rest.
    configured = (get_config().document_url or "").rstrip("/")
    urls = DatalayerURLs.from_environment(spacer_url=configured or None)
    return DatalayerClient(urls=urls, api_key=token)


async def _call(name: str, *args: Any) -> Any:
    """Run a synchronous SDK method off the event loop."""

    def _run() -> Any:
        return getattr(_client(), name)(*args)

    try:
        return await asyncio.to_thread(_run)
    except SpacesError:
        raise
    except Exception as error:  # noqa: BLE001 - surfaced to the agent as text
        logger.warning("Datalayer call [%s] failed: %s", name, error)
        raise SpacesError(f"Datalayer could not be reached: {error}") from error


async def list_spaces() -> list[dict[str, Any]]:
    """The spaces this user can reach."""
    spaces = await _call("list_spaces")
    return [
        {
            "uid": space.uid,
            "name": space.name,
            "handle": space.handle,
            "description": space.description,
            "notebooks": len(space.notebooks()),
        }
        for space in spaces
    ]


async def list_notebooks() -> list[dict[str, Any]]:
    """Every notebook this user can reach, with the space it belongs to."""
    notebooks = await _call("list_notebooks")
    return [
        {
            "uid": item.uid,
            "name": item.name,
            "notebook_name": item.notebook_name,
            "space": item.space_name,
            "description": item.description,
        }
        for item in notebooks
    ]


def resolve(notebooks: list[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    """The notebooks a name could mean, best matches first.

    Exact on uid, then on either name, then anything containing it. Returning
    the candidates rather than choosing is deliberate: guessing which notebook
    somebody meant is how an agent edits the wrong one.
    """
    if not wanted:
        return []
    target = wanted.strip().lower()

    def names(n: dict[str, Any]) -> list[str]:
        return [
            (n.get("name") or "").lower(),
            (n.get("notebook_name") or "").lower(),
        ]

    exact_uid = [n for n in notebooks if n["uid"].lower() == target]
    if exact_uid:
        return exact_uid
    exact_name = [n for n in notebooks if target in names(n)]
    if exact_name:
        return exact_name
    stem = target.removesuffix(".ipynb")
    by_stem = [
        n for n in notebooks if any(x.removesuffix(".ipynb") == stem for x in names(n))
    ]
    if by_stem:
        return by_stem
    return [n for n in notebooks if any(target in x for x in names(n) if x)]
