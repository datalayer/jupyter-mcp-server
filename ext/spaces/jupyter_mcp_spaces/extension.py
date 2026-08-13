# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The Jupyter MCP Server spaces extension.

Datalayer keeps notebooks in **spaces**, addressed by uid. It has no
filesystem and no kernels API, so the tools that assume a Jupyter server —
``list_files``, ``list_kernels``, ``connect_to_jupyter`` — have nothing to
answer and return the platform router's 404. An agent handed a tool that
always fails keeps trying it and then invents explanations, which is how a
hosted session ends up offering to connect to a Jupyter on your laptop.

So this extension does two things when the document provider is
``datalayer``:

- **replaces** ``list_notebooks`` with one that lists the notebooks in the
  user's spaces, and teaches ``use_notebook`` to accept a name or a uid;
- **removes** the tools that cannot work, so they are never offered.

Both matter for how an agent behaves. Keeping the upstream names is
deliberate: an agent asked to list notebooks calls ``list_notebooks``, and a
differently named tool would be found second, after the empty one has already
answered "you have none".

@module jupyter_mcp_spaces.extension
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.extensions import JupyterMCPExtension
from mcp.types import ToolAnnotations
from pydantic import Field
from reactor import PluginCompatibility, PluginManifest

from jupyter_mcp_spaces import spaces


logger = logging.getLogger(__name__)

#: The tools that assume a Jupyter server, and so cannot be answered by a
#: platform that has spaces instead of files and runtimes instead of kernels.
JUPYTER_ONLY_TOOLS = (
    "list_files",
    "list_kernels",
    "connect_to_jupyter",
)


class SpacesExtension(JupyterMCPExtension):
    """Datalayer spaces as the notebooks an agent can reach."""

    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="jupyter-mcp-spaces",
            version="0.1.0",
            description=(
                "List and open the notebooks of a Datalayer space, in place of "
                "the filesystem tools of a Jupyter server."
            ),
            author="Datalayer",
            tags=["datalayer", "spaces", "notebooks"],
            compatibility=PluginCompatibility(api_version="v1"),
        )

    def register_tools(self, mcp: Any) -> None:
        if not _serving_datalayer():
            # Pointed at a Jupyter server: its own tools are the right ones,
            # and replacing them would break the ordinary case.
            logger.debug("Document provider is not datalayer; spaces tools not registered")
            return

        _remove(mcp, JUPYTER_ONLY_TOOLS)
        # Removed before registering, not merely re-declared: FastMCP warns
        # "Tool already exists" and *keeps the original*, so a replacement
        # registered on top of a live name silently does nothing.
        _remove(mcp, ("list_notebooks",))

        @mcp.tool(
            annotations=ToolAnnotations(title="List Spaces", readOnlyHint=True),
        )
        async def list_spaces() -> list[dict[str, Any]]:
            """List the Datalayer spaces you can reach.

            A space holds notebooks, documents and datasets. Most people have
            one; teams have several.
            """
            try:
                return await spaces.list_spaces()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

        @mcp.tool(
            annotations=ToolAnnotations(title="List Notebooks", readOnlyHint=True),
        )
        async def list_notebooks() -> list[dict[str, Any]]:
            """List the notebooks in your Datalayer spaces.

            Returns each notebook's name, its uid, and the space it belongs
            to. Pass a name or a uid to `use_notebook` to open one.
            """
            try:
                return await spaces.list_notebooks()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

        @mcp.tool(
            annotations=ToolAnnotations(title="Find Notebook", readOnlyHint=True),
        )
        async def find_notebook(
            name: Annotated[
                str,
                Field(description="A notebook name, part of one, or a uid"),
            ],
        ) -> dict[str, Any]:
            """Find which notebook a name refers to, before opening it.

            Answers with one match, or with the candidates when a name is
            ambiguous — so the right notebook is chosen rather than guessed.
            """
            try:
                notebooks = await spaces.list_notebooks()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

            matches = spaces.resolve(notebooks, name)
            if not matches:
                return {
                    "found": False,
                    "message": (
                        f"No notebook of yours matches '{name}'. "
                        "Use list_notebooks to see them all."
                    ),
                }
            if len(matches) > 1:
                return {
                    "found": False,
                    "ambiguous": True,
                    "candidates": matches,
                    "message": (
                        f"{len(matches)} notebooks match '{name}'. "
                        "Ask which one is meant, then use its uid."
                    ),
                }
            return {"found": True, "notebook": matches[0]}

        logger.info(
            "Datalayer spaces tools registered; %s hidden",
            ", ".join(JUPYTER_ONLY_TOOLS),
        )


def _serving_datalayer() -> bool:
    """Whether this server is pointed at Datalayer rather than a Jupyter."""
    try:
        return (get_config().document_provider or "").lower() == "datalayer"
    except Exception:  # noqa: BLE001 - configuration may not be built yet
        return False


def _remove(mcp: Any, names: tuple[str, ...]) -> None:
    """Take tools off the list, tolerating ones that were never on it.

    A missing tool raises rather than passing quietly, and an upstream release
    that renames one must not stop this server from starting.
    """
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:  # pragma: no cover - defensive
        logger.warning("No tool manager; leaving the tool list alone")
        return
    for name in names:
        try:
            manager.remove_tool(name)
            logger.debug("Removed tool [%s]", name)
        except Exception:  # noqa: BLE001 - absent is the acceptable outcome
            logger.debug("Tool [%s] was not registered", name)
