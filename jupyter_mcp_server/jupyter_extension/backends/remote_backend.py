# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Remote Backend Implementation.

Serves the operations of :class:`Backend` against a Jupyter server reached over
HTTP and websocket, as opposed to :class:`LocalBackend`, which drives the
managers of a server this process is embedded in.

Two clients, because the two halves can address different servers: documents
come from ``document_url`` over the collaboration protocol, and execution from
``code_sandbox_url``. A deployment that runs both on one server simply passes
the same URL twice.

Cell operations go through the collaborative document rather than the contents
API. Reading a notebook file would see it as it was last saved, which is not
what anyone editing it is looking at, and writing one would overwrite whatever
another client had in flight.
"""

import asyncio
from typing import Any, Literal

from jupyter_nbmodel_client import NbModelClient, get_notebook_websocket_url
from jupyter_server_client import JupyterServerClient
from mcp.types import ImageContent

from jupyter_mcp_server.jupyter_extension.backends.base import Backend


class RemoteBackend(Backend):
    """Backend that connects to remote Jupyter servers over HTTP and websocket."""

    def __init__(
        self, document_url: str, document_token: str, code_sandbox_url: str, code_sandbox_token: str
    ):
        """
        Initialize remote backend.

        Args:
            document_url: URL of Jupyter server for document operations
            document_token: Authentication token for document server
            code_sandbox_url: URL of Jupyter server for code sandbox operations
            code_sandbox_token: Authentication token for code sandbox server
        """
        self.document_url = document_url
        self.document_token = document_token
        self.code_sandbox_url = code_sandbox_url
        self.code_sandbox_token = code_sandbox_token
        self._documents_client: JupyterServerClient | None = None
        self._sandbox_client: JupyterServerClient | None = None

    # -- clients ------------------------------------------------------------

    def _documents(self) -> JupyterServerClient:
        """The server holding the notebook files.

        Built once and kept: the client owns an HTTP session, and making a new
        one per call re-does the connection and its authentication on every
        listing — of which `list_notebooks` alone performs one per directory.
        """
        if self._documents_client is None:
            self._documents_client = JupyterServerClient(
                base_url=self.document_url, token=self.document_token
            )
        return self._documents_client

    def _sandbox(self) -> JupyterServerClient:
        """The server running the code. Kept for the same reason."""
        if self._sandbox_client is None:
            self._sandbox_client = JupyterServerClient(
                base_url=self.code_sandbox_url, token=self.code_sandbox_token
            )
        return self._sandbox_client

    @staticmethod
    async def _off_loop(call, *args):
        """Run a blocking client call without stalling the event loop.

        `JupyterServerClient` is synchronous, and these methods are awaited by
        a server handling other requests at the same time. Calling it directly
        would hold the loop for the length of a network round trip — and
        `list_notebooks` makes one per directory it walks.
        """
        return await asyncio.to_thread(call, *args)

    def _document(self, path: str) -> NbModelClient:
        """A live connection to one collaborative notebook."""
        return NbModelClient(
            get_notebook_websocket_url(
                server_url=self.document_url,
                path=path,
                token=self.document_token,
            )
        )

    # Notebook operations

    async def get_notebook_content(self, path: str) -> dict[str, Any]:
        """Get notebook content via remote API."""
        return await self._off_loop(self._documents().contents.get, path)

    async def list_notebooks(self, path: str = "") -> list[str]:
        """List notebooks via remote API, recursively from `path`."""
        found: list[str] = []
        pending = [path]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            listing = await self._off_loop(
                self._documents().contents.list_directory, current
            )
            for entry in listing:
                name = getattr(entry, "path", None) or getattr(entry, "name", "")
                kind = getattr(entry, "type", "")
                if kind == "directory":
                    pending.append(name)
                elif name.endswith(".ipynb"):
                    found.append(name)
        return sorted(found)

    async def notebook_exists(self, path: str) -> bool:
        """Check if notebook exists via remote API."""
        try:
            await self._off_loop(self._documents().contents.get, path)
        except Exception:  # noqa: BLE001 - any failure to fetch means "not there"
            return False
        return True

    async def create_notebook(self, path: str) -> dict[str, Any]:
        """Create notebook via remote API."""
        return await self._off_loop(self._documents().contents.create_notebook, path)

    # Cell operations

    async def read_cells(
        self, path: str, start_index: int | None = None, end_index: int | None = None
    ) -> list[dict[str, Any]]:
        """Read cells from the collaborative document."""
        async with self._document(path) as notebook:
            cells = [dict(cell) for cell in notebook[:]]
        return cells[start_index:end_index]

    async def append_cell(
        self, path: str, cell_type: Literal["code", "markdown"], source: str | list[str]
    ) -> int:
        """Append a cell, returning its index."""
        async with self._document(path) as notebook:
            if cell_type == "code":
                notebook.add_code_cell(_text(source))
            else:
                notebook.add_markdown_cell(_text(source))
            return len(notebook) - 1

    async def insert_cell(
        self,
        path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        source: str | list[str],
    ) -> int:
        """Insert a cell at `cell_index`, returning that index."""
        async with self._document(path) as notebook:
            notebook.insert_cell(cell_index, _text(source), cell_type)
            return cell_index

    async def delete_cell(self, path: str, cell_index: int) -> None:
        """Delete a cell from the collaborative document."""
        async with self._document(path) as notebook:
            del notebook[cell_index]

    async def overwrite_cell(
        self, path: str, cell_index: int, new_source: str | list[str]
    ) -> tuple[str, str]:
        """Replace a cell's source, returning what it was and what it became."""
        replacement = _text(new_source)
        async with self._document(path) as notebook:
            before = str(notebook[cell_index].get("source", ""))
            notebook.set_cell_source(cell_index, replacement)
        return before, replacement

    # Kernel operations

    async def get_or_create_kernel(self, path: str, kernel_id: str | None = None) -> str:
        """Get or create kernel via kernel_client."""
        # Left to the sandbox layer, which owns starting execution backends and
        # is the only place that knows which variant a deployment runs.
        raise NotImplementedError(
            "Starting execution is the sandbox layer's, not the backend's."
        )

    async def execute_cell(
        self, path: str, cell_index: int, kernel_id: str, timeout_seconds: int = 300
    ) -> list[str | ImageContent]:
        """Execute cell via kernel_client."""
        raise NotImplementedError(
            "Executing is the sandbox layer's, not the backend's."
        )

    async def interrupt_kernel(self, kernel_id: str) -> None:
        """Interrupt kernel via kernel_client."""
        raise NotImplementedError(
            "Interrupting is the sandbox layer's, not the backend's."
        )

    async def restart_kernel(self, kernel_id: str) -> None:
        """Restart kernel via kernel_client."""
        raise NotImplementedError(
            "Restarting is the sandbox layer's, not the backend's."
        )

    async def shutdown_kernel(self, kernel_id: str) -> None:
        """Shutdown kernel via kernel_client."""
        raise NotImplementedError(
            "Shutting down is the sandbox layer's, not the backend's."
        )

    async def list_kernels(self) -> list[dict[str, Any]]:
        """List the kernels of the execution server."""
        return [
            {
                "id": kernel.id,
                "name": getattr(kernel, "name", ""),
                "last_activity": getattr(kernel, "last_activity", None),
                "execution_state": getattr(kernel, "execution_state", None),
                "connections": getattr(kernel, "connections", 0),
            }
            for kernel in await self._off_loop(self._sandbox().kernels.list_kernels)
        ]

    async def kernel_exists(self, kernel_id: str) -> bool:
        """Check if a kernel exists on the execution server."""
        try:
            fetched = await self._off_loop(
                self._sandbox().kernels.get_kernel, kernel_id
            )
            return fetched is not None
        except Exception:  # noqa: BLE001 - any failure to fetch means "not there"
            return False


def _text(source: str | list[str]) -> str:
    """Cell source as one string, however the caller expressed it."""
    return source if isinstance(source, str) else "".join(source)
