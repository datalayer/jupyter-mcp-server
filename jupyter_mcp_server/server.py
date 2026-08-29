# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter MCP Server Layer
"""

import hmac
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from code_sandboxes import CodeSandboxClient
from fastapi import Request
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import ImageContent, ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from jupyter_mcp_server import cell_ids
from jupyter_mcp_server.__version__ import __version__
from jupyter_mcp_server.capabilities import (
    CAPABILITIES_RESOURCE,
    capabilities_extension,
    get_capabilities,
)
from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.enroll import auto_enroll_document
from jupyter_mcp_server.extensions import get_extension_manager
from jupyter_mcp_server.revalidation import revalidation_extension
from jupyter_mcp_server.tasks import tasks_extension
from jupyter_mcp_server.hooks import HookEvent, HookRegistry, with_hooks
from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.log import logger
from jupyter_mcp_server.models import DocumentCodeSandbox
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.results import (
    OutputsAnswer,
    TableAnswer,
    ToolAnswer,
    as_text,
    structured,
)
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.tools import (
    ClearCellOutputTool,
    ConnectJupyterTool,
    DeleteCellTool,
    EditCellSourceTool,
    # Cell Execution
    ExecuteCellTool,
    # Other Tools
    ExecuteCodeTool,
    # Cell Writing
    InsertCellTool,
    # MCP Prompt
    JupyterCitePrompt,
    ListFilesTool,
    ListKernelsTool,
    # Notebook Management
    ListNotebooksTool,
    MoveCellTool,
    OverwriteCellSourceTool,
    # Cell Reading
    ReadCellTool,
    ReadNotebookTool,
    RestartNotebookTool,
    # Tool infrastructure
    ServerMode,
    UnuseNotebookTool,
    UseNotebookTool,
)
from jupyter_mcp_server.utils import (
    create_code_sandbox,
    ensure_code_sandbox_alive,
    safe_extract_outputs,
    safe_notebook_operation,
    start_code_sandbox,
    wait_for_code_sandbox_idle,
)

###############################################################################
# Globals.


class CodeSandboxTokenVerifier:
    """Verify MCP client requests against the configured code sandbox token."""

    def __init__(self, token: str):
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id="mcp-client", scopes=[])


MANAGEMENT_ROUTE_PATHS = {"/api/connect", "/api/stop", "/api/healthz"}
AUTHENTICATED_MANAGEMENT_ROUTE_PATHS = {"/api/connect", "/api/stop"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _is_local_hostname(hostname: str | None) -> bool:
    return bool(hostname and hostname.lower() in LOCAL_HOSTNAMES)


def _is_management_route(path: str) -> bool:
    return path.rstrip("/") in MANAGEMENT_ROUTE_PATHS


def _is_authenticated_management_route(path: str) -> bool:
    return path.rstrip("/") in AUTHENTICATED_MANAGEMENT_ROUTE_PATHS


class ManagementRouteSecurityMiddleware(BaseHTTPMiddleware):
    """Apply authentication and browser-origin checks to management routes."""

    def __init__(self, app, token_verifier=None):
        super().__init__(app)
        self._token_verifier = token_verifier

    async def dispatch(self, request: Request, call_next):
        if not _is_management_route(request.url.path):
            return await call_next(request)

        if not _is_local_hostname(request.url.hostname):
            return JSONResponse({"error": "Invalid Host header"}, status_code=421)

        origin = request.headers.get("origin")
        if origin:
            origin_hostname = urlsplit(origin).hostname
            if not _is_local_hostname(origin_hostname):
                return JSONResponse({"error": "Invalid Origin header"}, status_code=403)

        if self._token_verifier and _is_authenticated_management_route(request.url.path):
            auth_header = request.headers.get("authorization", "")
            scheme, _, token = auth_header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                return JSONResponse(
                    {"error": "invalid_token", "error_description": "Authentication required"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer error="invalid_token", '
                            'error_description="Authentication required"'
                        )
                    },
                )

            access_token = await self._token_verifier.verify_token(token)
            if not access_token:
                return JSONResponse(
                    {"error": "invalid_token", "error_description": "Invalid token"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer error="invalid_token", ' 'error_description="Invalid token"'
                        )
                    },
                )

        return await call_next(request)


def _rows(value):
    """A tab-separated table, as rows a client can use without parsing prose.

    Several tools answer with a TSV table because that is compact for a model
    to read. An agent that wants one field out of it has to split the text and
    hope the columns did not move; this hands it the same table as data, with
    the header as keys, and leaves the text exactly as it was.
    """
    text = value if isinstance(value, str) else as_text(value)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or "\t" not in lines[0]:
        return {"result": text}
    header = [column.strip() for column in lines[0].split("\t")]
    items = [
        dict(zip(header, (cell.strip() for cell in line.split("\t"))))
        for line in lines[1:]
        if "\t" in line
    ]
    return {"result": text, "columns": header, "items": items, "count": len(items)}


def _outputs(value):
    """Execution or cell outputs, split into what is text and what is not.

    An image is left in `content` where a client can render it; the
    structured answer says one is there rather than trying to carry it twice.
    """
    blocks = value if isinstance(value, list) else [value]
    # `result` is the answer in the form it has always had: the outputs in
    # order, text as text and an image as its own object. Both halves matter
    # and each was learned from a test. Rendering a text output as an object
    # breaks a caller reading cell sources; dropping an image breaks one
    # reading an execution's picture — and it is dropped silently, because
    # the text beside it still arrives.
    outputs = []
    images = 0
    for block in blocks:
        if isinstance(block, ImageContent):
            images += 1
            outputs.append(block.model_dump(by_alias=True, exclude_none=True))
            continue
        outputs.append(block if isinstance(block, str) else as_text(block))
    return {
        "result": outputs,
        "outputs": outputs,
        "count": len(outputs),
        "images": images,
    }


class MCPServerWithCORS(MCPServer):
    async def list_tools(self, *arguments, **keywords):
        """The tools, in a deterministic order — by name.

        Registration order is deterministic for one build and nothing more.
        It moves when a tool is added, when one is moved in this file, and
        now that extensions register after configuration rather than at
        import, it moves depending on *when* an extension got its turn. A
        client that caches a tool list and compares it then sees a change
        that is not one, and re-reads a catalogue that did not move.

        Sorting by name is stable across all of that, and the specification
        recommends a deterministic order for exactly this reason.
        """
        listed = await super().list_tools(*arguments, **keywords)
        return sorted(listed, key=lambda tool: tool.name)

    async def call_tool(self, name, arguments, context=None):
        """Call a tool, keeping the reason when it fails.

        mcp 2 treats anything a tool raises other than ``ToolError`` as a crash
        and tells the client only ``Error executing tool <name>``. The tools
        here raise plain ``ValueError``/``RuntimeError`` carrying exactly what
        the agent needs in order to recover — which notebook is not connected,
        which index is out of range, what the kernel said — so that text is put
        back, in the form mcp 1 used: ``Error executing tool <name>: <reason>``.
        """
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError as exc:
            cause = exc.__cause__
            logger.debug("Tool %r failed: %s", name, cause, exc_info=cause)
            raise ToolError(f"{exc}: {cause}") from cause

    def streamable_http_app(
        self, *, json_response: bool = False, stateless_http: bool = True, **kwargs
    ) -> Starlette:
        """Return StreamableHTTP server app with CORS and auth middleware.

        The transport options were set on the server at construction in
        mcp 1; mcp 2 takes them here. The defaults are what this server
        needs: stateless, so that each request runs in its own context and
        :class:`~jupyter_mcp_server.identity.IdentityMiddleware` sees the
        caller of *that* request rather than whoever opened the session.

        See: https://github.com/modelcontextprotocol/python-sdk/issues/187
        """
        # Get the original Starlette app (includes RequireAuthMiddleware
        # when _token_verifier is set, but NOT the AuthenticationMiddleware
        # that actually validates Bearer tokens — that requires settings.auth
        # which we don't use). Add it here directly.
        app = super().streamable_http_app(
            json_response=json_response, stateless_http=stateless_http, **kwargs
        )

        # Added first, so it ends up innermost: Starlette builds the stack with
        # the last added outermost, and this has to run *after* the
        # authentication below has put the verified caller in the scope.
        # Without it a tool cannot tell who it is acting for, and every request
        # uses the single credential the process was configured with.
        from jupyter_mcp_server.identity import IdentityMiddleware

        app.add_middleware(IdentityMiddleware)

        app.add_middleware(
            ManagementRouteSecurityMiddleware,
            token_verifier=self._token_verifier,
        )

        if self._token_verifier:
            from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
            from starlette.middleware.authentication import AuthenticationMiddleware

            app.add_middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(self._token_verifier),
            )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, should set specific domains
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return app


#: What the server tells a client it is for. Sent in `initialize`, so an agent
#: reads it before choosing a tool — worth saying what the tools operate on
#: and what is unusual about them, rather than restating the name.
INSTRUCTIONS = (
    "Read, edit and run Jupyter notebooks. Cells are addressed by index within "
    "a notebook you have opened with use_notebook, and execution happens on the "
    "server, so a long computation keeps running after this session ends."
)

mcp = MCPServerWithCORS(
    name="Jupyter MCP Server",
    version=__version__,
    instructions=INSTRUCTIONS,
    # The capability registry, advertised where a client will find it
    # rather than only at `capabilities://`, which a client has to know to
    # ask for. See `jupyter_mcp_server.capabilities`.
    extensions=[capabilities_extension(), tasks_extension(), revalidation_extension()],
    # No `middleware=` here on purpose. mcp 2 installs its own
    # `OpenTelemetryMiddleware` by default, which is the span per inbound
    # message — `tools/list`, `tools/call`, the `gen_ai.*` attributes, the
    # client's `traceparent` continued. Passing one as well appends a second
    # instance and every message is traced twice, which reads as double the
    # traffic on every dashboard built from it. The hook-based OTel handler
    # beside it traces what happens *inside* a call, which the protocol layer
    # cannot see.
)
notebook_manager = NotebookManager()
server_context = ServerContext.get_instance()
extension_manager = get_extension_manager()


@mcp.resource(CAPABILITIES_RESOURCE)
def capabilities_resource() -> dict:
    """What this server can do, and where each answer came from.

    A server does things a client cannot see and did not ask for — replacing
    a dead kernel with an empty one is the clearest case. Reading this is how
    a client finds out which of those are on, and an operator finds out *why*
    a capability is on, which is the first question asked when one surprises
    somebody.

    A resource as well as a `server/discover` field, because a client may
    want to re-read it without re-discovering the server, and because a
    person can open a resource and look.
    """
    registry = get_capabilities()
    extension_manager.collect_capabilities(registry)
    return registry.advertise()


def __start_code_sandbox():
    """Start the Jupyter kernel with error handling (for backward compatibility)."""
    config = get_config()
    start_code_sandbox(notebook_manager, config, logger)


async def __auto_enroll_document():
    """Wrapper for auto_enroll_document that uses server context."""
    await auto_enroll_document(
        config=get_config(),
        notebook_manager=notebook_manager,
        use_notebook_tool=UseNotebookTool(),
        server_context=server_context,
    )


def __ensure_code_sandbox_alive() -> CodeSandboxClient:
    """Ensure kernel is running, restart if needed."""

    def __create_code_sandbox() -> CodeSandboxClient:
        """Create a new kernel instance using current configuration."""
        config = get_config()
        return create_code_sandbox(
            config, logger, path=notebook_manager.get_current_notebook_path()
        )

    current_notebook = notebook_manager.get_current_notebook() or "default"
    return ensure_code_sandbox_alive(notebook_manager, current_notebook, __create_code_sandbox)


def __make_execution_progress_callback(ctx: Context | None):
    """Build an MCP progress/log keepalive callback for long-running executions.

    Many MCP clients idle-timeout tool calls after a few minutes when the server
    is silent. ``report_progress`` and ``info`` keep protocol traffic flowing so
    a long cell (with ``--execution-timeout`` / tool ``timeout`` raised) can
    finish without the client abandoning the call while notebook outputs still
    land afterwards (issue #298).
    """

    async def progress_callback(
        *,
        elapsed: float,
        timeout_seconds: float,
        output_count: int = 0,
        message: str | None = None,
    ):
        if ctx is None:
            return
        msg = message or (
            f"Execution in progress: {elapsed:.0f}s / {timeout_seconds}s"
            + (f", {output_count} outputs" if output_count else "")
        )
        try:
            total = float(timeout_seconds) if timeout_seconds else None
            progress_value = min(elapsed, float(timeout_seconds)) if timeout_seconds else elapsed
            await ctx.report_progress(progress=progress_value, total=total, message=msg)
        except Exception:
            pass
        try:
            await ctx.info(msg)
        except Exception:
            pass

    return progress_callback


###############################################################################
# Custom Routes.


@mcp.custom_route("/api/connect", ["PUT"])
async def connect(request: Request):
    """Connect to a document and a code sandbox from the Jupyter MCP Server."""

    data = await request.json()

    # Log the received data for diagnostics
    # Note: set_config() will automatically normalize string "None" values
    logger.info(
        f"Connect endpoint received - code_sandbox_url: {data.get('code_sandbox_url')!r}, "
        f"document_url: {data.get('document_url')!r}, "
        f"document_provider: {data.get('document_provider')}"
    )

    document_code_sandbox = DocumentCodeSandbox(**data)

    # Clean up existing default notebook if any
    if "default" in notebook_manager:
        try:
            notebook_manager.remove_notebook("default")
        except Exception as e:
            logger.warning(f"Error stopping existing notebook during connect: {e}")

    # Update configuration with new values
    # String "None" values will be automatically normalized by set_config()
    set_config(
        document_provider=document_code_sandbox.document_provider,
        code_sandbox_url=document_code_sandbox.code_sandbox_url,
        code_sandbox_id=document_code_sandbox.code_sandbox_id,
        code_sandbox_token=document_code_sandbox.code_sandbox_token,
        document_url=document_code_sandbox.document_url,
        document_id=document_code_sandbox.document_id,
        document_token=document_code_sandbox.document_token,
        allowed_jupyter_tools=document_code_sandbox.allowed_jupyter_tools
        or "notebook_run-all-cells,notebook_get-selected-cell",
    )

    # Reset ServerContext to pick up new configuration
    ServerContext.reset()

    try:
        __start_code_sandbox()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/stop", ["DELETE"])
async def stop(request: Request):
    try:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        if current_notebook in notebook_manager:
            notebook_manager.remove_notebook(current_notebook)
        extension_manager.stop()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error stopping notebook: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/healthz", ["GET"])
async def health_check(request: Request):
    """Custom health check endpoint"""
    kernel_status = "unknown"
    try:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel = notebook_manager.get_code_sandbox(current_notebook)
        if kernel:
            kernel_status = "alive" if hasattr(kernel, "is_alive") and kernel.is_alive() else "dead"
        else:
            kernel_status = "not_initialized"
    except Exception:
        kernel_status = "error"
    return JSONResponse(
        {
            "success": True,
            "service": "jupyter-mcp-server",
            "message": "Jupyter MCP Server is running.",
            "status": "healthy",
            "kernel_status": kernel_status,
        }
    )


###############################################################################
# Tools.
###############################################################################

###############################################################################
# Server Management Tools.


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Files",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("files.list", shape=_rows, ttl_ms=30000)
@with_hooks("list_files")
async def list_files(
    path: Annotated[
        str, Field(description="The starting path to list from (empty string means root directory)")
    ] = "",
    # Maximum depth to recurse into subdirectories, Set Max to 3 to avoid infinite recursion.
    max_depth: Annotated[
        int, Field(description="Maximum depth to recurse into subdirectories", ge=0, le=3)
    ] = 1,
    start_index: Annotated[
        int, Field(description="Starting index for pagination (0-based)", ge=0)
    ] = 0,
    limit: Annotated[
        int, Field(description="Maximum number of items to return (0 means no limit)", ge=0)
    ] = 25,
    pattern: Annotated[str, Field(description="Glob pattern to filter file paths")] = "",
) -> TableAnswer:
    """
    List all files and directories recursively in the Jupyter server's file system.
    Used to explore the file system structure of the Jupyter server or to find specific files or directories.
    """
    return await safe_notebook_operation(
        lambda: ListFilesTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            path=path,
            max_depth=max_depth,
            start_index=start_index,
            limit=limit,
            pattern=pattern if pattern else None,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Kernels",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("kernels.list", shape=_rows, ttl_ms=10000)
@with_hooks("list_kernels")
async def list_kernels() -> (
    TableAnswer
):
    """List all available kernels in the Jupyter server.

    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.
    """
    return await safe_notebook_operation(
        lambda: ListKernelsTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            kernel_manager=server_context.kernel_manager,
            kernel_spec_manager=server_context.kernel_spec_manager,
        )
    )


###############################################################################
# Multi-Notebook Management Tools.


@mcp.tool(
    annotations=ToolAnnotations(
        title="Use Notebook",
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("notebook.use")
@with_hooks("use_notebook")
async def use_notebook(
    notebook_name: Annotated[str, Field(description="Unique identifier for the notebook")],
    notebook_path: Annotated[
        str,
        Field(
            description="Path to the notebook file, relative to the Jupyter server root (e.g. 'notebook.ipynb')"
        ),
    ],
    mode: Annotated[
        Literal["connect", "create"],
        Field(
            description="Notebook operation mode: 'connect' to connect to existing and activate it, 'create' to create new and activate it"
        ),
    ] = "connect",
    kernel_id: Annotated[
        str, Field(description="Specific kernel ID to use (will create new if skipped)")
    ] = None,
) -> ToolAnswer:
    """Use a notebook and activate it for following cell operations.
    All cell operations will be performed on the currently activated notebook.
    Activate new notebook will deactivate the previously activated notebook.
    Reactivate previously activated notebook using same notebook_name and notebook_path.
    """
    config = get_config()
    result = await safe_notebook_operation(
        lambda: UseNotebookTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            notebook_name=notebook_name,
            notebook_path=notebook_path,
            use_mode=mode,
            kernel_id=kernel_id,
            ensure_code_sandbox_alive_fn=__ensure_code_sandbox_alive,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            session_manager=server_context.session_manager,
            notebook_manager=notebook_manager,
            code_sandbox_url=config.code_sandbox_url if config.code_sandbox_url != "local" else None,
            code_sandbox_token=config.code_sandbox_token,
            auth_headers=server_context.code_sandbox_auth_headers or None,
        )
    )
    kid = notebook_manager.get_code_sandbox_id(notebook_name) or "unknown"
    await HookRegistry.get_instance().fire(
        HookEvent.KERNEL_LIFECYCLE,
        event_type="started",
        kernel_id=kid,
        kernel_name=notebook_name,
    )
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Notebooks",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("notebooks.list", shape=_rows, ttl_ms=30000)
@with_hooks("list_notebooks")
async def list_notebooks() -> (
    TableAnswer
):
    """List all notebooks that have been used via use_notebook tool"""
    return await ListNotebooksTool().execute(
        mode=server_context.mode,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restart Notebook",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@structured("notebook.restart")
@with_hooks("restart_notebook")
async def restart_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to restart")],
) -> ToolAnswer:
    """Restart the kernel for a specific notebook."""
    result = await RestartNotebookTool().execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )
    kid = notebook_manager.get_code_sandbox_id(notebook_name) or "unknown"
    await HookRegistry.get_instance().fire(
        HookEvent.KERNEL_LIFECYCLE,
        event_type="restarted",
        kernel_id=kid,
        kernel_name=notebook_name,
    )
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Unuse Notebook",
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("notebook.unuse")
@with_hooks("unuse_notebook")
async def unuse_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to disconnect")],
) -> ToolAnswer:
    """Unuse from a specific notebook and release its resources."""
    kid = notebook_manager.get_code_sandbox_id(notebook_name) or "unknown"
    result = await UnuseNotebookTool().execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )
    await HookRegistry.get_instance().fire(
        HookEvent.KERNEL_LIFECYCLE,
        event_type="stopped",
        kernel_id=kid,
        kernel_name=notebook_name,
    )
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Read Notebook",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
# A read, so it carries a version a client can revalidate against. The
# TTL is short because a notebook somebody is working in changes: the
# ETag is what makes holding it worthwhile, not the seconds.
@structured("notebook.read", ttl_ms=5000, etag=True)
@with_hooks("read_notebook")
async def read_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to read")],
    response_format: Annotated[
        Literal["brief", "detailed"],
        Field(
            description="Response format: 'brief' will return first line and lines number, 'detailed' will return full cell source"
        ),
    ] = "brief",
    start_index: Annotated[
        int, Field(description="Starting index for pagination (0-based)", ge=0)
    ] = 0,
    limit: Annotated[
        int, Field(description="Maximum number of items to return (0 means no limit)", ge=0)
    ] = 20,
) -> ToolAnswer:
    """Read a notebook and return index, source content, type, execution count of each cell.

    Using brief format to get a quick overview of the notebook structure and it's useful for locating specific cells for operations like delete or insert.
    Using detailed format to get detailed information of the notebook and it's useful for debugging and analysis.

    It is recommended to use brief format with larger limit to get a overview of the notebook structure,
    then use detailed format with exact index and limit to get the detailed information of some specific cells.
    """
    return await safe_notebook_operation(
        lambda: ReadNotebookTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            notebook_name=notebook_name,
            response_format=response_format,
            start_index=start_index,
            limit=limit,
        )
    )


###############################################################################
# Cell Tools.


@mcp.tool(
    annotations=ToolAnnotations(
        title="Insert Cell",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@structured("cell.insert")
@with_hooks("insert_cell")
async def insert_cell(
    cell_index: Annotated[
        int,
        Field(description="Target index for insertion (0-based), use -1 to append at end", ge=-1),
    ],
    cell_type: Annotated[
        Literal["code", "markdown", "raw"], Field(description="Type of cell to insert")
    ],
    cell_source: Annotated[str, Field(description="Source content for the cell")],
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
) -> ToolAnswer:
    """Insert a cell to specified position from the currently activated notebook."""
    return await safe_notebook_operation(
        lambda: InsertCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            cell_type=cell_type,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Overwrite Cell Source",
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("cell.overwrite")
@with_hooks("overwrite_cell_source")
async def overwrite_cell_source(
    *,
    cell_index: Annotated[
        int | None,
        Field(description="Index of the cell to overwrite (0-based). Omit when passing cell_id.", ge=0),
    ] = None,
    cell_source: Annotated[str, Field(description="New complete cell source")],
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Address the cell by its notebook cell id instead of its index. An "
                "index is a position, and a position stops being true the moment "
                "anyone inserts a cell above it; an id does not. Every result says "
                "which id it acted on, so read a cell once and address it by id "
                "afterwards. Given both, the id wins."
            )
        ),
    ] = None,
) -> ToolAnswer:
    """Replace the entire source of a cell in the currently activated notebook.
    Returns a diff showing the changes made.

    Use this when rewriting a cell completely. For small, targeted changes,
    prefer edit_cell_source instead — it is safer for partial edits."""
    cell_index = await cell_ids.resolve(
        cell_index=cell_index,
        cell_id=cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    return await safe_notebook_operation(
        lambda: OverwriteCellSourceTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Edit Cell Source",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@structured("cell.edit")
async def edit_cell_source(
    *,
    cell_index: Annotated[
        int | None,
        Field(description="Index of the cell to edit (0-based). Omit when passing cell_id.", ge=0),
    ] = None,
    old_string: Annotated[str, Field(description="Exact string to find in cell source")],
    new_string: Annotated[str, Field(description="Replacement string")],
    replace_all: Annotated[
        bool, Field(description="Replace all occurrences (default: first only)")
    ] = False,
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Address the cell by its notebook cell id instead of its index. An "
                "index is a position, and a position stops being true the moment "
                "anyone inserts a cell above it; an id does not. Every result says "
                "which id it acted on, so read a cell once and address it by id "
                "afterwards. Given both, the id wins."
            )
        ),
    ] = None,
) -> ToolAnswer:
    """Perform a surgical find-and-replace within a cell's source (like an editor's Edit tool).
    Finds `old_string` in the cell and replaces it with `new_string`. Matching is literal
    (not regex) and may span multiple lines. By default, `old_string` must appear exactly once;
    set `replace_all=True` for multiple occurrences. Returns a diff of the changes made.

    Prefer this over overwrite_cell_source for small, targeted edits — it is safer because
    unchanged parts of the cell are left untouched. Use read_cell first to see the current
    source and construct an accurate old_string."""
    cell_index = await cell_ids.resolve(
        cell_index=cell_index,
        cell_id=cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    return await safe_notebook_operation(
        lambda: EditCellSourceTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute Cell",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
@structured("cell.execute", shape=_outputs)
@with_hooks("execute_cell")
async def execute_cell(
    *,
    cell_index: Annotated[
        int | None,
        Field(description="Index of the cell to execute (0-based). Omit when passing cell_id.", ge=0),
    ] = None,
    timeout: Annotated[
        int, Field(description="Maximum seconds to wait for execution (0 = use config default)")
    ] = 0,
    stream: Annotated[
        bool,
        Field(
            description="Enable streaming progress (including time indicator) updates for long-running cells"
        ),
    ] = True,
    progress_interval: Annotated[
        int,
        Field(description="Seconds between progress updates (MCP keepalive + optional stream log)"),
    ] = 5,
    ctx: Context | None = None,
    cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Address the cell by its notebook cell id instead of its index. An "
                "index is a position, and a position stops being true the moment "
                "anyone inserts a cell above it; an id does not. Every result says "
                "which id it acted on, so read a cell once and address it by id "
                "afterwards. Given both, the id wins."
            )
        ),
    ] = None,
) -> OutputsAnswer:
    """Execute a cell from the currently activated notebook with timeout and return it's outputs"""
    cell_index = await cell_ids.resolve(
        cell_index=cell_index,
        cell_id=cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        # `execute_cell` always acts on the currently activated notebook; it
        # takes no `notebook_name`, so the resolver reads that same one.
        notebook_name=None,
    )
    config = get_config()
    # Use config default if timeout is 0, otherwise clamp to max
    effective_timeout = (
        config.execution_timeout if timeout == 0 else min(timeout, config.max_execution_timeout)
    )
    progress_callback = __make_execution_progress_callback(ctx)

    return await safe_notebook_operation(
        lambda: ExecuteCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=effective_timeout,
            stream=stream,
            progress_interval=progress_interval,
            ensure_code_sandbox_alive_fn=__ensure_code_sandbox_alive,
            progress_callback=progress_callback,
        ),
        max_retries=1,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Insert and Execute Code Cell",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
