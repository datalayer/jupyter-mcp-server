# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Extension mechanism for Jupyter MCP Server.

Extensions are standalone Python packages that plug additional capabilities
into the server — extra MCP tools, alternative kernel factories, or custom
``execute_code`` routing — without the core needing to know about them.

Discovery, registration and lifecycle are :mod:`reactor_mcp_server`'s, the
extensible MCP server foundation built on :mod:`reactor`. What that gives this
server, and what this module used to do by hand:

* **a tool is a contribution.** An extension declares its tools with
  :func:`~reactor_mcp_server.tool` and the host collects them, rather than
  being handed the server and registering functions on it;
* **a tool can be extended.** An extension narrows, wraps or re-describes a
  tool *another* extension declared, by name and in a declared order. Before
  this the only lever was to register a tool of the same name and be loaded
  second — the SDK keeps the first registration — so which extension won
  depended on how the entry point names happened to sort;
* **toolsets.** Tools belong to a named set, and a deployment that serves this
  through ``reactor_mcp_server``'s application lets a client pick them in the
  URL (``/mcp?sandboxes``). An extension whose toolset nobody asked for is not
  registered at all.

What stays here is what is *Jupyter's*: making a code sandbox, intercepting
``execute_code``, and declaring capabilities.

Each extension:

* is published on the ``reactor.mcp.extensions`` entry-point group,
* subclasses :class:`JupyterMCPExtension`,
* describes itself with a :class:`~reactor.PluginManifest`.

The first bundled extension is ``jupyter_mcp_sandboxes`` (see
``extensions/sandboxes``), which contributes the sandbox lifecycle tools and
sandbox-backed execution.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from reactor_mcp_server import (
    ENTRY_POINT_GROUP,
    McpExtension,
    McpHost,
    ToolSpec,
    load_extensions,
)

logger = logging.getLogger(__name__)

#: Entry-point group used to discover installed extensions.
#:
#: The foundation's group, not one of this server's own: an extension written
#: for any ``reactor_mcp_server`` host works here, and one written for this
#: server works in any other.
EXTENSION_ENTRY_POINT_GROUP = ENTRY_POINT_GROUP

#: Comma-separated entry-point names to load, to the exclusion of everything
#: else on the group. Unset or empty means every installed extension, which is
#: what a server should normally do.
EXTENSIONS_ENV = "JUPYTER_MCP_EXTENSIONS"


class JupyterMCPExtension(McpExtension):
    """Base class for Jupyter MCP Server extensions.

    Everything :class:`~reactor_mcp_server.McpExtension` offers — tools,
    extensions of other extensions' tools, toolsets, resources, prompts — plus
    the three hooks that are about *this* server rather than about MCP.

    Subclasses override what they need; every hook has a safe default.
    """

    def create_code_sandbox(self, config: Any, logger: logging.Logger) -> Any | None:
        """Optionally build a kernel for the current configuration.

        Return a kernel-like object (exposing the ``JupyterKernelClient``
        interface) to take over kernel creation, or ``None`` to let the core /
        other extensions handle it.
        """
        return None

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> list[Any] | None:
        """Optionally handle an ``execute_code`` call.

        Return a list of outputs to short-circuit execution, or ``None`` to let
        the core kernel-backed path run.
        """
        return None

    def capabilities(self) -> list[Any]:
        """Declare what this extension lets the server do.

        Return :class:`jupyter_mcp_server.capabilities.Capability` values. An
        extension that genuinely adds an ability says so here rather than the
        core guessing from what is installed — and a client then sees the same
        named thing whether it came from the core, a flag or a plugin.
        """
        return []


