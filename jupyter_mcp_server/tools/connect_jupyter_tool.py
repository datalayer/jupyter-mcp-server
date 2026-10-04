# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tool for dynamically connecting to Jupyter server with URL and token."""

import asyncio
import logging

import requests

from jupyter_mcp_server.config import set_config
from jupyter_mcp_server.tools._base import BaseTool, ServerMode

logger = logging.getLogger(__name__)

_STATUS_TIMEOUT_SECONDS = 10.0


def _unset(value: str | None) -> bool:
    """`set_config` reads "None", "null" and "" as no value; read them the same here."""
    return value is None or value.lower() in ("none", "null", "")


def _check_jupyter_server(jupyter_url: str, jupyter_token: str | None) -> None:
    """Ask the server for `/api/status` with the token the agent was given.

    Switching the configuration does not touch the server, so without this a
    typo'd URL, a dead port or a wrong token all came back as "Successfully
    connected", and every later tool failed instead. Same check as the
    password login's verification step in `auth.py`.

    Raises:
        RuntimeError: The server can't be reached, rejects the token, or
            doesn't answer `/api/status` with a 200.
    """
    url = f"{jupyter_url.rstrip('/')}/api/status"
    headers = {"Authorization": f"token {jupyter_token}"} if not _unset(jupyter_token) else {}
    try:
        response = requests.get(url, headers=headers, timeout=_STATUS_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as error:
        raise RuntimeError(f"could not reach {url}: {error}") from error
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"the server rejected the token (GET /api/status returned {response.status_code})"
        )
    if response.status_code != 200:
        raise RuntimeError(f"GET /api/status returned {response.status_code}")


class ConnectJupyterTool(BaseTool):
    """Connect to a Jupyter server with dynamic URL and token."""

    async def execute(
        self,
        mode: ServerMode,
        jupyter_url: str,
        jupyter_token: str | None = None,
        document_provider: str = "jupyter",
        **kwargs,
    ) -> str:
        """Execute the connect to Jupyter server operation.

        Args:
            mode: ServerMode indicating MCP_SERVER or JUPYTER_SERVER
            jupyter_url: The Jupyter server URL to connect to
            jupyter_token: The Jupyter server token for authentication
            document_provider: DocumentProvider type (default: "jupyter")
            **kwargs: Additional keyword arguments

        Returns:
            Success message with connection information
        """

        logger.info(
            f"Connecting to Jupyter server - URL: {jupyter_url}, "
            f"Token: {'***' if jupyter_token else 'None'}"
        )

        if document_provider == "jupyter" and jupyter_url != "local" and not _unset(jupyter_url):
            try:
                await asyncio.to_thread(_check_jupyter_server, jupyter_url, jupyter_token)
            except RuntimeError as error:
                # Leave the current connection in place: it may still work,
                # and the new one is known not to.
                error_msg = (
                    f"Failed to connect to Jupyter server {jupyter_url}: {error}. "
                    "The previous connection is unchanged."
                )
                logger.error(error_msg)
                raise Exception(error_msg) from error

        try:
            # Update configuration with new connection parameters
            set_config(
                document_provider=document_provider,
                code_sandbox_url=jupyter_url,
                code_sandbox_token=jupyter_token,
                document_url=jupyter_url,
                document_token=jupyter_token,
            )

            # Reset ServerContext to pick up new configuration
            # Import here to avoid circular import issues
            from jupyter_mcp_server.server_context import ServerContext

            ServerContext.reset()

            # Build connection info message
            connection_info = [
                f"Successfully connected to Jupyter server: {jupyter_url}",
                f"DocumentProvider: {document_provider}",
            ]

            if jupyter_token:
                connection_info.append("Authentication: Token-based")
            else:
                connection_info.append("Authentication: None (anonymous)")

            return "\n".join(connection_info)

        except Exception as e:
            error_msg = f"Failed to connect to Jupyter server {jupyter_url}: {e!s}"
            logger.error(error_msg)
            raise Exception(error_msg)
