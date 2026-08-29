# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""One place that knows what a tool result looks like on the wire.

A ``tools/call`` may answer with ``content`` — text and images, for a person
and for the model to read — and with ``structuredContent``, the same answer as
data. A server cannot know which of the two a client puts in front of the
model, and the Core Primitives Working Group is redesigning that contract for
exactly that reason. Content annotations (``audience``, ``priority``) are in
the same discussion, and may be deprecated outright if nobody adopts them.

So the shape is built here and nowhere else. When the redesign lands, or
annotations go, this file changes and the eighteen tools do not.

The tools keep returning what they already return — a string, or a list of
text and images. The :func:`structured` decorator turns that into the one
shape, and a tool that has something to add attaches it through
:func:`add_meta` from wherever it runs, without threading a return value back
up through helpers that have no business carrying it.

@module jupyter_mcp_server.results
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import wraps
from typing import Any

from mcp.types import Annotations, CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: Who a piece of content is for. The specification's two audiences.
AUDIENCE_ASSISTANT = "assistant"
AUDIENCE_USER = "user"

#: Where a result's cache hints live (SEP-2549). The protocol's namespace,
#: not this server's: a client caches on the standard key or not at all.
CACHE_META_KEY = "io.modelcontextprotocol/cache"

#: Caching scopes. `session` is the same answer for everyone talking to this
#: server; `private` is one caller's and must never be shared by a proxy.
SCOPE_SESSION = "session"
SCOPE_PRIVATE = "private"

#: The namespace this server's own `_meta` keys live under. Namespaced because
#: `_meta` is shared with the protocol and with every other extension: a bare
#: `cell_id` would be a collision waiting to happen.
META_NAMESPACE = "io.jupyter-mcp"


def meta_key(name: str) -> str:
    """A `_meta` key of this server's, namespaced."""
    return f"{META_NAMESPACE}/{name}"


#: What the tool running right now has attached to its result. A context
#: variable rather than an argument because the facts worth attaching — the id
#: of the cell that was actually edited, the notebook it was resolved to — are
#: known deep inside helpers whose signatures should not have to carry a
#: result object up and down for the sake of one dictionary.
_pending: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "jupyter_mcp_result_meta", default=None
)


def add_meta(**values: Any) -> None:
    """Attach facts to the result of the tool call running right now.

    Silently does nothing outside a tool call, so a helper shared with a
    non-tool code path — the Jupyter Server extension's handlers, a test —
    does not have to know whether it is inside one.
    """
    pending = _pending.get()
    if pending is None:
        return
    for name, value in values.items():
        if value is not None:
            pending[meta_key(name)] = value


def as_text(value: Any) -> str:
    """The text rendering of a structured answer.

    Text is what most clients still show the model, so it is never omitted:
    a result with `structuredContent` and empty `content` is invisible to a
    client that has not adopted the former.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(value)


def _content_of(value: Any, *, annotations: Annotations | None) -> list[Any]:
    """The `content` blocks for a tool's return value.

    Images are passed through as they are: they are already content blocks,
    and re-rendering one as text would throw the image away.
    """
    if isinstance(value, str):
        return [TextContent(type="text", text=value, annotations=annotations)]
    if isinstance(value, ImageContent):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        blocks: list[Any] = []
        for item in value:
            blocks.extend(_content_of(item, annotations=annotations))
        return blocks
    return [TextContent(type="text", text=as_text(value), annotations=annotations)]


def _annotations(audience: Sequence[str], priority: float | None) -> Annotations | None:
    """The content annotations, or none at all when there is nothing to say.

    Set here and nowhere else. If the Working Group deprecates annotations,
    this function stops returning them and no tool changes.
    """
    if not audience and priority is None:
        return None
    return Annotations(
        audience=list(audience) or None,
        priority=priority,
    )


class ToolAnswer(BaseModel):
    """What every tool of this server answers with.

    Declared so the shape is *advertised* rather than merely produced. A tool
    that returns structure without saying what it will return leaves a client
    nothing to validate against and the generated reference nothing to show —
    the call works and the contract is invisible, which is the worst of both.

    Extra fields are allowed on purpose. A tool that already answers with a
    mapping keeps its own keys (see :func:`_default_shape`), and those are the
    interesting part of its answer; forbidding them would mean either
    flattening every tool into one shape or declaring nothing at all.
    """

    model_config = ConfigDict(extra="allow")

    kind: str = Field(
        description=(
            "What this result is — 'cell.read', 'notebooks.list' and so on. "
            "Lets a client tell one answer from another without matching prose."
        )
    )
    result: Any = Field(
        default=None,
        description=(
            "The answer itself: a message, the rows of a listing, or the "
            "outputs of an execution in order."
        ),
    )


class TableAnswer(ToolAnswer):
    """A listing that also comes back as rows keyed by its header."""

    columns: list[str] = Field(default_factory=list, description="The header, in order.")
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="One object per row, keyed by the header."
    )
    count: int = Field(default=0, description="How many rows.")


class OutputsAnswer(ToolAnswer):
    """Cell or execution outputs, in order."""

    outputs: list[Any] = Field(
        default_factory=list,
        description="The outputs in order: text as text, an image as its own object.",
    )
    count: int = Field(default=0, description="How many outputs.")
    images: int = Field(default=0, description="How many of them are images.")


def _is_data(value: Any) -> bool:
    """Whether a sequence can go into the structured answer as it is.

    Deliberately narrow: content blocks are a list too, and they are the
    server's own models rather than the tool's answer, so they keep the text
    rendering. Anything here has to survive `json.dumps` without help.
    """
    if not isinstance(value, (list, tuple)):
        return False
    return all(
        isinstance(item, Mapping) or isinstance(item, (str, int, float, bool)) or item is None
        for item in value
    )


def _default_shape(value: Any) -> dict[str, Any]:
    """The structured answer for a tool that did not ask for a particular one.

    A tool already returning a mapping *is* the structured answer, and its
    keys are carried through. Rendering it as a string under ``result`` would
    hand a client JSON to parse where it previously had an object — a silent
    break, because the text still arrives and nothing looks wrong until
    something tries to read a field.

    Anything else goes under ``result``, the key the SDK's own
    ``wrap_output`` used for a scalar answer.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if _is_data(value):
        # A list of records is structured data for the same reason a mapping
        # is. `list_sandboxes` answers with one, and rendering it as text put
        # a JSON *string* under `result` — the client parses what it was
        # already handed, which is what this function exists to avoid.
        return {"result": [dict(item) if isinstance(item, Mapping) else item for item in value]}
    return {"result": as_text(value)}