class ExtensionManager:
    """Discover, register and coordinate :class:`JupyterMCPExtension` plugins.

    A thin layer over :class:`reactor_mcp_server.McpHost`, which owns the
    reactor platform: manifests, compatibility, activation events, enablement
    and disposal are all its. What is added here is the three Jupyter hooks,
    which are dispatched to the extensions directly.
    """

    def __init__(self, host: McpHost | None = None) -> None:
        self._host = host or McpHost(name="jupyter-mcp-server")
        self._extensions: dict[str, McpExtension] = {}
        self._started = False
        self._discovered = False
        self._tools_registered = False
        self._capabilities_collected: set[str] = set()

    @property
    def host(self) -> McpHost:
        """The MCP host. What a caller reaches for to build a server."""
        return self._host

    def register(self, extension: McpExtension) -> None:
        """Register one extension with the platform.

        Any :class:`~reactor_mcp_server.McpExtension` is welcome, not only a
        :class:`JupyterMCPExtension`: an extension written for another
        ``reactor_mcp_server`` host contributes tools that are valid here, and
        refusing it would make the entry-point group this server reads a
        different group in all but name. The three Jupyter hooks are asked for
        by name below, so an extension that has none simply has none.
        """
        if not isinstance(extension, McpExtension):
            raise TypeError(
                f"{extension!r} is not an McpExtension; an extension declares "
                "its tools so a host can collect them"
            )
        name = self._host.add(extension)
        self._extensions[name] = extension
        self._tools_registered = False

    def get(self, name: str) -> McpExtension | None:
        """One registered extension by name, for extensions built on others.

        ``None`` for a name that is not registered, because "the extension you
        build on is not installed" is an ordinary configuration, not an error:
        the caller degrades — leaving its tool off the list — rather than
        failing the whole server's startup.
        """
        return self._extensions.get(name)

    def discover(self) -> None:
        """Discover extensions published on the entry-point group.

        ``JUPYTER_MCP_EXTENSIONS`` narrows discovery to the entry-point names
        it lists. What it is for: the tool surface a client sees is whatever
        happens to be installed beside the server, so an environment carrying
        an extra extension answers differently from a bare one — which is a
        problem when the answer has to be reproducible, as it does for the
        generated reference in ``docs/sourcey``. Unset, every installed
        extension loads, which is what a server should normally do.

        Load order no longer decides anything: an extension that acts on
        another's tool says so with
        :meth:`~reactor_mcp_server.McpExtension.tool_extensions` and is applied
        in a declared order whichever way the names sort.
        """
        if self._discovered:
            return
        self._discovered = True
        # This server's own tools first, so an extension that narrows one is
        # narrowing something the host already knows about. Registered here
        # rather than published on the entry-point group: it contributes what
        # this distribution ships, and a distribution cannot be missing
        # itself.
        from jupyter_mcp_server.core_tools import CoreToolsExtension  # noqa: PLC0415

        try:
            self.register(CoreToolsExtension())
        except Exception:  # pragma: no cover - defensive
            logger.exception("This server could not offer its own tools")
        allowed = [
            part.strip()
            for part in (os.environ.get(EXTENSIONS_ENV) or "").split(",")
            if part.strip()
        ]
        # `load_extensions` reads the entry points sorted( ) by name, so two
        # runs on two machines build the same server. Not for precedence any
        # more — extending a tool is declared, not raced for.
        for extension in load_extensions(allowed or None):
            try:
                self.register(extension)
            except Exception:
                logger.exception("Failed to register extension %r", extension)

    def tools(self) -> Sequence[ToolSpec]:
        """Every tool the registered extensions offer, extensions applied."""
        self.discover()
        return self._host.offered_tools()

    def collect_capabilities(self, registry: Any) -> None:
        """Ask every extension what it adds, and record it.

        One extension raising must not cost the others their declarations, so
        each is asked on its own: a plugin with a broken `capabilities()`
        loses only its own, and says so in the log.

        Each extension is asked once. `registry.declare` applies the
        extension's own `enabled` value, so asking a second time re-imposes it
        over whatever the operator has set since, and this runs on a resource
        read: any client could turn a capability back on by looking at it.
        """
        self.discover()
        for name, extension in self._extensions.items():
            if name in self._capabilities_collected:
                continue
            self._capabilities_collected.add(name)
            declare = getattr(extension, "capabilities", None)
            if declare is None:
                continue
            try:
                declared = declare() or []
            except Exception:
                logger.exception("Extension %s could not declare its capabilities", name)
                continue
            for capability in declared:
                try:
                    registry.declare(capability)
                except Exception:
                    logger.exception(
                        "Extension %s declared something that is not a capability: %r",
                        name, capability,
                    )

    def register_tools(self, mcp: Any, *, once: bool = False) -> None:
        """Put every extension's tools on this server.

        The tools are read from the contributions with every extension of them
        already applied, so what lands on the server is the resolved tool — not
        one tool per extension of it, and not whichever one registered first.

        Args:
            once: Do nothing if tools have already been registered on this
                manager. What makes it safe to call this from every entry
                point — the CLI after it has configured the server, the
                Jupyter Server extension, a test — without any of them having
                to know whether another got there first.
        """
        if once and self._tools_registered:
            return
        self.discover()
        self._tools_registered = True
        for spec in self._host.offered_tools():
            try:
                # Off first, on second. The SDK keeps the tool that was
                # registered first and warns, so a name already on the server
                # — every one of this server's own, and any tool an extension
                # narrowed — would keep the unextended version and say so in
                # a log nobody reads. What the host resolved is what a client
                # should get.
                remove = getattr(mcp, "remove_tool", None)
                if callable(remove):
                    try:
                        remove(spec.name)
                    except Exception:  # noqa: BLE001 - it was not there
                        pass
                mcp.add_tool(
                    spec.handler,
                    name=spec.name,
                    title=spec.title or None,
                    description=spec.documentation or None,
                    annotations=spec.annotations,
                )
            except Exception:
                logger.exception("Tool '%s' could not be registered", spec.name)
        # Started here, which is what fires `on_start`: an extension with work
        # to do once — registering a hook, opening a client — does it where
        # its tools have just been put on a server, and every entry point
        # reaches this. Idempotent, so calling it again starts nothing again.
        self.start()
        # What an extension does to the server itself, once its tools are on
        # it: take one off, add a resource, read what else was offered. A
        # host building a server per toolset does this too, and an entry
        # point that serves this one server would otherwise be the only place
        # where it silently did not happen.
        for name, extension in self._extensions.items():
            act = getattr(extension, "on_server", None)
            if act is None:
                continue
            try:
                act(mcp)
            except Exception:
                logger.exception("Extension '%s' failed acting on the server", name)

    def start(self) -> None:
        """Start the platform and notify extensions."""
        self.discover()
        if self._started:
            return
        self._started = True
        try:
            self._host.start()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Reactor platform failed to start")
        for name, extension in self._extensions.items():
            try:
                extension.on_start()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Extension '%s' failed on start", name)

    def stop(self) -> None:
        """Stop the platform and notify extensions."""
        for name, extension in self._extensions.items():
            try:
                extension.on_stop()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Extension '%s' failed on stop", name)
        try:
            self._host.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Reactor platform failed to stop")
        self._started = False

    def create_code_sandbox(self, config: Any, log: logging.Logger) -> Any | None:
        """Ask extensions to build a code sandbox; return the first non-None result."""
        self.discover()
        for name, extension in self._extensions.items():
            make = getattr(extension, "create_code_sandbox", None)
            if make is None:
                continue
            code_sandbox = make(config, log)
            if code_sandbox is not None:
                # The caller's logger, as for the warning above: one method,
                # one logging configuration.
                log.debug("Extension '%s' provided a code sandbox", name)
                return code_sandbox
        return None

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> list[Any] | None:
        """Give extensions a chance to handle ``execute_code``."""
        self.discover()
        for extension in self._extensions.values():
            intercept = getattr(extension, "intercept_execute_code", None)
            if intercept is None:
                continue
            result = await intercept(code, timeout)
            if result is not None:
                return result
        return None


_EXTENSION_MANAGER: ExtensionManager | None = None


def get_extension_manager() -> ExtensionManager:
    """Return the process-wide :class:`ExtensionManager` singleton."""
    global _EXTENSION_MANAGER
    if _EXTENSION_MANAGER is None:
        _EXTENSION_MANAGER = ExtensionManager()
    return _EXTENSION_MANAGER