@structured("cell.insert_execute", shape=_outputs)
@with_hooks("insert_execute_code_cell")
async def insert_execute_code_cell(
    cell_index: Annotated[
        int, Field(description="Index of the cell to insert and execute (0-based)", ge=-1)
    ],
    cell_source: Annotated[str, Field(description="Code source for the cell")],
    timeout: Annotated[
        int, Field(description="Maximum seconds to wait for execution (0 = use config default)")
    ] = 0,
    stream: Annotated[
        bool,
        Field(
            description="Enable streaming progress (including time indicator) updates for long-running cells"
        ),
    ] = True,
    progress_interval: Annotated[
        int,
        Field(description="Seconds between progress updates (MCP keepalive + optional stream log)"),
    ] = 5,
    ctx: Context | None = None,
) -> OutputsAnswer:
    """Insert a cell at specified index from the currently activated notebook and then execute it with timeout and return it's outputs
    It is a shortcut tool for insert_cell and execute_cell tools, recommended to use if you want to insert a cell and execute it at the same time"""
    config = get_config()
    effective_timeout = (
        config.execution_timeout if timeout == 0 else min(timeout, config.max_execution_timeout)
    )
    progress_callback = __make_execution_progress_callback(ctx)

    insert_result = await safe_notebook_operation(
        lambda: InsertCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            cell_type="code",
        )
    )

    # Execute exactly the cell that was inserted. This avoids races where an
    # append operation (-1) could execute a previously last cell if notebook
    # state visibility lags briefly between insert and execute paths.
    execute_index = cell_index
    if isinstance(insert_result, str):
        match = re.search(r"Cell inserted successfully at index (-?\d+)", insert_result)
        if match:
            execute_index = int(match.group(1))

    return await safe_notebook_operation(
        lambda: ExecuteCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=execute_index,
            timeout_seconds=effective_timeout,
            stream=stream,
            progress_interval=progress_interval,
            ensure_code_sandbox_alive_fn=__ensure_code_sandbox_alive,
            progress_callback=progress_callback,
        ),
        max_retries=1,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Read Cell",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("cell.read", shape=_outputs, ttl_ms=5000, etag=True)
