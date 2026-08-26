# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tornado request handlers for the Jupyter MCP Server extension.

This module provides handlers that bridge between Tornado (Jupyter Server) and
MCPServer, managing the MCP protocol lifecycle and request proxying.
"""

import json
import logging
from typing import Any

from jupyter_server.base.handlers import JupyterHandler
from tornado.web import HTTPError

from jupyter_mcp_server.__version__ import __version__
from jupyter_mcp_server.identity import (
    identity_from_jupyter_user,
    reset_current_identity,
    set_current_identity,
)
from jupyter_mcp_server.jupyter_extension.backends.local_backend import LocalBackend
from jupyter_mcp_server.jupyter_extension.backends.remote_backend import RemoteBackend
from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.utils import clean_mcp_response

logger = logging.getLogger(__name__)


async def _fetch_jupyter_tools(**kwargs):
    """Fetch jupyter-mcp-tools with the shorter timeout this transport wants.

    If the JupyterLab frontend is not loaded there is nothing to wait for, so
    tools/list should not sit here for the library default of 30 seconds.

    Defined at module level on purpose: ToolCache keys its in-flight fetches by
    fetcher as well as by query, so a function rebuilt per request would stop
    concurrent tools/list requests from sharing one call.
    """
    from jupyter_mcp_tools import get_tools

    return await get_tools(wait_timeout=5, **kwargs)


class MCPSSEHandler(JupyterHandler):
    """
    Handler for MCP protocol over Streamable HTTP.

    This handler implements the MCP transport by directly calling
    the registered MCP tools instead of trying to wrap the Starlette app.

    Authentication is enforced via JupyterHandler — clients must provide
    a valid Jupyter token (e.g. ``Authorization: token <TOKEN>``).
    Token-authenticated requests automatically bypass XSRF checking.
    """

    # Cache of jupyter_mcp_tools tool names for routing decisions
    _jupyter_tool_names = set()

    _identity_token = None

    async def prepare(self):
        """Require a valid Jupyter token for all /mcp requests.

        Whoever the identity provider resolved becomes the identity of this
        request, so a tool sees the same `Identity` here as it would in
        MCP_SERVER mode. A deployment that authenticates its own way supplies
        a Jupyter `IdentityProvider`; nothing below has to know.
        """
        await super().prepare()
        if not self.current_user:
            raise HTTPError(403, "Authentication required")
        self._identity_token = set_current_identity(
            identity_from_jupyter_user(self.current_user)
        )

    def on_finish(self):
        """Forget the identity when the request is over."""
        if self._identity_token is not None:
            reset_current_identity(self._identity_token)
            self._identity_token = None

    def set_default_headers(self):
        """Set headers for SSE responses."""
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")

    async def get(self):
        """Handle SSE connection establishment."""
        # Import here to avoid circular dependency

        # For now, just acknowledge the connection
        # The actual MCP protocol would be handled via POST
        self.write("event: connected\ndata: {}\n\n")
        await self.flush()

    async def post(self):
        """Handle MCP protocol messages."""
        # Import here to avoid circular dependency
        from jupyter_mcp_server.server import mcp

        try:
            # Parse the JSON-RPC request
            body = json.loads(self.request.body.decode("utf-8"))
            method = body.get("method")
            params = body.get("params", {})
            request_id = body.get("id")

            logger.info(f"MCP request: method={method}, id={request_id}")

            # Handle notifications (id is None) - these don't require a response per JSON-RPC 2.0
            # But in HTTP transport, we need to acknowledge the request
            if request_id is None:
                logger.info(f"Received notification: {method} - acknowledging without result")
                # Return empty response - the client should handle notifications without expecting a result
                # Some clients may send this as POST and expect HTTP 200 with no JSON-RPC response
                self.set_status(200)
                self.finish()
                return

            # Handle different MCP methods
            if method == "initialize":
                # Return server capabilities
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                        "serverInfo": {"name": "Jupyter MCP Server", "version": __version__},
                    },
                }
                logger.info(f"Sending initialize response: {response}")
            elif method == "tools/list":
                # List available tools from MCPServer and jupyter_mcp_tools
                from jupyter_mcp_server.server import mcp

                logger.info("Listing tools from MCPServer and jupyter_mcp_tools...")

                try:
                    # Get MCPServer tools first
                    tools_list = await mcp.list_tools()
                    logger.info(f"Got {len(tools_list)} tools from MCPServer")

                    # Track jupyter_mcp_tools tool names
                    jupyter_tool_names = set()

                    # Get tools from jupyter_mcp_tools extension first to identify duplicates
                    jupyter_tools_data = []
                    try:
                        from jupyter_mcp_server.tool_cache import get_tool_cache

                        # Get the server's base URL dynamically from ServerApp
                        context = get_server_context()
                        if context.serverapp is not None:
                            base_url = context.serverapp.connection_url
                            token = context.serverapp.token
                            logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                        else:
                            # Fallback to hardcoded localhost (should not happen in JUPYTER_SERVER mode)
                            port = self.settings.get("port", 8888)
                            base_url = f"http://localhost:{port}"
                            token = self.settings.get("token", None)
                            logger.warning(f"ServerApp not available, using fallback: {base_url}")

                        logger.info(f"Querying jupyter_mcp_tools at {base_url}")

                        # Check if JupyterLab mode is enabled before loading jupyter-mcp-tools.
                        # An empty allowlist enables no command, and jupyter-mcp-tools applies
                        # no filter to an empty query, so asking would return every command.
                        from jupyter_mcp_server.config import get_config

                        context = ServerContext.get_instance()
                        jupyterlab_enabled = context.is_jupyterlab_mode()
                        allowed_jupyter_mcp_tools = get_config().get_allowed_jupyter_mcp_tools()
                        logger.info(f"JupyterLab mode check: enabled={jupyterlab_enabled}")

                        if jupyterlab_enabled and allowed_jupyter_mcp_tools:
                            # Define specific tools we want to load from jupyter-mcp-tools
                            # (https://github.com/datalayer/jupyter-mcp-tools)
                            # jupyter-mcp-tools exposes JupyterLab commands as MCP tools.
                            # Only tools listed here will be available to MCP clients.
                            # To add new tools, also update the list in server.py and
                            # see docs/docs/reference/tools-jupyterlab/index.mdx for documentation.
                            logger.info(
                                f"Looking for specific jupyter-mcp-tools: {allowed_jupyter_mcp_tools}"
                            )

                            # Try querying with caching to avoid expensive repeated calls
                            try:
                                search_query = ",".join(allowed_jupyter_mcp_tools)
                                logger.info(
                                    f"Searching jupyter-mcp-tools with query: '{search_query}' (allowed_tools: {allowed_jupyter_mcp_tools})"
                                )

                                # Use cached get_tools to avoid expensive repeated calls
                                tool_cache = get_tool_cache()

                                jupyter_tools_data = await tool_cache.get_tools(
                                    base_url=base_url,
                                    token=token,
                                    query=search_query,
                                    enabled_only=False,
                                    ttl_seconds=180,  # 3 minutes for handlers (shorter than server.py)
                                    fetch_func=_fetch_jupyter_tools,  # module-level wrapper carrying wait_timeout=5
                                )
                                logger.info(
                                    f"Query returned {len(jupyter_tools_data)} tools (from cache or fresh)"
                                )

                                # Use the tools directly since query should return only what we want
                                for tool in jupyter_tools_data:
                                    logger.info(f"Found tool: {tool.get('id', '')}")
                            except Exception as e:
                                logger.warning(
                                    f"Failed to load jupyter-mcp-tools (this is normal if JupyterLab frontend is not loaded): {e}"
                                )
                                jupyter_tools_data = []

                            logger.info(
                                f"Successfully loaded {len(jupyter_tools_data)} specific jupyter-mcp-tools (requires JupyterLab frontend)"
                            )
                        else:
                            jupyter_tools_data = []
                            logger.info(
                                "Skipping jupyter-mcp-tools "
                                f"(jupyterlab={jupyterlab_enabled}, "
                                f"allowed={allowed_jupyter_mcp_tools})"
                            )

                        # Build set of jupyter tool names and cache it for routing decisions
                        jupyter_tool_names = {
                            tool_data.get("id", "") for tool_data in jupyter_tools_data
                        }
                        MCPSSEHandler._jupyter_tool_names = jupyter_tool_names
                        logger.info(
                            f"Cached {len(jupyter_tool_names)} jupyter_mcp_tools names for routing: {jupyter_tool_names}"
                        )

                    except Exception as jupyter_error:
                        # Log but don't fail - just return MCPServer tools
                        logger.warning(
                            f"Could not fetch tools from jupyter_mcp_tools: {jupyter_error}"
                        )

                    # Convert MCPServer tools to MCP protocol format
                    tools = []
                    for tool in tools_list:
                        # Skip connect_to_jupyter tool when running as Jupyter extension
                        # since it doesn't make sense to connect to a different server
                        # when already running inside Jupyter
                        from jupyter_mcp_server.tools import ServerMode

                        context = ServerContext.get_instance()
                        context.initialize()
                        mode = context._mode

                        if tool.name == "connect_to_jupyter" and mode == ServerMode.JUPYTER_SERVER:
                            logger.info("Skipping connect_to_jupyter tool in JUPYTER_SERVER mode")
                            continue

                        tools.append(
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "inputSchema": tool.input_schema,
                            }
                        )

                    # Now add jupyter_mcp_tools
                    for tool_data in jupyter_tools_data:
                        # Only include MCP protocol fields (exclude internal fields like commandId)
                        tool_dict = {
                            "name": tool_data.get("id", ""),
                            "description": tool_data.get("caption", tool_data.get("label", "")),
                        }

                        # Convert parameters to inputSchema
                        # The parameters field contains the JSON Schema for the tool's arguments
                        params = tool_data.get("parameters", {})
                        if params and isinstance(params, dict) and params.get("properties"):
                            # Tool has parameters - use them as inputSchema
                            tool_dict["inputSchema"] = params
                            logger.debug(
                                f"Tool {tool_dict['name']} has parameters: {list(params.get('properties', {}).keys())}"
                            )
                        else:
                            # Tool has no parameters - use empty schema
                            tool_dict["inputSchema"] = {
                                "type": "object",
                                "properties": {},
                                "description": tool_data.get("usage", ""),
                            }

                        tools.append(tool_dict)

                    logger.info(f"Added {len(jupyter_tools_data)} tool(s) from jupyter_mcp_tools")

                    logger.info(f"Returning total of {len(tools)} tools")

                    response = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
                except Exception as e:
                    logger.error(f"Error listing tools: {e}", exc_info=True)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error listing tools: {e!s}",
                        },
                    }
            elif method == "tools/call":
                # Execute a tool
                from jupyter_mcp_server.server import mcp

                tool_name = params.get("name")
                tool_arguments = params.get("arguments", {})

                logger.info(f"Calling tool: {tool_name}")

                try:
                    # Check if this is a jupyter_mcp_tools tool
                    # Use the cached set of jupyter tool names from tools/list
                    if tool_name in MCPSSEHandler._jupyter_tool_names:
                        # Route to jupyter_mcp_tools extension via HTTP execute endpoint
                        logger.info(
                            f"Routing {tool_name} to jupyter_mcp_tools extension (recognized from cache)"
                        )

                        # Get server configuration from ServerApp
                        context = get_server_context()
                        if context.serverapp is not None:
                            base_url = context.serverapp.connection_url
                            token = context.serverapp.token
                            logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                        else:
                            # Fallback to hardcoded localhost (should not happen in JUPYTER_SERVER mode)
                            port = self.settings.get("port", 8888)
                            base_url = f"http://localhost:{port}"
                            token = self.settings.get("token", None)
                            logger.warning(f"ServerApp not available, using fallback: {base_url}")

                        # Use the MCPToolsClient to execute the tool
                        from jupyter_mcp_tools.client import MCPToolsClient

                        try:
                            async with MCPToolsClient(base_url=base_url, token=token) as client:
                                execution_result = await client.execute_tool(
                                    tool_id=tool_name, parameters=tool_arguments
                                )

                                if execution_result.get("success"):
                                    result_data = execution_result.get("result", {})
                                    result_text = (
                                        str(result_data)
                                        if result_data
                                        else "Tool executed successfully"
                                    )
                                    result_dict = {
                                        "content": [{"type": "text", "text": result_text}]
                                    }
                                else:
                                    error_msg = execution_result.get("error", "Unknown error")
                                    result_dict = {
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": f"Error executing tool: {error_msg}",
                                            }
                                        ],
                                        "isError": True,
                                    }
                        except Exception as exec_error:
                            logger.error(f"Error executing {tool_name}: {exec_error}")
                            result_dict = {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Failed to execute tool: {exec_error!s}",
                                    }
                                ],
                                "isError": True,
                            }
                    else:
                        # Use MCPServer's call_tool method for regular tools
                        logger.info(
                            f"Routing {tool_name} to MCPServer (not in jupyter_mcp_tools cache)"
                        )
                        result = await mcp.call_tool(tool_name, tool_arguments)

                        # A `CallToolResult`. Put it on the wire the way the SDK
                        # does: camelCase keys, nothing null. `resultType` is
                        # left out because it belongs to a newer protocol
                        # revision than the one this handler announces.
                        result_dict = clean_mcp_response(
                            result.model_dump(
                                by_alias=True,
                                mode="json",
                                exclude_none=True,
                                exclude={"result_type"},
                            )
                        )

                    logger.info("Converted result to dict")

                    response = {"jsonrpc": "2.0", "id": request_id, "result": result_dict}
                except Exception as e:
                    logger.error(f"Error calling tool: {e}", exc_info=True)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": f"Internal error calling tool: {e!s}"},
                    }
            elif method == "prompts/list":
                # List available prompts - return empty list if no prompts defined
                logger.info("Listing prompts...")
                response = {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
            elif method == "resources/list":
                # List available resources - return empty list if no resources defined
                logger.info("Listing resources...")
                response = {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
            else:
                # Method not supported
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            # Send response
            self.set_header("Content-Type", "application/json")
            logger.info(f"Sending response: {json.dumps(response)[:200]}...")
            self.write(json.dumps(response))
            self.finish()

        except Exception as e:
            logger.error(f"Error handling MCP request: {e}", exc_info=True)
            self.set_status(500)
            self.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id") if "body" in locals() else None,
                        "error": {"code": -32603, "message": str(e)},
                    }
                )
            )
            self.finish()


class MCPHandler(JupyterHandler):
    """Base handler for MCP endpoints with common functionality.

    Requires a valid Jupyter token for all requests (GET and POST).
    """

    _identity_token = None

    async def prepare(self):
        """Enforce Jupyter token authentication.

        As in `MCPSSEHandler`, the resolved user becomes the identity of the
        request so that both modes present tools with the same thing.
        """
        await super().prepare()
        if not self.current_user:
            raise self._custom_403()
        self._identity_token = set_current_identity(
            identity_from_jupyter_user(self.current_user)
        )

    def on_finish(self):
        """Forget the identity when the request is over."""
        if self._identity_token is not None:
            reset_current_identity(self._identity_token)
            self._identity_token = None

    def _custom_403(self):
        from tornado.web import HTTPError

        return HTTPError(403, "Authentication required")

    def get_backend(self):
        """
        Get the appropriate backend based on configuration.

        Returns:
            Backend instance (LocalBackend or RemoteBackend)
        """
        context = get_server_context()

        # Check if we should use local backend
        if context.is_local_document() or context.is_local_code_sandbox():
            return LocalBackend(context.serverapp)
        else:
            # Use remote backend
            document_url = self.settings.get("mcp_document_url")
            document_token = self.settings.get("mcp_document_token", "")
            code_sandbox_url = self.settings.get("mcp_code_sandbox_url")
            code_sandbox_token = self.settings.get("mcp_code_sandbox_token", "")

            return RemoteBackend(
                document_url=document_url,
                document_token=document_token,
                code_sandbox_url=code_sandbox_url,
                code_sandbox_token=code_sandbox_token,
            )

    def set_default_headers(self):
        """Set response headers for MCP endpoints."""
        self.set_header("Content-Type", "application/json")


class MCPHealthHandler(MCPHandler):
    """
    Health check endpoint.

    GET /mcp/healthz
    """

    def get(self):
        """Handle health check request."""
        context = get_server_context()

        health_info = {
            "status": "healthy",
            "context_type": context.context_type,
            "document_url": context.document_url or self.settings.get("mcp_document_url"),
            "code_sandbox_url": context.code_sandbox_url or self.settings.get("mcp_code_sandbox_url"),
            "extension": "jupyter_mcp_server",
            "version": "0.20.0",
        }

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(health_info))
        self.finish()


class MCPToolsListHandler(MCPHandler):
    """
    List available MCP tools.

    GET /mcp/tools/list
    """

    async def get(self):
        """Return list of available tools dynamically from the tool registry."""
        # Import here to avoid circular dependency
        from jupyter_mcp_server.server import get_registered_tools

        # Get tools dynamically from the MCP server registry
        tools = await get_registered_tools()

        response = {"tools": tools, "count": len(tools)}

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(response))
        self.finish()


class MCPToolsCallHandler(MCPHandler):
    """
    Execute an MCP tool.

    POST /mcp/tools/call
    Body: {"tool_name": "...", "arguments": {...}}
    """

    async def post(self):
        """Handle tool execution request."""
        try:
            # Parse request body
            body = json.loads(self.request.body.decode("utf-8"))
            tool_name = body.get("tool_name")
            arguments = body.get("arguments", {})

            if not tool_name:
                self.set_status(400)
                self.write(json.dumps({"error": "tool_name is required"}))
                self.finish()
                return

            logger.info(f"Executing tool: {tool_name} with args: {arguments}")

            # Get backend
            backend = self.get_backend()

            # Execute tool based on name
            # For now, return a placeholder response
            # TODO: Implement actual tool routing
            result = await self._execute_tool(tool_name, arguments, backend)

            response = {"success": True, "result": result}

            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(response))
            self.finish()

        except Exception as e:
            logger.error(f"Error executing tool: {e}", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"success": False, "error": str(e)}))
            self.finish()

    async def _execute_tool(self, tool_name: str, arguments: dict[str, Any], backend):
        """
        Route tool execution to appropriate implementation.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            backend: Backend instance

        Returns:
            Tool execution result
        """
        # TODO: Implement actual tool routing
        # For now, return a simple response

        if tool_name == "list_notebooks":
            notebooks = await backend.list_notebooks()
            return {"notebooks": notebooks}

        # Placeholder for other tools
        return f"Tool {tool_name} executed with backend {type(backend).__name__}"
