# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Addressing a cell by something that survives an edit.

Every cell tool takes a ``cell_index``. An index is a position, and a position
is only true until somebody inserts a cell above it — which, in a notebook a
person and an agent are both working in, is constantly. The agent reads cell 3,
decides to fix it, and by the time the edit lands cell 3 is a different cell.
Nothing errors. The wrong cell is quietly overwritten.

nbformat 4.5 gave every cell an ``id`` for exactly this. So each cell tool also
takes a ``cell_id``, and every result says which id it acted on, so an agent
that read a cell can come back to *that* cell rather than to whatever is now in
its place.

An id that is no longer in the notebook is an error naming the id, never a
fallback to the index that came with it: falling back would edit an arbitrary
cell in the name of safety, which is the whole failure this exists to prevent.

@module jupyter_mcp_server.cell_ids
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jupyter_mcp_server.results import add_meta

logger = logging.getLogger(__name__)


class UnknownCellId(ValueError):
    """The id names no cell in this notebook.

    Its own type so a caller can tell "the cell is gone" — somebody deleted
    it, or this is another notebook — from an index that is out of range.
    """


def _id_of(cell: Any) -> str:
    """The id of a cell, however it is being represented.

    Three representations, and they do not share a base class. A YDoc cell is
    a `pycrdt.Map` — mapping-like, and emphatically not a `dict`, which is
    what an `isinstance(cell, dict)` check gets wrong and gets wrong
    silently: every id comes back empty and the whole feature quietly does
    nothing. A file cell is an `nbformat` node, which is a dict *and* has
    attribute access. A cell from a notebook written before nbformat 4.5 has
    no id at all, and empty is the honest answer for it.

    So: anything that can be asked by key is asked by key.
    """
    getter = getattr(cell, "get", None)
    if callable(getter):
        try:
            return str(getter("id") or "")
        except Exception:  # fall through to attribute access
            pass
    return str(getattr(cell, "id", "") or "")


async def cell_ids(
    *,
    mode: Any,
    contents_manager: Any = None,
    notebook_manager: Any = None,
    notebook_name: str | None = None,
) -> list[str]:
    """The ids of the notebook's cells, in order.

    Read the same three ways the cell tools write: the collaborative document
    when there is one, the file when there is not, and the websocket
    connection in ``MCP_SERVER`` mode. Reading it the same way is what makes
    the index this resolves to the index those paths will use.
    """
    from jupyter_mcp_server.tools._base import ServerMode
    from jupyter_mcp_server.utils import (
        get_notebook_model,
        resolve_notebook_connection,
        resolve_notebook_path,
    )

    if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context

        serverapp = get_server_context().serverapp
        notebook_path, _ = resolve_notebook_path(notebook_manager, notebook_name)
        if serverapp and not Path(notebook_path).is_absolute():
            notebook_path = str(Path(serverapp.root_dir) / notebook_path)
        if serverapp:
            model = await get_notebook_model(serverapp, notebook_path)
            if model is not None:
                return [_id_of(cell) for cell in model._doc.ycells]
        import nbformat

        with open(notebook_path, encoding="utf-8") as handle:
            return [_id_of(cell) for cell in nbformat.read(handle, as_version=4).cells]

    if notebook_manager is not None:
        async with resolve_notebook_connection(notebook_manager, notebook_name) as notebook:
            return [_id_of(cell) for cell in notebook._doc.ycells]

    raise ValueError("no way to read this notebook's cells")


async def resolve(
    *,
    cell_index: int | None = None,
    cell_id: str | None = None,
    mode: Any,
    contents_manager: Any = None,
    notebook_manager: Any = None,
    notebook_name: str | None = None,
) -> int:
    """The index to act on, with the id of that cell attached to the result.

    Given an id, this is where the index comes from. Given an index, the id
    is read back and attached, so the agent has something to address the same
    cell with next time — which is the whole point: an agent can only use ids
    it has been given.

    Reading the notebook to attach an id is not free, and it is worth it. The
    alternative is an agent that has no way to refer to a cell except by a
    number that goes stale the moment anyone types.

    Raises:
        UnknownCellId: The id names no cell here.
        ValueError: Neither an index nor an id was given.
    """
    if cell_id is None and cell_index is None:
        raise ValueError("name the cell to act on, by cell_index or by cell_id")
    try:
        ids = await cell_ids(
            mode=mode,
            contents_manager=contents_manager,
            notebook_manager=notebook_manager,
            notebook_name=notebook_name,
        )
    except UnknownCellId:
        raise
    except Exception as error:
        if cell_id is not None:
            # There is no index to fall back to that means anything, and
            # guessing one would edit an arbitrary cell.
            raise UnknownCellId(
                f"Could not read this notebook's cells to find {cell_id!r}: {error}"
            ) from error
        # An index was given and the notebook could not be read here. The
        # tool is about to read it its own way and will say so properly;
        # losing the result's id is not worth failing the call for.
        logger.debug("Could not read cell ids to annotate the result: %r", error)
        return cell_index

    if cell_id is not None:
        if cell_id not in ids:
            raise UnknownCellId(
                f"No cell {cell_id!r} in this notebook. It was deleted, or it belongs to "
                "another notebook. Read the notebook again for current cell ids."
            )
        cell_index = ids.index(cell_id)

    if 0 <= cell_index < len(ids) and ids[cell_index]:
        add_meta(cell_id=ids[cell_index])
    # No id to attach means the notebook predates nbformat 4.5, where cell
    # ids were introduced. Addressing by id is simply unavailable for it, and
    # saying nothing is better than inventing one: an id generated on read is
    # different on the next read, so it would name a cell only until somebody
    # looked again.
    return cell_index


async def resolve_many(
    *,
    cell_indices: list[int] | None = None,
    cell_ids_wanted: list[str] | None = None,
    mode: Any,
    contents_manager: Any = None,
    notebook_manager: Any = None,
    notebook_name: str | None = None,
) -> list[int]:
    """The same, for a tool that acts on several cells at once.

    Every id is resolved before any of them is used, so a list with one bad
    id fails whole rather than half-deleting a notebook.
    """
    if not cell_indices and not cell_ids_wanted:
        raise ValueError("name the cells to act on, by cell_indices or by cell_ids")
    ids = await cell_ids(
        mode=mode,
        contents_manager=contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    if cell_ids_wanted:
        missing = [wanted for wanted in cell_ids_wanted if wanted not in ids]
        if missing:
            raise UnknownCellId(
                f"No cell {missing[0]!r} in this notebook"
                + (f" (and {len(missing) - 1} more)" if len(missing) > 1 else "")
                + ". Read the notebook again for current cell ids."
            )
        cell_indices = [ids.index(wanted) for wanted in cell_ids_wanted]
    resolved = [ids[index] for index in cell_indices if 0 <= index < len(ids) and ids[index]]
    if resolved:
        add_meta(cell_ids=resolved)
    return cell_indices