@with_hooks("read_cell")
async def read_cell(
    *,
    cell_index: Annotated[
        int | None,
        Field(description="Index of the cell to read (0-based). Omit when passing cell_id.", ge=0),
    ] = None,
    include_outputs: Annotated[
        bool, Field(description="Include outputs in the response (only for code cells)")
    ] = True,
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Address the cell by its notebook cell id instead of its index. An "
                "index is a position, and a position stops being true the moment "
                "anyone inserts a cell above it; an id does not. Every result says "
                "which id it acted on, so read a cell once and address it by id "
                "afterwards. Given both, the id wins."
            )
        ),
    ] = None,
) -> OutputsAnswer:
    """Read a cell as readable text entries.

    Includes metadata and source, plus optional formatted output text rather
    than raw nbformat objects.
    """
    cell_index = await cell_ids.resolve(
        cell_index=cell_index,
        cell_id=cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    return await safe_notebook_operation(
        lambda: ReadCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            include_outputs=include_outputs,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete Cell",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@structured("cell.delete")
@with_hooks("delete_cell")
async def delete_cell(
    *,
    cell_indices: Annotated[
        list[int] | None,
        Field(
            description="List of cell indices to delete (0-based). Omit when passing cell_ids_to_delete.",
            min_length=1,
        ),
    ] = None,
    include_source: Annotated[
        bool, Field(description="Whether to include the source of deleted cells")
    ] = True,
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    cell_ids_to_delete: Annotated[
        list[str] | None,
        Field(
            description=(
                "Address the cells by their notebook cell ids instead of their "
                "indices. Safer for a multi-cell delete than indices, which shift "
                "as earlier cells go. Given both, the ids win; every id is checked "
                "before any cell is deleted, so a bad one fails the whole call "
                "rather than half-deleting the notebook."
            )
        ),
    ] = None,
) -> ToolAnswer:
    """Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True)."""
    cell_indices = await cell_ids.resolve_many(
        cell_indices=cell_indices,
        cell_ids_wanted=cell_ids_to_delete,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    return await safe_notebook_operation(
        lambda: DeleteCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_indices=cell_indices,
            include_source=include_source,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Clear Cell Output",
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("cell.clear_output")
@with_hooks("clear_cell_output")
async def clear_cell_output(
    *,
    cell_index: Annotated[
        int | None,
        Field(
            description="Index of the code cell to clear (0-based). Omit when passing cell_id.",
            ge=0,
        ),
    ] = None,
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Address the cell by its notebook cell id instead of its index. An "
                "index is a position, and a position stops being true the moment "
                "anyone inserts a cell above it; an id does not. Every result says "
                "which id it acted on, so read a cell once and address it by id "
                "afterwards. Given both, the id wins."
            )
        ),
    ] = None,
) -> ToolAnswer:
    """Clear the outputs and execution count of a single code cell in the currently
    activated notebook, without deleting the cell itself."""
    cell_index = await cell_ids.resolve(
        cell_index=cell_index,
        cell_id=cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    return await safe_notebook_operation(
        lambda: ClearCellOutputTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Move Cell",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@structured("cell.move")
async def move_cell(
    *,
    source_index: Annotated[
        int | None,
        Field(description="Index of the cell to move (0-based). Omit when passing source_cell_id.", ge=0),
    ] = None,
    target_index: Annotated[
        int | None,
        Field(
            description="Destination index where the cell will end up (0-based). Omit when passing target_cell_id.",
            ge=0,
        ),
    ] = None,
    notebook_name: Annotated[
        str | None,
        Field(
            description="Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook."
        ),
    ] = None,
    source_cell_id: Annotated[
        str | None,
        Field(description="Address the cell to move by its id rather than its index."),
    ] = None,
    target_cell_id: Annotated[
        str | None,
        Field(
            description=(
                "Put the moved cell where this cell is now, addressed by id rather "
                "than by an index that the move itself will shift."
            )
        ),
    ] = None,
) -> ToolAnswer:
    """Move a cell from source_index to target_index within the currently activated notebook.

    The cell is removed from source_index and placed at target_index. Cells in between shift
    to fill the gap. The cell's type, source, and outputs are preserved.
    Example: in a notebook [A, B, C, D], move_cell(1, 3) produces [A, C, D, B].

    Use this tool instead of manually deleting and re-inserting a cell — it is atomic and
    preserves cell metadata. Use read_notebook first to see cell indices if needed."""
    # Both resolved against the notebook as it is now, before anything
    # moves: resolving the target afterwards would resolve it against a
    # notebook the source had already left.
    source_index = await cell_ids.resolve(
        cell_index=source_index,
        cell_id=source_cell_id,
        mode=server_context.mode,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
        notebook_name=notebook_name,
    )
    if target_cell_id is not None:
        target_index = await cell_ids.resolve(
            cell_id=target_cell_id,
            mode=server_context.mode,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            notebook_name=notebook_name,
        )
    return await safe_notebook_operation(
        lambda: MoveCellTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            source_index=source_index,
            target_index=target_index,
            notebook_name=notebook_name,
        )
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute Code",
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
@structured("code.execute", shape=_outputs)
@with_hooks("execute_code")
async def execute_code(
    code: Annotated[
        str,
        Field(
            description="Code to execute (supports magic commands with %, shell commands with !)"
        ),
    ],
    timeout: Annotated[
        int, Field(description="Maximum seconds to wait for execution (0 = use config default)")
    ] = 30,
    kernel_id: Annotated[
        str | None,
        Field(
            description="Target an existing kernel by ID (e.g. a raw kernel with no notebook). If omitted, uses the current notebook's kernel."
        ),
    ] = None,
    progress_interval: Annotated[
        int,
        Field(
            description="Seconds between MCP progress keepalive updates during long-running execution"
        ),
    ] = 5,
    ctx: Context | None = None,
) -> OutputsAnswer:
    """Execute code directly in a kernel (not saved to notebook).

    If `use_sandbox` selected an active sandbox, this tool executes on that
    sandbox instead of a Jupyter kernel. This allows agents to switch between
    kernel-backed and sandbox-backed execution using the same execute_code API.

    Targets the current activated notebook's kernel by default. Pass kernel_id
    to execute in a specific kernel directly — including raw kernels with no
    notebook attached.

    Recommended to use in following cases:
    1. Execute Jupyter magic commands(e.g., `%timeit`, `%pip install xxx`)
    2. Performance profiling and debugging.
    3. View intermediate variable values(e.g., `print(xxx)`, `df.head()`)
    4. Temporary calculations and quick tests(e.g., `np.mean(df['xxx'])`)
    5. Execute Shell commands in Jupyter server(e.g., `!git xxx`)

    Under no circumstances should you use this tool to:
    1. Import new modules or perform variable assignments that affect subsequent Notebook execution
    2. Execute dangerous code that may harm the Jupyter server or the user's data without permission
    """
    config = get_config()
    # Use config default if timeout is 0, otherwise clamp to max
    effective_timeout = (
        config.execution_timeout if timeout == 0 else min(timeout, config.max_execution_timeout)
    )
    progress_callback = __make_execution_progress_callback(ctx)

    intercepted = await extension_manager.intercept_execute_code(code, effective_timeout)
    if intercepted is not None:
        return intercepted

    if kernel_id is None and server_context.mode == ServerMode.JUPYTER_SERVER:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel_id = notebook_manager.get_code_sandbox_id(current_notebook)

    return await safe_notebook_operation(
        lambda: ExecuteCodeTool().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            code=code,
            timeout=effective_timeout,
            kernel_id=kernel_id,
            ensure_code_sandbox_alive_fn=__ensure_code_sandbox_alive,
            wait_for_code_sandbox_idle_fn=wait_for_code_sandbox_idle,
            safe_extract_outputs_fn=safe_extract_outputs,
            progress_callback=progress_callback,
            progress_interval=progress_interval,
        ),
        max_retries=1,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Connect to Jupyter Server",
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
@structured("jupyter.connect")
@with_hooks("connect_to_jupyter")
async def connect_to_jupyter(
    jupyter_url: Annotated[
        str, Field(description="Jupyter server URL to connect to (e.g., 'http://localhost:8888')")
    ],
    jupyter_token: Annotated[
        str | None, Field(description="Jupyter server authentication token")
    ] = None,
    document_provider: Annotated[
        str, Field(description="Which backend holds the notebook documents")
    ] = "jupyter",
) -> ToolAnswer:
    """Connect to a Jupyter server dynamically with URL and token.

    This tool allows you to connect to different Jupyter servers without needing to
    restart the MCP server or modify configuration files. Particularly useful when:
    - Working with multiple Jupyter servers with different ports/tokens
    - Jupyter server token changes dynamically
    - Need to switch between different Jupyter instances

    Example usage:
    - "Connect to http://localhost:8888 with token abc123"
    - "Connect to http://localhost:8889 without authentication"
    """
    return await safe_notebook_operation(
        lambda: ConnectJupyterTool().execute(
            mode=server_context.mode,
            jupyter_url=jupyter_url,
            jupyter_token=jupyter_token,
            document_provider=document_provider,
        )
    )


###############################################################################
# Prompt


@mcp.prompt()
async def jupyter_cite(
    prompt: Annotated[str, Field(description="User prompt for the cited cells")],
    cell_indices: Annotated[
        str,
        Field(
            description="Cell indices to cite (0-based),supporting flexible range format, e.g., '0,1,2', '0-2' or '0-2,4'"
        ),
    ],
    notebook_name: Annotated[
        str,
        Field(
            description="Name of the notebook to cite cells from, default (empty) to current activated notebook"
        ),
    ] = "",
):
    """
    Like @ or # in Coding IDE or CLI, cite specific cells from specified notebook and insert them into the prompt.
    """
    return await safe_notebook_operation(
        lambda: JupyterCitePrompt().execute(
            mode=server_context.mode,
            sandbox_server_client=server_context.sandbox_server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            cell_indices=cell_indices,
            notebook_name=notebook_name,
            prompt=prompt,
        )
    )


###############################################################################
# Helper Functions for Extension.


async def get_registered_tools():
    """
    Get list of all registered MCP tools with their metadata.

    This function is used by the Jupyter extension to dynamically expose
    the tool registry without hardcoding tool names and parameters.

    For JUPYTER_SERVER mode, it queries the jupyter-mcp-tools extension.
    For MCP_SERVER mode, it uses the local MCPServer registry.

    Returns:
        list: List of tool dictionaries with name, description, and inputSchema
    """
    # Last line of defence: whoever asks for the tool list gets a complete
    # one, whichever entry point started this process and whether or not it
    # remembered. Idempotent, so asking twice costs nothing.
    register_extension_tools()

    context = ServerContext.get_instance()
    mode = context._mode

    # For JUPYTER_SERVER mode, expose BOTH MCPServer tools AND jupyter-mcp-tools (when enabled)
    if mode == ServerMode.JUPYTER_SERVER:
        all_tools = []
        jupyter_tool_names = set()

        # Check if JupyterLab mode is enabled before loading jupyter-mcp-tools.
        # An empty allowlist enables no command, and jupyter-mcp-tools applies no filter
        # to an empty query, so asking would return every command.
        allowed_jupyter_mcp_tools = get_config().get_allowed_jupyter_mcp_tools()
        if server_context.is_jupyterlab_mode() and allowed_jupyter_mcp_tools:
            logger.info("JupyterLab mode enabled, loading selected jupyter-mcp-tools")

            # Get tools from jupyter-mcp-tools extension with caching
            try:
                from jupyter_mcp_tools import get_tools

                from jupyter_mcp_server.tool_cache import get_tool_cache

                # Get the base_url and token from the extension context, which is the object
                # that carries the ServerApp (handlers.py reads it the same way).
                extension_context = get_server_context()
                if extension_context.serverapp is not None:
                    # Use the actual Jupyter server connection URL
                    base_url = extension_context.serverapp.connection_url
                    token = extension_context.serverapp.token
                    logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                else:
                    # Fallback to configuration (for remote scenarios)
                    config = get_config()
                    base_url = config.code_sandbox_url if config.code_sandbox_url else "http://localhost:8888"
                    token = config.code_sandbox_token
                    logger.info(f"Using config code sandbox URL: {base_url}")

                logger.info(f"Querying jupyter-mcp-tools at {base_url}")

                # Define specific tools we want to load from jupyter-mcp-tools
                # (https://github.com/datalayer/jupyter-mcp-tools)
                # jupyter-mcp-tools exposes JupyterLab commands as MCP tools.
                # Only tools listed here will be available to MCP clients.
                # To add new tools, also update the list in handlers.py and
                # see docs/docs/reference/tools-jupyterlab/index.mdx for documentation.

                # Try querying with caching to avoid expensive repeated calls
                try:
                    search_query = ",".join(allowed_jupyter_mcp_tools)
                    logger.info(
                        f"Searching jupyter-mcp-tools with query: '{search_query}' (allowed_tools: {allowed_jupyter_mcp_tools})"
                    )

                    # Use cached get_tools to avoid expensive repeated calls
                    tool_cache = get_tool_cache()
                    tools_data = await tool_cache.get_tools(
                        base_url=base_url,
                        token=token,
                        query=search_query,
                        enabled_only=False,
                        fetch_func=get_tools,  # Pass the actual get_tools function for cache misses
                    )
                    logger.info(f"Query returned {len(tools_data)} tools (from cache or fresh)")

                    # Use the tools directly since query should return only what we want
                    for tool in tools_data:
                        logger.info(f"Found tool: {tool.get('id', '')}")

                except Exception as e:
                    logger.warning(f"Failed to load jupyter-mcp-tools: {e}")
                    tools_data = []

                logger.info(f"Successfully loaded {len(tools_data)} specific jupyter-mcp-tools")

                logger.info(f"Retrieved {len(tools_data)} tools from jupyter-mcp-tools extension")

                # Convert jupyter-mcp-tools format to MCP format
                for tool_data in tools_data:
                    tool_name = tool_data.get("id", "")
                    jupyter_tool_names.add(tool_name)

                    # Only include MCP protocol fields (exclude internal fields like commandId)
                    tool_dict = {
                        "name": tool_name,
                        "description": tool_data.get("caption", tool_data.get("label", "")),
                    }

                    # Convert parameters to inputSchema
                    # The parameters field contains the JSON Schema for the tool's arguments
                    params = tool_data.get("parameters", {})
                    if params and isinstance(params, dict) and params.get("properties"):
                        # Tool has parameters - use them as inputSchema
                        tool_dict["inputSchema"] = params
                        tool_dict["parameters"] = list(params["properties"].keys())
                        logger.debug(
                            f"Tool {tool_dict['name']} has parameters: {tool_dict['parameters']}"
                        )
                    else:
                        # Tool has no parameters - use empty schema
                        tool_dict["parameters"] = []
                        tool_dict["inputSchema"] = {
                            "type": "object",
                            "properties": {},
                            "description": tool_data.get("usage", ""),
                        }

                    all_tools.append(tool_dict)

                logger.info(
                    f"Converted {len(all_tools)} tool(s) from jupyter-mcp-tools with parameter schemas"
                )

            except Exception as e:
                logger.error(f"Error querying jupyter-mcp-tools extension: {e}", exc_info=True)
                # Continue to add MCPServer tools even if jupyter-mcp-tools fails
        else:
            logger.info(
                "Skipping jupyter-mcp-tools integration "
                f"(jupyterlab={server_context.is_jupyterlab_mode()}, "
                f"allowed={allowed_jupyter_mcp_tools})"
            )

        # Second, add MCPServer tools
        try:
            tools_list = await mcp.list_tools()
            logger.info(f"Retrieved {len(tools_list)} tools from MCPServer registry")

            for tool in tools_list:
                logger.info(f"Processing tool: {tool.name}, mode: {mode}")
                # Skip connect_to_jupyter tool when running as Jupyter extension
                # since it doesn't make sense to connect to a different server
                # when already running inside Jupyter
                if tool.name == "connect_to_jupyter":
                    logger.info("Skipping connect_to_jupyter tool in JUPYTER_SERVER mode")
                    continue

                # Add MCPServer tool
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description,
                }

                # Extract parameter names from inputSchema
                if tool.input_schema:
                    input_schema = tool.input_schema
                    if "properties" in input_schema:
                        tool_dict["parameters"] = list(input_schema["properties"].keys())
                    else:
                        tool_dict["parameters"] = []

                    # Include full inputSchema for MCP protocol compatibility
                    tool_dict["inputSchema"] = input_schema
                else:
                    tool_dict["parameters"] = []

                all_tools.append(tool_dict)

            logger.info(
                f"Added {len(all_tools) - len(jupyter_tool_names)} MCPServer tool(s), total: {len(all_tools)}"
            )

        except Exception as e:
            logger.error(f"Error retrieving MCPServer tools: {e}", exc_info=True)

        return all_tools

    # For MCP_SERVER mode, use local MCPServer registry
    # Use MCPServer's list_tools method which returns Tool objects
    tools_list = await mcp.list_tools()

    tools = []
    for tool in tools_list:
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
        }

        # Extract parameter names from inputSchema
        if tool.input_schema:
            input_schema = tool.input_schema
            if "properties" in input_schema:
                tool_dict["parameters"] = list(input_schema["properties"].keys())
            else:
                tool_dict["parameters"] = []

            # Include full inputSchema for MCP protocol compatibility
            tool_dict["inputSchema"] = input_schema
        else:
            tool_dict["parameters"] = []

        # Include full outputSchema for MCP protocol compatibility
        if tool.output_schema:
            tool_dict["outputSchema"] = tool.output_schema
        else:
            tool_dict["outputSchema"] = []

        tools.append(tool_dict)

    return tools


###############################################################################
# Extension registration.


def register_extension_tools() -> None:
    """Let installed extensions contribute their tools — after configuration.

    This used to run at module scope, which is earlier than it looks: the CLI
    imports this module in order to start the server, so extensions registered
    while the command line was still being parsed and before ``set_config``
    had been called. An extension asking "what am I pointed at?" was told
    "jupyter" however the server had been invoked, and the only way one could
    find out otherwise was to read ``sys.argv`` itself — which the
    Datalayer spaces extension had to do, and documented as a workaround
    waiting on exactly this change.

    Called after configuration by every entry point, and idempotent, so none
    of them has to know whether another got there first. Extensions are
    resolved through the ``jupyter_mcp_server.extensions`` entry-point group
    and coordinated by the reactor plugin platform.
    """
    extension_manager.register_tools(mcp, once=True)
