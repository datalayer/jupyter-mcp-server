# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The notebook, its cells and their outputs, as resources a client may read.

Tools *push*: everything a call produces comes back whether the agent wanted
it or not, so a cell that printed a megabyte spends a megabyte of the
client's context on every read. Resources *pull*: the agent is told what
exists, and reads the one thing it needs.

That is the whole point of the output resource. A tool result says an output
is there, how big it is and what type it is; an agent that needs the bytes
asks for them, and an agent that only needed to know the cell succeeded does
not pay for them.

**Addressed by name and cell id, not by path and index.** A notebook path
contains slashes and cannot sit in one URI template segment without being
encoded into something nobody can read; the *name* is what every tool here
already takes and what `use_notebook` registered. And an index is a position
in a document somebody else is editing — between reading a notebook and
reading cell 4 of it, cell 4 may be a different cell. The nbformat 4.5 id is
not.

The scheme is `notebook://`, deliberately provider-neutral: this server talks
to a Jupyter server, and a `datalayer://` URI here would be a hosted
platform's identifier on a resource that has nothing to do with it.

@module jupyter_mcp_server.resources
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from jupyter_core.utils import ensure_async

from jupyter_mcp_server.models import Notebook

logger = logging.getLogger(__name__)

#: The three resources, as URI templates.
NOTEBOOK_RESOURCE = "notebook://{name}"
CELL_RESOURCE = "notebook://{name}/cells/{cell_id}"
OUTPUT_RESOURCE = "notebook://{name}/cells/{cell_id}/outputs/{index}"

#: A notebook someone is editing is worth holding for seconds, not minutes.
#: Long enough that reading a notebook and then three of its cells does not
#: fetch the document four times; short enough that an agent watching a cell
#: run sees it change.
NOTEBOOK_TTL_MS = 5_000

#: An output that exists does not change: a cell re-run replaces its outputs
#: rather than editing one, and the new ones are at new indices under a cell
#: whose id is the same. So this is the one thing here worth holding.
OUTPUT_TTL_MS = 60_000

#: The MIME type of a whole notebook.
NOTEBOOK_MIME = "application/x-ipynb+json"


#: Names a class deciding which of these resources this deployment serves.
#: See ``resolve_gate``.
RESOURCE_GATE_CLASS_ENV = "JUPYTER_MCP_RESOURCE_GATE_CLASS"

_gate: Any | None = None
_gate_resolved = False


def resolve_gate() -> Any | None:
    """The configured gate, or ``None`` when every resource is served.

    A deployment that addresses notebooks by its own identifiers serves its
    own `…://` resources and does not want these: `notebook://{name}` is the
    name a *worker* knows, and a hosted platform's client has never seen one.
    Rather than have that platform delete resources after the fact — the
    `_remove` dance the tools need — it names a gate here and this module
    asks before answering.

    Same shape and same strictness as the audit-sink seam: a class that
    cannot be imported or built is fatal, because a deployment that
    configured a gate and got one without it is serving resources it meant to
    withhold.
    """
    global _gate, _gate_resolved
    if _gate_resolved:
        return _gate
    _gate_resolved = True
    path = (os.environ.get(RESOURCE_GATE_CLASS_ENV) or "").strip()
    if not path:
        return None
    module_name, _, attribute = path.rpartition(".")
    if not module_name:
        raise RuntimeError(
            f"{RESOURCE_GATE_CLASS_ENV} is {path!r}, which is not a module.Class path"
        )
    try:
        module = importlib.import_module(module_name)
        gate = getattr(module, attribute)()
    except Exception as error:
        raise RuntimeError(
            f"{RESOURCE_GATE_CLASS_ENV} names {path!r}, which could not be used: {error}"
        ) from error
    if not callable(getattr(gate, "serves", None)):
        raise RuntimeError(
            f"{RESOURCE_GATE_CLASS_ENV} names {path!r}, which has no serves(uri) method"
        )
    _gate = gate
    return _gate


def use_gate(replacement: Any | None) -> None:
    """Swap the gate — for the tests, and at startup."""
    global _gate, _gate_resolved
    _gate = replacement
    _gate_resolved = replacement is not None


def serves(uri_template: str) -> bool:
    """Whether this deployment answers this resource.

    Asked at *read* time rather than at registration, so the answer can
    depend on configuration that arrives after the module is imported —
    which is when extensions are registered here.
    """
    gate = resolve_gate()
    if gate is None:
        return True
    try:
        return bool(gate.serves(uri_template))
    except Exception as error:  # noqa: BLE001 - a gate that cannot decide serves
        logger.debug("The resource gate could not decide about %s: %s", uri_template, error)
        return True


class ResourceWithheld(ValueError):
    """This deployment does not serve this resource.

    Distinct from `ResourceNotFound`, which means the thing asked for is not
    there. "We do not answer this here" and "there is no such cell" are
    different answers, and a client told the second when the first is true
    goes looking for a cell it will never find.
    """


class ResourceNotFound(ValueError):
    """Named rather than a bare `ValueError`, so a caller can tell "no such
    cell" from "the notebook could not be read" — one is the agent asking for
    something that is not there, the other is this server failing."""


