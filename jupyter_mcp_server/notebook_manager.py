# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unified Notebook and Code Sandbox Management Module

This module provides centralized management for Jupyter notebooks and the code
sandboxes that run their cells, replacing the scattered global variable
approach with a unified architecture.

"Code sandbox" is the generic name for whatever executes code for a notebook: a
Jupyter kernel reached over HTTP/WebSocket in MCP_SERVER mode, a non-Jupyter
sandbox engine contributed by an extension, or — in JUPYTER_SERVER mode — a
plain ``{"id": kernel_id}`` handle to a kernel the local kernel manager owns.
The MCP tools keep speaking of "kernels" to their callers; internally the
generic name is used so the non-Jupyter cases are not mislabelled.
"""

from __future__ import annotations

from collections.abc import Callable
import asyncio
import logging
from types import TracebackType
from typing import Any, Dict, Optional, TYPE_CHECKING, Union

import requests

from jupyter_nbmodel_client import NbModelClient, get_notebook_websocket_url

from .config import get_config

if TYPE_CHECKING:
    from code_sandboxes import CodeSandboxClient

logger = logging.getLogger(__name__)

# Bounds NbModelClient.__aexit__ (the notebook websocket disconnect). The client's own
# teardown already bounds propagating queued changes to REQUEST_TIMEOUT (10s default),
# but a stuck cancellation of its background sender task past that point has no further
# bound of its own, so a hang there was blocking every tool call that opened this
# connection forever with no response ever reaching the MCP client (#160).
DISCONNECT_TIMEOUT = 20


def _code_sandbox_reports_alive(code_sandbox: Any) -> bool:
    """Ask the sandbox object itself whether it is alive."""
    return hasattr(code_sandbox, "is_alive") and bool(code_sandbox.is_alive())


class NotebookConnection:
    """
    Context manager for Notebook connections that handles the lifecycle
    of NbModelClient instances.

    Note: This is only used in MCP_SERVER mode with remote Jupyter servers that have RTC enabled.
    In JUPYTER_SERVER mode (local), notebook content is accessed directly via contents_manager.
    """

    def __init__(self, notebook_info: dict[str, str], is_local: bool = False):
        self.notebook_info = notebook_info
        self.is_local = is_local
        self._notebook: NbModelClient | None = None

    async def __aenter__(self) -> NbModelClient:
        """Enter context, establish notebook connection."""
        if self.is_local:
            raise ValueError(
                "NotebookConnection cannot be used in local/JUPYTER_SERVER mode. "
                "Cell operations in local mode should use contents_manager directly to read notebook JSON files."
            )

        config = get_config()
        server_url = self.notebook_info.get("server_url") or config.resolved_document_url()
        token = self.notebook_info.get("token") or config.resolved_document_token()
        path = self.notebook_info.get("path", config.document_id)

        from jupyter_mcp_server.server_context import ServerContext
        server_context = ServerContext.get_instance()
        auth_headers = server_context.document_auth_headers

        ws_url = self._get_ws_url(server_url, token, path, config, auth_headers)
        # _get_ws_url may have re-authenticated on an expired cookie; re-read the
        # (possibly rotated) cookie so the WebSocket handshake uses a fresh one
        # rather than the snapshot captured before any relogin.
        auth_headers = server_context.document_auth_headers
        websocket_headers = (
            {"Cookie": auth_headers["Cookie"]}
            if auth_headers and "Cookie" in auth_headers
            else None
        )
        self._notebook = NbModelClient(ws_url, additional_headers=websocket_headers)
        await self._notebook.__aenter__()
        return self._notebook

    def _get_ws_url(self, server_url, token, path, config, auth_headers):
        """Fetch the collaboration WebSocket URL, retrying once after a re-login
        if the session cookie has expired (HTTP 401 or 403 on the session PUT).
        """
        from jupyter_mcp_server.server_context import ServerContext

        try:
            return get_notebook_websocket_url(
                server_url=server_url,
                token=token,
                path=path,
                provider=config.document_provider,
                headers=auth_headers or None,
            )
        except requests.HTTPError as error:
            if error.response is None or error.response.status_code not in (401, 403):
                raise
            logger.warning(
                "Collaboration session request returned %s — session cookie likely "
                "expired. Re-authenticating and retrying.",
                error.response.status_code,
            )
            ServerContext.get_instance().relogin_document()
            fresh_headers = ServerContext.get_instance().document_auth_headers
            return get_notebook_websocket_url(
                server_url=server_url,
                token=token,
                path=path,
                provider=config.document_provider,
                headers=fresh_headers or None,
            )

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit context, clean up connection.

        Bounded by DISCONNECT_TIMEOUT so a stuck disconnect cannot hang the tool call
        that owns this connection forever; any exception being propagated through this
        context manager still surfaces normally either way.
        """
        if self._notebook:
            try:
                await asyncio.wait_for(
                    self._notebook.__aexit__(exc_type, exc_val, exc_tb),
                    timeout=DISCONNECT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Notebook client disconnect did not finish within %ss; "
                    "continuing without waiting for its cleanup.",
                    DISCONNECT_TIMEOUT,
                )


