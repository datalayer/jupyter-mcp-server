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

The first bundled extension is ``jupyter_mcp_sandboxes`` (see ``ext/sandboxes``),
which contributes the sandbox lifecycle tools and sandbox-backed execution.
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from reactor import PluginManifest

logger = logging.getLogger(__name__)

#: Entry-point group used to discover installed extensions.
ENTRY_POINT_GROUP = "jupyter_mcp_server.extensions"


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
        """Register MCP tools on the given ``FastMCP`` instance.

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

    def discover(self) -> None:
        """Discover extensions published on the entry-point group."""
        if self._discovered:
            return
        self._discovered = True
        try:
            entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - Python < 3.10 compatibility
            entry_points = metadata.entry_points().get(ENTRY_POINT_GROUP, [])
        for entry_point in entry_points:
            try:
                factory = entry_point.load()
                extension = factory() if callable(factory) else factory
                self.register(extension)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to load Jupyter MCP extension '%s'", entry_point.name
                )

    def register_tools(self, mcp: Any) -> None:
        """Discover extensions (if needed) and register all their tools."""
        self.discover()
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
