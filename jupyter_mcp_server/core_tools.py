# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""This server's own tools, offered the way an extension offers tools.

Every tool in :mod:`jupyter_mcp_server.server` is registered by a decorator on
one module-level server. That works for the process that serves *that* server
and for nothing else:

* **an extension cannot narrow one.** Extending a tool is declared by name
  against a contribution, and a decorated function is not a contribution — so
  a deployment that addresses notebooks by uid rather than by path had to
  reach into the live server's tool manager, take ``use_notebook`` off and put
  a replacement on, which is a patch on somebody's internals dressed up as a
  feature;
* **a host cannot build a server that has them.** A host builds a server per
  set of toolsets, from what was contributed. Built from contributions alone,
  such a server would have every extension's tools and none of this server's
  own — the notebook tools missing from the notebook server.

So they are contributed here, by one extension that is registered like any
other. Nothing about how they are written changes: the decorators stay, the
names stay, and this reads what they registered.

@module jupyter_mcp_server.core_tools
"""

from __future__ import annotations

import logging
from typing import Any

from reactor import PluginCompatibility, PluginManifest
from reactor_mcp_server import McpExtension, ToolSpec, Toolset

logger = logging.getLogger(__name__)

#: The toolset this server's own tools belong to.
#:
#: A client that wants nothing else asks for it by name — ``/mcp?only=notebooks``
#: — and one that says nothing gets it, because a Jupyter MCP server without
#: the notebook tools is not what anybody connected for.
CORE_TOOLSET = "notebooks"


class CoreToolsExtension(McpExtension):
    """The server's own tools, as contributions.

    Registered by the extension manager itself rather than through an entry
    point: it contributes what this distribution ships, so a deployment
    cannot end up without it by not installing something.
    """

    def __init__(self) -> None:
        self._lifted: tuple[ToolSpec, ...] | None = None

    def manifest(self) -> PluginManifest:
        from jupyter_mcp_server.__version__ import __version__  # noqa: PLC0415

        return PluginManifest(
            name="jupyter-mcp-server",
            version=__version__,
            description="The notebook tools this server ships itself.",
            author="Datalayer",
            tags=["jupyter", "notebooks"],
            compatibility=PluginCompatibility(api_version="v1"),
        )

    def toolsets(self) -> tuple[Toolset, ...]:
        return (
            Toolset(
                name=CORE_TOOLSET,
                description=(
                    "Read, edit and run notebooks on a Jupyter server or a "
                    "code sandbox."
                ),
            ),
        )

    def tools(self) -> tuple[ToolSpec, ...]:
        """Every tool the server registered on itself, as a `ToolSpec`.

        Lifted once and kept. Twice would read a server that extensions have
        since registered their resolved tools on — including this
        extension's own, already narrowed by whoever narrows them — and offer
        each of those again, extended a second time.
        """
        if self._lifted is None:
            self._lifted = tuple(self._lift())
        return self._lifted

    def _lift(self) -> list[ToolSpec]:
        from jupyter_mcp_server.server import SCAFFOLD_TOOLS, mcp  # noqa: PLC0415

        manager = mcp._tool_manager
        specs: list[ToolSpec] = []
        for name in SCAFFOLD_TOOLS:
            tool: Any = manager.get_tool(name)
            if tool is None:  # pragma: no cover - a tool cannot leave the module
                logger.warning("This server no longer registers '%s'", name)
                continue
            specs.append(
                ToolSpec(
                    name=name,
                    handler=tool.fn,
                    description=tool.description or "",
                    title=tool.title or "",
                    annotations=tool.annotations,
                    toolset=CORE_TOOLSET,
                )
            )
        return specs
