# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Telling a client that what it already holds is still current.

A tool that stamps an ETag lets a client ask a cheaper question. Instead of
choosing between a copy that may be stale and fetching the whole thing again,
it sends the version it holds and is told, in one field, that it is still
right.

**This saves bandwidth, not work.** The tool still runs — the version is
computed from what it answered, so there is no way to know the answer is
unchanged without producing it. That is worth stating plainly, because an
ETag on an HTTP endpoint often saves both and somebody will reasonably assume
this one does too. Where it pays is `read_notebook` on a large notebook: the
answer is megabytes and the comparison is a hash.

The reply is the shape the Datalayer gateway already uses for the results it
synthesises, so a client sees one kind of *not modified* whichever end
produced it — and it says so in a named field rather than by being empty,
because a client that read an empty result as an empty *notebook* would show
somebody no cells at all.

@module jupyter_mcp_server.revalidation
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.extension import Extension
from mcp.types import CallToolRequestParams, CallToolResult

from jupyter_mcp_server.results import CACHE_META_KEY

logger = logging.getLogger(__name__)

#: The extension identifier, advertised so a client knows it may ask.
REVALIDATION_EXTENSION = "io.datalayer/revalidation"

#: The field that says there is no payload, as opposed to an empty one.
NOT_MODIFIED_KEY = "notModified"


def _cache_block(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    block = meta.get(CACHE_META_KEY)
    return block if isinstance(block, dict) else {}


def requested_etag(params: Any) -> str:
    """The version a client says it already has, from the request's `_meta`."""
    return str(_cache_block(getattr(params, "meta", None)).get("etag") or "")


def answered_etag(result: Any) -> str:
    """The version a result carries, or `""` when the tool stamps none."""
    return str(_cache_block(getattr(result, "meta", None)).get("etag") or "")


def not_modified(block: dict[str, Any]) -> CallToolResult:
    """The answer to a client that already has this result.

    Carries the hints again, so holding it for another window costs nothing,
    and says plainly that there is no payload rather than answering an empty
    one.
    """
    return CallToolResult(
        content=[],
        structured_content=None,
        meta={CACHE_META_KEY: {**block, NOT_MODIFIED_KEY: True}},
    )


class RevalidationExtension(Extension):
    """Turns a matching ETag into *not modified*."""

    identifier = REVALIDATION_EXTENSION

    def settings(self) -> dict[str, Any]:
        return {"notModifiedKey": NOT_MODIFIED_KEY}

    async def intercept_tool_call(
        self, params: CallToolRequestParams, ctx: Any, call_next: Any
    ) -> Any:
        wanted = requested_etag(params)
        result = await call_next(ctx)
        if getattr(result, "is_error", False):
            # An error is never "what you already have". A client that
            # treated a refusal as its cached answer being current would go
            # on using a result the server has just declined to confirm.
            return result
        block = _cache_block(getattr(result, "meta", None))
        current = str(block.get("etag") or "")
        if not current or current != wanted:
            # No ETag on this answer, or a different one: send the answer.
            #
            # `not current` is doing real work and is not a tidier way of
            # writing the comparison. A tool that stamps no ETag answers
            # `""`, and a client that holds none asks with `""` — without it
            # the two would compare equal and a first call to an unstamped
            # tool would come back "unchanged" about something the client
            # has never seen.
            return result
        logger.debug("Answering not-modified for %s", getattr(params, "name", ""))
        return not_modified(block)


def revalidation_extension() -> RevalidationExtension:
    """The extension, for `MCPServer(extensions=[...])`."""
    return RevalidationExtension()