async def read_notebook(notebook_manager: Any, name: str) -> Notebook:
    """The notebook behind a resource URI.

    Through the same connection the tools use, so a resource read right after
    a write sees the write: the collaborative document is the truth, and
    reading the file from disk would answer with whatever was last saved.

    Which connection that is depends on the mode, exactly as it does for
    `read_notebook`'s tool: in JUPYTER_SERVER mode there is no notebook
    websocket to open — `NotebookConnection` refuses a local notebook — and
    the document is reached through the server this process is part of.
    """
    from jupyter_mcp_server.server_context import ServerContext  # noqa: PLC0415
    from jupyter_mcp_server.tools._base import ServerMode  # noqa: PLC0415
    from jupyter_mcp_server.utils import resolve_notebook_connection  # noqa: PLC0415

    if name not in notebook_manager:
        raise ResourceNotFound(
            f"No notebook named {name!r} is in use. Open one with use_notebook, "
            "and list what is open with list_notebooks."
        )
    context = ServerContext.get_instance()
    if context.mode == ServerMode.JUPYTER_SERVER and context.contents_manager is not None:
        return await _read_notebook_locally(notebook_manager, name, context.contents_manager)
    async with resolve_notebook_connection(notebook_manager, name) as content:
        return Notebook(**content.as_dict())


async def _read_notebook_locally(
    notebook_manager: Any, name: str, contents_manager: Any
) -> Notebook:
    """The notebook, read the way the local tools read it.

    The live YDoc first — the same source every cell-mutation tool writes
    to — so a resource read right after our own write sees it rather than
    the on-disk copy the autosave has not flushed yet. `contents_manager` is
    the fallback for a notebook nobody has a collaborative session on.
    """
    from jupyter_mcp_server.jupyter_extension.context import get_server_context  # noqa: PLC0415
    from jupyter_mcp_server.utils import get_notebook_model  # noqa: PLC0415

    notebook_path = notebook_manager.get_notebook_path(name)
    serverapp = get_server_context().serverapp

    ydoc_path = notebook_path
    if serverapp and not Path(ydoc_path).is_absolute():
        ydoc_path = str(Path(serverapp.root_dir) / ydoc_path)

    nb_model = await get_notebook_model(serverapp, ydoc_path) if serverapp else None
    if nb_model:
        return Notebook(**nb_model.as_dict())

    model = await ensure_async(contents_manager.get(notebook_path, content=True, type="notebook"))
    if "content" not in model:
        raise ResourceNotFound(f"Could not read notebook content from {notebook_path}")
    return Notebook(**model["content"])


def find_cell(notebook: Notebook, cell_id: str) -> tuple[int, Any]:
    """The cell with this id, and where it currently sits.

    The index comes back with it because a caller almost always wants to say
    *which* cell in a message, and looking it up twice invites the two
    answers to disagree after an edit lands between them.
    """
    for index, cell in enumerate(notebook.cells):
        if str(getattr(cell, "id", "")) == cell_id:
            return index, cell
    raise ResourceNotFound(
        f"No cell with id {cell_id!r} in this notebook. Cell ids are on every "
        "cell result; an index is not an id."
    )


def output_mime(output: Any) -> str:
    """The output's own MIME type, not `text/plain` for everything.

    An image read as text is a screenful of base64 in the agent's context,
    and the agent cannot tell that is what happened. The type is what lets a
    client decide whether to render it, save it or leave it alone.
    """
    if not isinstance(output, dict):
        return "text/plain"
    kind = output.get("output_type")
    if kind == "stream":
        return "text/plain"
    if kind == "error":
        return "text/plain"
    data = output.get("data")
    if isinstance(data, dict) and data:
        # The richest representation the cell produced. `text/plain` is the
        # fallback every kernel attaches, so preferring it would throw away
        # the image in every image output.
        for candidate in data:
            if candidate != "text/plain":
                return str(candidate)
        return "text/plain"
    return "text/plain"


def output_text(output: Any) -> str:
    """One output as text, in whatever form it actually has."""
    if not isinstance(output, dict):
        return str(output)
    kind = output.get("output_type")
    if kind == "stream":
        text = output.get("text", "")
        return "".join(text) if isinstance(text, list) else str(text)
    if kind == "error":
        traceback = output.get("traceback") or []
        if traceback:
            return "\n".join(str(line) for line in traceback)
        return f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
    data = output.get("data")
    if isinstance(data, dict):
        chosen = output_mime(output)
        value = data.get(chosen, data.get("text/plain", ""))
        return "".join(value) if isinstance(value, list) else str(value)
    return json.dumps(output)


def cell_document(name: str, index: int, cell: Any) -> str:
    """One cell, as JSON rather than as the tools' readable text.

    A resource is read by a program. The tools' `=====Cell 3 | type: code=====`
    banner is for a person reading a transcript, and an agent parsing it back
    into fields is an agent that will get it wrong on the first cell whose
    source contains the word "Cell".
    """
    return json.dumps(
        {
            "id": str(getattr(cell, "id", "")),
            "index": index,
            "cell_type": cell.cell_type,
            "source": cell.get_source("raw"),
            "execution_count": getattr(cell, "execution_count", None),
            # The outputs are *listed*, not inlined: their URIs and their
            # types, so an agent can decide which to read. Inlining them here
            # would make reading a cell cost whatever the cell printed, which
            # is the thing these resources exist to avoid.
            "outputs": [
                {
                    "index": position,
                    "mimeType": output_mime(output),
                    "uri": (
                        f"notebook://{name}/cells/"
                        f"{getattr(cell, 'id', '')}/outputs/{position}"
                    ),
                }
                for position, output in enumerate(getattr(cell, "outputs", []) or [])
            ],
        },
        indent=2,
    )
