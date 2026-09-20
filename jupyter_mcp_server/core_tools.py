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

The same is true of everything else the module-level server holds — its
resources, its prompt, the request handlers for `resources/subscribe`,
`logging/setLevel` and the task methods, and the management routes — but none
of that is a contribution and some of it could not be one. A built server is
*furnished* with them instead, on `on_server`, which is the hook for what a
tool list cannot express. Leaving them out is worse than losing the tools:
`initialize` would tell a client this server does not do subscriptions, and a
client that reads the capability does not then ask.

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

    def on_server(self, server: Any) -> None:
        """Furnish a built server with everything else this one registers."""
        from jupyter_mcp_server.server import mcp  # noqa: PLC0415

        if server is mcp:
            # The module server already has its own; putting them back would
            # be a no-op at best and a duplicate-registration warning at worst.
            return
        furnish(server, mcp)

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


def furnish(target: Any, source: Any) -> None:
    """Give `target` what `source` holds besides its tools.

    Resources, templates, prompts, the request handlers registered on the
    low-level server, and the management routes. Each is copied only where
    the target has nothing under that name: an extension that put its own
    `capabilities://` on the server it was handed meant that one.

    Reaching into the SDK's registries, deliberately and in one place. There
    is no public "register what that server registered", and the alternative
    — every deployment that builds its own server rediscovering which
    internals to copy — is the same reach, spread out and unversioned.

    Never raises: a server without the notebook resources still serves
    notebooks, and failing the build over the furniture would take the tools
    with it.
    """
    try:
        registry = target._resource_manager
        held = source._resource_manager
        for uri, resource in held._resources.items():
            registry._resources.setdefault(uri, resource)
        for uri, template in held._templates.items():
            registry._templates.setdefault(uri, template)
    except Exception:  # noqa: BLE001 - the SDK moved its registry
        logger.exception("The built server has none of this server's resources")

    try:
        for name, prompt in source._prompt_manager._prompts.items():
            target._prompt_manager._prompts.setdefault(name, prompt)
    except Exception:  # noqa: BLE001
        logger.exception("The built server has none of this server's prompts")

    try:
        handlers = target._lowlevel_server._request_handlers
        for method, entry in source._lowlevel_server._request_handlers.items():
            handlers.setdefault(method, entry)
    except Exception:  # noqa: BLE001
        logger.exception(
            "The built server serves none of this server's extra methods; "
            "subscriptions and tasks will be missing from what it advertises"
        )

    try:
        known = {getattr(route, "path", None) for route in target._custom_starlette_routes}
        for route in source._custom_starlette_routes:
            if getattr(route, "path", None) not in known:
                target._custom_starlette_routes.append(route)
    except Exception:  # noqa: BLE001
        logger.exception("The built server serves none of this server's own routes")