def etag_for(payload: Any) -> str:
    """A version identifier for whatever this answer is made of.

    Derived from the content rather than from a document version, and that is
    a decision worth stating because the plan asked for the version.

    A notebook's version is not one number here. A cell can be read through
    the contents manager, through a live CRDT document or through a sandbox,
    and the three do not share a counter; a tool that read one and reported
    another's version would hand out an identifier that compares equal to
    answers it has nothing to do with. Hashing what was actually answered
    cannot be wrong in that way: two reads of an unchanged cell compare
    equal, and a changed one does not.

    Weak (`W/`), because it says *this means the same thing* rather than
    *this is byte-for-byte what you had* — the same form the Datalayer
    gateway stamps on the answers it synthesises, so a client sees one kind
    of ETag whichever end produced it.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return 'W/"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32] + '"'


def answer(
    value: Any,
    *,
    kind: str,
    shape: Callable[[Any], Any] | None = None,
    meta: dict[str, Any] | None = None,
    audience: Sequence[str] = (),
    priority: float | None = None,
    ttl_ms: int | None = None,
    cache_scope: str = SCOPE_PRIVATE,
    etag: bool = False,
) -> CallToolResult:
    """Build the one result shape from what a tool returned.

    Args:
        value: What the tool answered — a string, or content blocks.
        kind: What this result *is*, carried in `structuredContent` so a
            client can tell one answer from another without matching prose.
        shape: Turns the tool's return value into the structured answer.
            Defaults to carrying it under ``result`` — the key the SDK's own
            ``wrap_output`` uses for a scalar answer, so a tool whose answer
            really is one string keeps the key a client already reads.
        meta: Facts to attach beyond the ones the tool attached itself.
        audience: Who the content is for.
        priority: How important it is, 0 to 1.
        ttl_ms: How long the answer is worth holding (SEP-2549). Only for a
            tool whose answer is worth holding at all: an agent listing the
            same notebooks four times while it works should not ask four
            times, but a hint on an answer that moves is worse than none.
        cache_scope: `private` unless the answer genuinely is the same for
            every caller. A shared cache holding one person's notebooks for
            another is the failure this exists to prevent.
        etag: Also carry a version of this answer, so a client can ask
            whether what it holds is still current instead of choosing
            between a stale copy and fetching again. See `etag_for`.
    """
    annotations = _annotations(audience, priority)
    structured: dict[str, Any] = {"kind": kind}
    try:
        shaped = shape(value) if shape is not None else _default_shape(value)
    except Exception:  # a shaping bug must not lose the answer
        logger.exception("Could not shape the result of %s; answering text only", kind)
        shaped = {"result": as_text(value)}
    if isinstance(shaped, dict):
        structured.update(shaped)
    else:
        structured["result"] = shaped
    collected = dict(_pending.get() or {})
    collected.update(meta or {})
    if ttl_ms is not None:
        block: dict[str, Any] = {"ttlMs": ttl_ms, "cacheScope": cache_scope}
        if etag:
            # Over the structured answer, not the whole result: the content
            # blocks are a rendering of the same facts, and hashing them too
            # would make an ETag change when the prose does.
            block["etag"] = etag_for(structured)
        collected[CACHE_META_KEY] = block
    return CallToolResult(
        content=_content_of(value, annotations=annotations),
        structured_content=structured,
        meta=collected or None,
    )


def structured(
    kind: str,
    *,
    shape: Callable[[Any], Any] | None = None,
    audience: Sequence[str] = (),
    priority: float | None = None,
    ttl_ms: int | None = None,
    cache_scope: str = SCOPE_PRIVATE,
    etag: bool = False,
) -> Callable:
    """Wrap a tool so its answer comes back in the one shape.

    A decorator rather than a change to each body: the bodies already return
    the right *information*, and what has to be centralised is the wire
    format. It also means a tool that raises still raises — the failure path
    is the SDK's, untouched.

    Applied under ``@mcp.tool``, so the signature the schema is built from
    is the tool's own. The tool annotates its return type with the model
    matching its ``shape`` — :class:`ToolAnswer`, :class:`TableAnswer` or
    :class:`OutputsAnswer` — which both advertises an output schema to
    clients and has the SDK validate what this builds against it. Returning
    nothing there advertises nothing: the reference loses its Output section
    and a client must call the tool to learn what comes back.
    """

    def decorate(function: Callable) -> Callable:
        @wraps(function)
        async def wrapper(*arguments: Any, **keywords: Any) -> CallToolResult:
            token = _pending.set({})
            try:
                value = await function(*arguments, **keywords)
                return answer(
                    value,
                    kind=kind,
                    shape=shape,
                    audience=audience,
                    priority=priority,
                    ttl_ms=ttl_ms,
                    cache_scope=cache_scope,
                    etag=etag,
                )
            finally:
                _pending.reset(token)

        return wrapper

    return decorate
