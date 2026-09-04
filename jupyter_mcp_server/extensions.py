# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Extension mechanism for Jupyter MCP Server.

Extensions are standalone Python packages that plug additional capabilities
into the server — extra MCP tools, alternative kernel factories, or custom
``execute_code`` routing — without the core needing to know about them.

Discovery and lifecycle are powered by :mod:`reactor`, a small
``pluggy``-based plugin platform. Each extension:

* is published on the ``jupyter_mcp_server.extensions`` entry-point group,
* subclasses :class:`JupyterMCPExtension`,
* is registered with a :class:`~reactor.PluginManifest` so the reactor
  platform can track versions, compatibility and lifecycle.

The first bundled extension is ``jupyter_mcp_sandboxes`` (see ``extensions/sandboxes``),
which contributes the sandbox lifecycle tools and sandbox-backed execution.
"""

from __future__ import annotations

import logging
import os
from importlib import metadata
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from reactor import PluginManifest

logger = logging.getLogger(__name__)

#: Entry-point group used to discover installed extensions.
ENTRY_POINT_GROUP = "jupyter_mcp_server.extensions"

#: Comma-separated entry-point names to load, to the exclusion of everything
#: else on the group. Unset or empty means every installed extension, which is
#: what a server should normally do.
EXTENSIONS_ENV = "JUPYTER_MCP_EXTENSIONS"


class JupyterMCPExtension:
    """Base class for Jupyter MCP Server extensions.

    Subclasses override the hooks they care about. Every hook has a safe default
    so an extension only implements what it needs.
    """

    def manifest(self) -> "PluginManifest":
        """Return the reactor manifest describing this extension.

        Subclasses must override this to provide at least a name and version.
        """
        raise NotImplementedError

    def register_tools(self, mcp: Any) -> None:
        """Register MCP tools on the given ``MCPServer`` instance.

        Called once during server startup, after the core tools are registered.
        """

    def create_code_sandbox(self, config: Any, logger: logging.Logger) -> Optional[Any]:
        """Optionally build a kernel for the current configuration.

        Return a kernel-like object (exposing the ``JupyterKernelClient`` interface) to
        take over kernel creation, or ``None`` to let the core / other extensions
        handle it.
        """
        return None

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> Optional[list[Any]]:
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

    def on_start(self) -> None:
        """Called when the extension platform starts."""

    def on_stop(self) -> None:
        """Called when the server shuts down. Release resources here."""


class ExtensionManager:
    """Discover, register and coordinate :class:`JupyterMCPExtension` plugins.

    Uses a :class:`reactor.PluginPlatform` as the underlying registry
    for manifests, version compatibility and lifecycle hooks, while dispatching
    the MCP-specific hooks (tool registration, kernel creation, execute_code
    interception) to the registered extensions directly.
    """

    def __init__(self) -> None:
        self._extensions: dict[str, JupyterMCPExtension] = {}
        self._platform: Any = None
        self._started = False
        self._discovered = False
        self._tools_registered = False

    def _ensure_platform(self) -> Any:
        if self._platform is None:
            try:
                from reactor import PluginPlatform
            except ImportError:  # pragma: no cover - optional dependency
                logger.warning(
                    "reactor is not installed; extension mechanism disabled."
                )
                return None
            self._platform = PluginPlatform()
        return self._platform

    @property
    def platform(self) -> Any:
        """The underlying reactor plugin platform (or ``None`` if unavailable)."""
        return self._ensure_platform()

    def register(self, extension: JupyterMCPExtension) -> None:
        """Register a single extension with the reactor platform."""
        manifest = extension.manifest()
        platform = self._ensure_platform()
        if platform is not None:
            platform.register_plugin(manifest, extension)
        self._extensions[manifest.name] = extension
        logger.info("Registered Jupyter MCP extension: %s", manifest.name)

    def get(self, name: str) -> Optional[JupyterMCPExtension]:
        """The registered extension published under this manifest name.

        Extensions are meant to compose — that is what registering them in
        name order is *for*: one extension narrowing or extending a tool an
        earlier one put on the server. Composing needs a way to reach the
        extension being built on, and until now the only route was
        ``manager._extensions``, another object's private dict. A downstream
        extension reaching in that way keeps working right up to the day this
        class stores its extensions differently, and then breaks with an
        ``AttributeError`` in somebody else's package.

        ``None`` for a name that is not registered, because "the extension you
        build on is not installed" is an ordinary configuration, not an error:
        the caller degrades — leaving its tool off the list — rather than
        failing the whole server's startup.
        """
        return self._extensions.get(name)

    def discover(self) -> None:
        """Discover extensions published on the entry-point group.

        Registered in **name order**. `importlib.metadata` returns entry
        points in whatever order the installation happens to produce, which
        varies between machines and between a wheel and an editable install —
        so two extensions that interact would work on one and not the other,
        and nothing would say why.

        Order matters because registration is not independent: an extension
        may *replace* a tool another registered, and the SDK keeps the
        original when a name is registered twice. Sorting by name gives such
        an extension something it can rely on.

        ``JUPYTER_MCP_EXTENSIONS`` narrows discovery to the entry-point names
        it lists. What it is for: the tool surface a client sees is whatever
        happens to be installed beside the server, so an environment carrying
        an extra extension answers differently from a bare one — which is a
        problem when the answer has to be reproducible, as it does for the
        generated reference in ``docs/sourcey``. Unset, every installed
        extension loads, which is what a server should normally do.
        """
        if self._discovered:
            return
        self._discovered = True
        allowed = {
            part.strip()
            for part in (os.environ.get(EXTENSIONS_ENV) or "").split(",")
            if part.strip()
        }
        try:
            entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - Python < 3.10 compatibility
            entry_points = metadata.entry_points().get(ENTRY_POINT_GROUP, [])
        for entry_point in sorted(entry_points, key=lambda point: point.name):
            if allowed and entry_point.name not in allowed:
                logger.info(
                    "Skipping Jupyter MCP extension '%s': %s selects %s",
                    entry_point.name, EXTENSIONS_ENV, ", ".join(sorted(allowed)),
                )
                continue
            try:
                factory = entry_point.load()
                extension = factory() if callable(factory) else factory
                self.register(extension)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to load Jupyter MCP extension '%s'", entry_point.name
                )

    def collect_capabilities(self, registry: Any) -> None:
        """Ask every extension what it adds, and record it.

        One extension raising must not cost the others their declarations, so
        each is asked on its own: a plugin with a broken `capabilities()`
        loses only its own, and says so in the log.
        """
        for name, extension in self._extensions.items():
            try:
                declared = extension.capabilities() or []
            except Exception:  # noqa: BLE001 - one plugin never breaks the rest
                logger.exception("Extension %s could not declare its capabilities", name)
                continue
            for capability in declared:
                try:
                    registry.declare(capability)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Extension %s declared something that is not a capability: %r",
                        name, capability,
                    )

    def register_tools(self, mcp: Any, *, once: bool = False) -> None:
        """Discover extensions (if needed) and register all their tools.

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
        for name, extension in self._extensions.items():
            try:
                extension.register_tools(mcp)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Extension '%s' failed to register tools", name)

    def start(self) -> None:
        """Start the platform and notify extensions."""
        self.discover()
        if self._started:
            return
        self._started = True
        platform = self._ensure_platform()
        if platform is not None:
            try:
                platform.start()
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
        platform = self._platform
        if platform is not None:
            try:
                platform.stop()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Reactor platform failed to stop")
        self._started = False

    def create_code_sandbox(self, config: Any, log: logging.Logger) -> Optional[Any]:
        """Ask extensions to build a code sandbox; return the first non-None result."""
        self.discover()
        for name, extension in self._extensions.items():
            if hasattr(extension, "create_kernel") and (
                type(extension).create_code_sandbox
                is JupyterMCPExtension.create_code_sandbox
            ):
                # An extension built before the factory hook was renamed: its
                # `create_kernel` would never be called and execution would
                # silently fall back to a Jupyter kernel that is not there.
                # Say it, loudly — this is a version mismatch, not a choice.
                log.warning(
                    "Extension '%s' defines the legacy 'create_kernel' hook but "
                    "not 'create_code_sandbox'; it is outdated for this "
                    "jupyter-mcp-server and its sandboxes will not be used. "
                    "Upgrade the extension package.",
                    name,
                )
            code_sandbox = extension.create_code_sandbox(config, log)
            if code_sandbox is not None:
                # The caller's logger, as for the warning above: one method,
                # one logging configuration.
                log.debug("Extension '%s' provided a code sandbox", name)
                return code_sandbox
        return None

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> Optional[list[Any]]:
        """Give extensions a chance to handle ``execute_code``."""
        for extension in self._extensions.values():
            result = await extension.intercept_execute_code(code, timeout)
            if result is not None:
                return result
        return None


_EXTENSION_MANAGER: Optional[ExtensionManager] = None


def get_extension_manager() -> ExtensionManager:
    """Return the process-wide :class:`ExtensionManager` singleton."""
    global _EXTENSION_MANAGER
    if _EXTENSION_MANAGER is None:
        _EXTENSION_MANAGER = ExtensionManager()
    return _EXTENSION_MANAGER
