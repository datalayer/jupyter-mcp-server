# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Use notebook tool implementation."""

import inspect
import logging
from pathlib import Path
from typing import Any, Literal

import nbformat
from jupyter_core.utils import ensure_async
from jupyter_nbmodel_client import NbModelClient
from jupyter_server_client import JupyterServerClient, NotFoundError

from jupyter_mcp_server.models import Notebook
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.sandbox_client import create_jupyter_sandbox_client
from jupyter_mcp_server.tools._base import BaseTool, ServerMode

logger = logging.getLogger(__name__)


class UseNotebookTool(BaseTool):
    """Tool to use (connect to or create) a notebook file."""

    async def _start_kernel_local(self, kernel_manager: Any, path: str | None = None):
        # Start a new kernel using local API
        kernel_id = await kernel_manager.start_kernel()
        logger.info(f"Started kernel '{kernel_id}', waiting for it to be ready...")

        # CRITICAL: Wait for the kernel to actually start and be ready
        # The start_kernel() call returns immediately, but kernel takes time to start
        import asyncio

        max_wait_time = 30  # seconds
        wait_interval = 0.5  # seconds
        elapsed = 0
        kernel_ready = False

        while elapsed < max_wait_time:
            try:
                # Get kernel model to check its state
                kernel_model = kernel_manager.get_kernel(kernel_id)
                if kernel_model is not None:
                    # Kernel exists, check if it's ready
                    # In Jupyter, we can try to get connection info which indicates readiness
                    try:
                        kernel_manager.get_connection_info(kernel_id)
                        kernel_ready = True
                        logger.info(f"Kernel '{kernel_id}' is ready (took {elapsed:.1f}s)")
                        break
                    except:
                        # Connection info not available yet, kernel still starting
                        pass
            except Exception as e:
                logger.debug(f"Waiting for kernel to start: {e}")

            await asyncio.sleep(wait_interval)
            elapsed += wait_interval

        if not kernel_ready:
            logger.warning(
                f"Kernel '{kernel_id}' may not be fully ready after {max_wait_time}s wait"
            )

        return {"id": kernel_id}

    async def _check_path_http(
        self, sandbox_server_client: JupyterServerClient, notebook_path: str, mode: str
    ) -> tuple[bool, str | None]:
        """Check if path exists using HTTP API."""
        path = Path(notebook_path)
        try:
            parent_path = path.parent.as_posix() if path.parent.as_posix() != "." else ""

            if parent_path:
                dir_contents = sandbox_server_client.contents.list_directory(parent_path)
            else:
                dir_contents = sandbox_server_client.contents.list_directory("")

            file_exists = any(file.name == path.name for file in dir_contents)
            if mode == "connect":
                if not file_exists:
                    return (
                        False,
                        f"'{notebook_path}' not found in jupyter server, please check the notebook already exists.",
                    )
            elif mode == "create":
                if file_exists:
                    return (
                        False,
                        f"'{notebook_path}' already exists in jupyter server, please use a different path or use_mode='connect' to open it.",
                    )

            return True, None
        except NotFoundError:
            parent_dir = (
                path.parent.as_posix() if path.parent.as_posix() != "." else "root directory"
            )
            return (
                False,
                f"'{parent_dir}' not found in jupyter server, please check the directory path already exists.",
            )
        except Exception as e:
            return False, f"Failed to check the path '{notebook_path}': {e}"

    async def _check_path_local(
        self, contents_manager: Any, notebook_path: str, mode: str
    ) -> tuple[bool, str | None]:
        """Check if path exists using local contents_manager API."""
        path = Path(notebook_path)
        try:
            parent_path = str(path.parent) if str(path.parent) != "." else ""

            # Get directory contents using local API
            model = await ensure_async(
                contents_manager.get(parent_path, content=True, type="directory")
            )

            file_exists = any(item["name"] == path.name for item in model.get("content", []))
            if mode == "connect":
                if not file_exists:
                    return (
                        False,
                        f"'{notebook_path}' not found in jupyter server, please check the notebook already exists.",
                    )
            elif mode == "create":
                if file_exists:
                    return (
                        False,
                        f"'{notebook_path}' already exists in jupyter server, please use a different path or use_mode='connect' to open it.",
                    )

            return True, None
        except Exception as e:
            parent_dir = str(path.parent) if str(path.parent) != "." else "root directory"
            return False, f"'{parent_dir}' not found in jupyter server: {e}"

    async def execute(
        self,
        mode: ServerMode,
        sandbox_server_client: JupyterServerClient | None = None,
        contents_manager: Any | None = None,
        kernel_manager: Any | None = None,
        kernel_spec_manager: Any | None = None,
        session_manager: Any | None = None,
        notebook_manager: NotebookManager | None = None,
        # Tool-specific parameters
        notebook_name: str = None,
        notebook_path: str = None,
        use_mode: Literal["connect", "create"] = "connect",
        kernel_id: str | None = None,
        code_sandbox_url: str | None = None,
        code_sandbox_token: str | None = None,
        auth_headers: dict[str, str] | None = None,
        **kwargs,
    ) -> str:
        """Execute the use_notebook tool.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            sandbox_server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            kernel_manager: Direct kernel manager for JUPYTER_SERVER mode
            session_manager: Session manager for creating kernel-notebook associations
            notebook_manager: Notebook manager instance
            notebook_name: Unique identifier for the notebook
            notebook_path: Path to the notebook file (optional, if not provided switches to existing notebook)
            use_mode: "connect" or "create"
            kernel_id: Optional specific kernel ID
            code_sandbox_url: Code sandbox URL for HTTP mode
            code_sandbox_token: Code sandbox token for HTTP mode
            **kwargs: Additional parameters

        Returns:
            Success message with notebook information
        """
        # Check server connectivity (HTTP mode only).
        #
        # Only when a Jupyter server is actually what holds the documents.
        # `get_status()` asks for `/api/status`, which exists on a Jupyter
        # server and nowhere else — so when the documents come from another
        # provider, or code runs in a sandbox that is not a Jupyter, this
        # precheck fails against a URL that was never meant to answer it and
        # the tool reports "Failed to connect the Jupyter server" for a server
        # it does not need. Nothing downstream uses that client in those
        # setups: the document goes over the provider's own collaboration
        # endpoint, and execution through the sandbox.
        from jupyter_mcp_server.config import get_config

        config = get_config()
        needs_jupyter = (
            config.document_provider == "jupyter" and not config.uses_sandbox_variant()
        )
        if (
            mode == ServerMode.MCP_SERVER
            and sandbox_server_client is not None
            and needs_jupyter
        ):
            try:
                sandbox_server_client.get_status()
            except Exception as e:
                return f"Failed to connect the Jupyter server: {e}"

        # In split setups, contents operations use the document server and its auth.
        # When the URLs match, sandbox_server_client already targets the document server.
        document_server_client = sandbox_server_client
        document_auth_headers = auth_headers
        if mode == ServerMode.MCP_SERVER and sandbox_server_client is not None:
            from jupyter_mcp_server.config import get_config

            config = get_config()
            if config.document_url and config.document_url != config.code_sandbox_url:
                from jupyter_mcp_server.server_context import ServerContext

                context = ServerContext.get_instance()
                document_server_client = context.document_server_client
                document_auth_headers = context.document_auth_headers

        # Check the path exists
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            path_ok, error_msg = await self._check_path_local(
                contents_manager, notebook_path, use_mode
            )
        elif mode == ServerMode.MCP_SERVER and sandbox_server_client is not None:
            path_ok, error_msg = await self._check_path_http(
                document_server_client, notebook_path, use_mode
            )
        else:
            return f"Invalid mode or missing required clients: mode={mode}"

        if not path_ok:
            return error_msg

        info_list = []

        # Check if notebook already in notebook_manager (Cober all cases)
        if notebook_name in notebook_manager:
            if use_mode == "create":
                if notebook_manager.get_notebook_path(notebook_name) == notebook_path:
                    return f"Notebook '{notebook_name}'(path: {notebook_path}) is already created. DO NOT CREATE AGAIN."
                else:
                    return f"Notebook '{notebook_name}' is already used. Use different notebook_name to create a new notebook on {notebook_path}."
            else:
                if notebook_manager.get_notebook_path(notebook_name) == notebook_path:
                    if notebook_name == notebook_manager.get_current_notebook():
                        return f"Notebook '{notebook_name}' is already activated now. DO NOT REACTIVATE AGAIN."
                    else:
                        # the only correct case.
                        info_list.append(
                            f"[INFO] Reactivating notebook '{notebook_name}' and deactivating '{notebook_manager.get_current_notebook()}'."
                        )
                        notebook_manager.set_current_notebook(notebook_name)
                else:
                    return f"The path '{notebook_path}' is not the correct path for notebook '{notebook_name}'. Do you mean connect to '{notebook_manager.get_notebook_path(notebook_name)}'?"
        # add new notebook to notebook_manager
        else:
            # Create notebook if needed
            # This runs before the kernel and the Jupyter session below, which are
            # both pointed at notebook_path and so need the file to exist already.
            if use_mode == "create":
                # Build the notebook with nbformat's constructors rather than a
                # raw dict so the format version and the per-cell `id` stay
                # consistent: nbformat 4.5 requires a unique `id` on every cell,
                # and new_markdown_cell()/new_notebook() assign the id and stamp
                # the matching nbformat_minor for us. Hand-writing the dict is how
                # a cell ended up without an `id` under nbformat_minor 5 (see #338)
                # and, on main, a downgrade to nbformat_minor 4 that drops cell ids
                # entirely. This also matches insert_cell, which already uses
                # nbformat.v4.new_code_cell().
                content = nbformat.v4.new_notebook(
                    cells=[
                        nbformat.v4.new_markdown_cell(
                            "New Notebook Created by Jupyter MCP Server"
                        )
                    ]
                )
                if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
                    # Use local API to create notebook
                    await ensure_async(
                        contents_manager.new(
                            model={"type": "notebook", "content": content, "format": "json"},
                            path=notebook_path,
                        )
                    )
                elif mode == ServerMode.MCP_SERVER and sandbox_server_client is not None:
                    # Creating a notebook is a state-changing PUT to /api/contents,
                    # which Jupyter's XSRF protection guards. Under password auth the
                    # injected session carries the _xsrf cookie but not the matching
                    # X-XSRFToken header, and the cookie alone fails the check
                    # ("'_xsrf' argument missing from POST"). Echo the token the
                    # caller just read from the live cookie jar, so a rotated cookie
                    # cannot go stale. Token auth has no _xsrf cookie and satisfies
                    # XSRF via its own header, so nothing happens there.
                    xsrf_token = (document_auth_headers or {}).get("X-XSRFToken")
                    session = getattr(
                        getattr(document_server_client, "http_client", None), "session", None
                    )
                    if xsrf_token and session is not None:
                        session.headers["X-XSRFToken"] = xsrf_token
                    document_server_client.contents.create_notebook(notebook_path, content=content)

            # # Create/connect to kernel based on mode
            if mode == ServerMode.MCP_SERVER and sandbox_server_client is not None:
                if kernel_id is not None:
                    kernels = sandbox_server_client.kernels.list_kernels()
                    kernel_exists = any(kernel.id == kernel_id for kernel in kernels)
                    if not kernel_exists:
                        return f"Kernel '{kernel_id}' not found in jupyter server, please check whether the kernel already exists using 'list_kernels' tool."
                # Ensure the kernel is started with the same path as the notebook.
                # Routed through code-sandboxes (jupyter variant) rather than a
                # direct JupyterKernelClient; the sandbox creates and starts the kernel.
                from jupyter_mcp_server.config import get_config

                config = get_config()
                kernel = create_jupyter_sandbox_client(
                    server_url=code_sandbox_url,
                    # Password auth authenticates via the cookie/XSRF headers, so
                    # the token is dropped when they are present.
                    token=None if auth_headers else code_sandbox_token,
                    kernel_id=kernel_id,
                    path=notebook_path,
                    logger=logger,
                    timeout=getattr(config, "execution_timeout", None),
                    reconnect_interval=getattr(config, "reconnect_interval", 0) or 0,
                    headers=auth_headers or None,
                )

                info_list.append(f"[INFO] Connected to kernel '{kernel.id}'.")
            elif mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
                # JUPYTER_SERVER mode: Use local kernel manager API directly
                if kernel_id:
                    # Connect to existing kernel - verify it exists
                    if kernel_id not in kernel_manager:
                        return f"Kernel '{kernel_id}' not found in local kernel manager."
                    kernel = {"id": kernel_id}
                else:
                    kernel = await self._start_kernel_local(kernel_manager, path=notebook_path)
                    kernel_id = kernel["id"]

                info_list.append(f"[INFO] Connected to kernel '{kernel_id}'.")
                # Create a Jupyter session to associate the kernel with the notebook
                # This is CRITICAL for JupyterLab to recognize the kernel-notebook connection
                if session_manager is not None:
                    try:
                        # create_session is an async method, so we await it directly
                        session_dict = await session_manager.create_session(
                            path=notebook_path,
                            kernel_id=kernel_id,
                            type="notebook",
                            name=notebook_path,
                        )
                        logger.info(
                            f"Created Jupyter session '{session_dict.get('id')}' for notebook '{notebook_path}' with kernel '{kernel_id}'"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to create Jupyter session: {e}. Notebook may not be properly connected in JupyterLab UI."
                        )
                else:
                    logger.warning(
                        "No session_manager available. Notebook may not be properly connected in JupyterLab UI."
                    )

            # Add notebook to notebook_manager
            if mode == ServerMode.MCP_SERVER and code_sandbox_url:
                from jupyter_mcp_server.config import get_config

                # The notebook and its collaboration session live on the
                # document server.
                config = get_config()
                notebook_manager.add_notebook(
                    notebook_name,
                    kernel,
                    server_url=config.document_url,
                    token=config.document_token,
                    path=notebook_path,
                )
            elif mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
                notebook_manager.add_notebook(
                    notebook_name, kernel, server_url="local", token=None, path=notebook_path
                )
            else:
                return f"Invalid configuration: mode={mode}, code_sandbox_url={code_sandbox_url}, kernel_manager={kernel_manager is not None}"

            notebook_manager.set_current_notebook(notebook_name)
            info_list.append(f"[INFO] Successfully activate notebook '{notebook_name}'.")

        # Return the quick overview of currently activated notebook
        try:
            if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
                # Read notebook to get cell count and first 20 cells
                model = await ensure_async(
                    contents_manager.get(notebook_path, content=True, type="notebook")
                )
                if "content" in model:
                    notebook = Notebook(**model["content"])
                else:
                    notebook = Notebook()

            elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
                # Use notebook manager to get cell info
                nbclient_supports_headers = (
                    "additional_headers" in inspect.signature(NbModelClient).parameters
                )
                if auth_headers and not code_sandbox_token and not nbclient_supports_headers:
                    info_list.append(
                        "\nNotebook preview skipped: current jupyter_nbmodel_client "
                        "does not support websocket auth headers in password-only mode."
                    )
                    return "\n".join(info_list)
                async with notebook_manager.get_current_connection() as notebook_content:
                    notebook = Notebook(**notebook_content.as_dict())

            info_list.append(f"\nNotebook has {len(notebook)} cells.")
            info_list.append(f"Showing first {min(20, len(notebook))} cells:\n")
            info_list.append(
                notebook.format_output(response_format="brief", start_index=0, limit=20)
            )
        except Exception as e:
            logger.debug(f"Failed to get notebook summary: {e}")

        # Check if we should open in JupyterLab UI (when JupyterLab mode is
        # enabled and the user opted in, since opening activates the tab)
        try:
            from jupyter_mcp_server.config import get_config
            from jupyter_mcp_server.jupyter_extension.context import get_server_context

            context = get_server_context()

            if context.is_jupyterlab_mode() and get_config().open_notebook_in_ui:
                logger.info(
                    f"JupyterLab mode enabled, attempting to open notebook '{notebook_path}' in JupyterLab UI"
                )

                # Determine base_url and token based on mode
                base_url = None
                token = None

                if mode == ServerMode.JUPYTER_SERVER and context.serverapp is not None:
                    # JUPYTER_SERVER mode: Use ServerApp connection details
                    base_url = context.serverapp.connection_url
                    token = context.serverapp.token
                elif mode == ServerMode.MCP_SERVER:
                    # In split setups, open the file in the document server's
                    # JupyterLab, where the notebook is stored.
                    config = get_config()
                    if config.document_url and config.document_url != config.code_sandbox_url:
                        base_url = config.document_url
                        token = config.document_token
                    elif code_sandbox_url:
                        base_url = code_sandbox_url
                        token = code_sandbox_token

                if base_url and token:
                    try:
                        from jupyter_mcp_tools.client import MCPToolsClient

                        async with MCPToolsClient(base_url=base_url, token=token) as client:
                            execution_result = await client.execute_tool(
                                tool_id="docmanager_open",  # docmanager:open converted to underscore format
                                parameters={"path": notebook_path},
                            )

                            if execution_result.get("success"):
                                logger.info(
                                    "Successfully opened notebook '%s' in JupyterLab UI",
                                    notebook_path,
                                )
                            else:
                                logger.warning(
                                    f"Failed to open notebook in JupyterLab UI: {execution_result}"
                                )

                    except ImportError:
                        logger.warning(
                            "jupyter_mcp_tools not available, skipping JupyterLab UI opening"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to open notebook in JupyterLab UI: {e}")
                else:
                    logger.warning(
                        "No valid base_url or token available for opening notebook in JupyterLab UI"
                    )
        except Exception as e:
            logger.debug(f"Could not check JupyterLab mode: {e}")

        return "\n".join(info_list)
