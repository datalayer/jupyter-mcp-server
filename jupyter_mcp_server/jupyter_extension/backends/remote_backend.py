# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Remote Backend Implementation

Note: This is a placeholder.
"""

from typing import Any, Literal

from mcp.types import ImageContent

from jupyter_mcp_server.jupyter_extension.backends.base import Backend

class RemoteBackend(Backend):
    """
    Backend that connects to remote Jupyter servers using HTTP/WebSocket APIs.

    Uses:
    - jupyter_nbmodel_client.NbModelClient for notebook operations
    - A kernel client adapter for kernel operations
    - jupyter_server_client.JupyterServerClient for server operations
    """

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

    # Notebook operations

    async def get_notebook_content(self, path: str) -> dict[str, Any]:
        """Get notebook content via remote API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")

    async def list_notebooks(self, path: str = "") -> list[str]:
        """List notebooks via remote API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")

    async def notebook_exists(self, path: str) -> bool:
        """Check if notebook exists via remote API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")

    async def create_notebook(self, path: str) -> dict[str, Any]:
        """Create notebook via remote API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")

    # Cell operations

    async def read_cells(
        self, path: str, start_index: int | None = None, end_index: int | None = None
    ) -> list[dict[str, Any]]:
        """Read cells via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")

    async def append_cell(
        self, path: str, cell_type: Literal["code", "markdown"], source: str | list[str]
    ) -> int:
        """Append cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")

    async def insert_cell(
        self,
        path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        source: str | list[str],
    ) -> int:
        """Insert cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")

    async def delete_cell(self, path: str, cell_index: int) -> None:
        """Delete cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")

    async def overwrite_cell(
        self, path: str, cell_index: int, new_source: str | list[str]
    ) -> tuple[str, str]:
        """Overwrite cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")

    # Kernel operations

    async def get_or_create_kernel(self, path: str, kernel_id: str | None = None) -> str:
        """Get or create kernel via kernel_client."""
        # TODO: Implement using the configured kernel client adapter
        raise NotImplementedError("To be refactored from server.py")

    async def execute_cell(
        self, path: str, cell_index: int, kernel_id: str, timeout_seconds: int = 300
    ) -> list[str | ImageContent]:
        """Execute cell via kernel_client."""
        # TODO: Implement using the configured kernel client adapter
        raise NotImplementedError("To be refactored from server.py")

    async def interrupt_kernel(self, kernel_id: str) -> None:
        """Interrupt kernel via kernel_client."""
        # TODO: Implement using the configured kernel client adapter
        raise NotImplementedError("To be refactored from server.py")

    async def restart_kernel(self, kernel_id: str) -> None:
        """Restart kernel via kernel_client."""
        # TODO: Implement using the configured kernel client adapter
        raise NotImplementedError("To be refactored from server.py")

    async def shutdown_kernel(self, kernel_id: str) -> None:
        """Shutdown kernel via kernel_client."""
        # TODO: Implement using the configured kernel client adapter
        raise NotImplementedError("To be refactored from server.py")

    async def list_kernels(self) -> list[dict[str, Any]]:
        """List kernels via server API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")

    async def kernel_exists(self, kernel_id: str) -> bool:
        """Check if kernel exists via server API."""
        # TODO: Implement using jupyter_server_client
        raise NotImplementedError("To be refactored from server.py")