class NotebookManager:
    """
    Centralized manager for multiple notebooks and their code sandboxes.

    This class replaces the global code sandbox variable approach with a unified
    management system that supports both single and multiple notebook scenarios.

    Note that this state is per *process*, not per caller. A server accepting
    several users therefore shares its managed notebooks between them: one
    user's ``use_notebook`` is visible to another, and ``list_notebooks``
    reports the union rather than each caller's own.

    The credential is already per request — see
    :attr:`~jupyter_mcp_server.identity.Identity.token` — so a shared entry
    still cannot be *read* without the reader's own authority behind it. What
    is shared is the alias and its binding, which leaks the existence and path
    of a notebook rather than its contents.

    A deployment serving several users should therefore run **one process per
    user** rather than sharing one. That is the supported pattern, not a
    stopgap: a process is a boundary the operating system already enforces,
    and it covers this state along with every other piece a future change
    might cache. The hosted Datalayer gateway works exactly this way — it
    authenticates and authorizes centrally, then hands each request to that
    user's own server process.
    """

    def __init__(self):
        self._notebooks: dict[str, dict[str, Any]] = {}
        self._default_notebook_name = "default"
        self._current_notebook: str | None = None  # Currently active notebook

    def __contains__(self, name: str) -> bool:
        """Check if a notebook is managed by this instance."""
        return name in self._notebooks

    def __iter__(self):
        """Iterate over notebook name, info pairs."""
        return iter(self._notebooks.items())

    def add_notebook(
        self,
        name: str,
        code_sandbox: CodeSandboxClient | dict[str, Any],
        server_url: str | None = None,
        token: str | None = None,
        path: str | None = None,
    ) -> None:
        """
        Add a notebook to the manager.

        Args:
            name: Unique identifier for the notebook
            code_sandbox: Sandbox client instance (MCP_SERVER mode) or kernel metadata dict (JUPYTER_SERVER mode)
            server_url: Jupyter server URL (optional, uses config default). Use "local" for JUPYTER_SERVER mode.
            token: Authentication token (optional, uses config default)
            path: Notebook file path (optional, uses config default)
        """
        config = get_config()

        # Determine if this is local (JUPYTER_SERVER) mode or HTTP (MCP_SERVER) mode
        is_local_mode = server_url == "local"

        self._notebooks[name] = {
            "code_sandbox": code_sandbox,
            "is_local": is_local_mode,
            "notebook_info": {
                "server_url": server_url or config.resolved_document_url(),
                "token": token or config.resolved_document_token(),
                "path": path or config.document_id,
            },
        }

        # For backward compatibility: if this is the first notebook or it's "default",
        # set it as the current notebook
        if self._current_notebook is None or name == self._default_notebook_name:
            self._current_notebook = name
        # A bound remote notebook is watched for changes made elsewhere, for
        # as long as it is bound. Best effort: a watcher that cannot start is
        # a subscriber not told, never a `use_notebook` that failed.
        if not is_local_mode:
            try:
                from jupyter_mcp_server.watchers import watchers  # noqa: PLC0415

                watchers.watch(name, self)
            except Exception:  # noqa: BLE001
                logger.debug("Notebook [%s] could not be watched", name, exc_info=True)

    def remove_notebook(self, name: str) -> bool:
        """
        Remove a notebook from the manager.

        Args:
            name: Notebook identifier

        Returns:
            True if removed successfully, False if not found
        """
        if name in self._notebooks:
            try:
                from jupyter_mcp_server.watchers import watchers  # noqa: PLC0415

                watchers.unwatch(name)
            except Exception:  # noqa: BLE001
                pass
            try:
                notebook_data = self._notebooks[name]
                is_local = notebook_data.get("is_local", False)
                code_sandbox = notebook_data["code_sandbox"]

                # Only stop the sandbox if it's an HTTP sandbox client (MCP_SERVER
                # mode). In JUPYTER_SERVER mode it is just metadata; the kernel
                # itself is managed by the local kernel manager.
                if not is_local and code_sandbox and hasattr(code_sandbox, "stop"):
                    code_sandbox.stop()
            except Exception:
                # Ignore errors during code sandbox cleanup
                pass
            finally:
                del self._notebooks[name]

                # If we removed the current notebook, update the current pointer
                if self._current_notebook == name:
                    # Set to another notebook if available, prefer "default" for compatibility
                    if self._default_notebook_name in self._notebooks:
                        self._current_notebook = self._default_notebook_name
                    elif self._notebooks:
                        # Set to the first available notebook
                        self._current_notebook = next(iter(self._notebooks.keys()))
                    else:
                        # No notebooks left
                        self._current_notebook = None
            return True
        return False

    def get_code_sandbox(self, name: str) -> CodeSandboxClient | dict[str, Any] | None:
        """
        Get the code sandbox for a specific notebook.

        Args:
            name: Notebook identifier

        Returns:
            Sandbox client (MCP_SERVER mode) or kernel metadata dict (JUPYTER_SERVER mode), or None if not found
        """
        if name in self._notebooks:
            return self._notebooks[name]["code_sandbox"]
        return None

    def get_code_sandbox_id(self, name: str) -> str | None:
        """
        Get the code sandbox ID for a specific notebook.

        The id is a Jupyter kernel id whenever the sandbox is Jupyter-backed,
        which is what the `kernel_id` tool parameters name.

        Args:
            name: Notebook identifier

        Returns:
            Code sandbox ID string or None if not found
        """
        if name in self._notebooks:
            code_sandbox = self._notebooks[name]["code_sandbox"]
            # Handle both sandbox client objects and kernel metadata dicts
            if isinstance(code_sandbox, dict):
                return code_sandbox.get("id")
            elif hasattr(code_sandbox, "id"):
                return code_sandbox.id
        return None

    def get_notebook_path(self, name: str) -> str | None:
        """
        Get the path of a notebook.

        Args:
            name: Notebook identifier

        Returns:
            Notebook path or None if not found
        """
        if name in self._notebooks:
            return self._notebooks[name]["notebook_info"].get("path")
        return None

    def is_local_notebook(self, name: str) -> bool:
        """
        Check if a notebook is using local (JUPYTER_SERVER) mode.

        Args:
            name: Notebook identifier

        Returns:
            True if local mode, False otherwise
        """
        if name in self._notebooks:
            return self._notebooks[name].get("is_local", False)
        return False

    def get_notebook_connection(self, name: str) -> NotebookConnection:
        """
        Get a context manager for notebook connection.

        Args:
            name: Notebook identifier

        Returns:
            NotebookConnection context manager

        Raises:
            ValueError: If notebook doesn't exist
        """
        if name not in self._notebooks:
            raise ValueError(f"Notebook '{name}' does not exist in manager")

        return NotebookConnection(self._notebooks[name]["notebook_info"])

    def restart_notebook(self, name: str) -> bool:
        """
        Restart the code sandbox for a specific notebook.

        Args:
            name: Notebook identifier

        Returns:
            True if restarted successfully, False otherwise
        """
        if name in self._notebooks:
            try:
                code_sandbox = self._notebooks[name]["code_sandbox"]
                if code_sandbox and hasattr(code_sandbox, "restart"):
                    code_sandbox.restart()
                return True
            except Exception:
                return False
        return False

    def is_empty(self) -> bool:
        """Check if the manager is empty (no notebooks)."""
        return len(self._notebooks) == 0

    def ensure_code_sandbox_alive(
        self,
        name: str,
        code_sandbox_factory: Callable[[], CodeSandboxClient],
        is_alive_fn: Callable[[Any], bool] | None = None,
    ) -> CodeSandboxClient:
        """
        Ensure a code sandbox is alive, create if necessary.

        Args:
            name: Notebook identifier
            code_sandbox_factory: Function to create a new code sandbox
            is_alive_fn: Liveness test for the tracked sandbox. Defaults to the
                sandbox's own `is_alive()`, which reports whether this process
                started it and not whether it still exists where it runs.

        Returns:
            The alive code sandbox instance
        """
        code_sandbox = self.get_code_sandbox(name)
        if is_alive_fn is None:
            is_alive_fn = _code_sandbox_reports_alive
        if code_sandbox is None or not is_alive_fn(code_sandbox):
            new_code_sandbox = code_sandbox_factory()
            if name in self._notebooks:
                # Swap only the sandbox: a restart replaces the sandbox, never the
                # notebook the entry points at. Re-adding via add_notebook without
                # the original server_url/token/path would reset notebook_info to
                # the config defaults (see add_notebook) and silently rebind this
                # notebook to the default document.
                self._notebooks[name]["code_sandbox"] = new_code_sandbox
            else:
                self.add_notebook(name, new_code_sandbox)
            return new_code_sandbox
        return code_sandbox

    def set_current_notebook(self, name: str) -> bool:
        """
        Set the currently active notebook.

        Args:
            name: Notebook identifier

        Returns:
            True if set successfully, False if notebook doesn't exist
        """
        if name in self._notebooks:
            self._current_notebook = name
            return True
        return False

    def get_current_notebook(self) -> str | None:
        """
        Get the name of the currently active notebook.

        Returns:
            Current notebook name or None if no active notebook
        """
        return self._current_notebook

    def get_current_connection(self) -> NotebookConnection:
        """
        Get the connection for the currently active notebook.
        For backward compatibility, defaults to "default" if no current notebook is set.

        Returns:
            NotebookConnection context manager for the current notebook

        Raises:
            ValueError: If no notebooks exist and no default config is available
        """
        current = self._current_notebook or self._default_notebook_name

        # For backward compatibility: if the requested notebook doesn't exist but we're
        # asking for default, create a connection using the default config
        if current not in self._notebooks and current == self._default_notebook_name:
            # Return a connection using default configuration
            config = get_config()
            return NotebookConnection(
                {
                    "server_url": config.resolved_document_url(),
                    "token": config.resolved_document_token(),
                    "path": config.document_id,
                }
            )

        return self.get_notebook_connection(current)

    def get_current_notebook_path(self) -> str | None:
        """
        Get the file path of the currently active notebook.

        Returns:
            Notebook file path or None if no active notebook
        """
        current = self._current_notebook or self._default_notebook_name
        if current in self._notebooks:
            return self._notebooks[current]["notebook_info"].get("path")
        return None

    def list_all_notebooks(self, kernel_manager: Any | None = None) -> dict[str, dict[str, Any]]:
        """
        Get information about all managed notebooks.

        Args:
            kernel_manager: Jupyter server's kernel manager (JUPYTER_SERVER mode only).
                In that mode the code sandbox is a plain dict ({"id": kernel_id}),
                not a client, so liveness has to be checked against the real kernel
                manager instead of via `is_alive()`.

        Returns:
            Dictionary with notebook names as keys and their info as values.
            `kernel_status` keeps its name because `list_notebooks` reports it
            to callers under the `Kernel_Status` column.
        """
        result = {}
        for name, notebook_data in self._notebooks.items():
            code_sandbox = notebook_data["code_sandbox"]
            notebook_info = notebook_data["notebook_info"]

            kernel_status = "unknown"
            if code_sandbox:
                try:
                    if hasattr(code_sandbox, "is_alive"):
                        kernel_status = "alive" if code_sandbox.is_alive() else "dead"
                    elif isinstance(code_sandbox, dict) and kernel_manager is not None:
                        kernel_id = code_sandbox.get("id")
                        kernel_status = (
                            "alive" if kernel_id and kernel_id in kernel_manager else "dead"
                        )
                except Exception:
                    kernel_status = "error"
            else:
                kernel_status = "not_initialized"

            result[name] = {
                "path": notebook_info.get("path", ""),
                "kernel_status": kernel_status,
                "is_current": name == self._current_notebook,
            }

        return result
