# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Core adapter logic for translating between HTTP and MCP protocols."""

import json
import asyncio
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from contextlib import AsyncExitStack

from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client

from .models import (
    MCPError, Tool, ToolCallResponse, ContentItem, 
    InitializeResponse, MCPCapabilities
)

# Import the embedded MCP server
from jupyter_mcp_server.server import mcp as embedded_mcp_server
from jupyter_mcp_server.config import get_config, set_config


class InternalJupyterClient:
    """A client that accesses Jupyter server APIs directly without HTTP calls."""
    
    def __init__(self, server_app):
        self.server_app = server_app
        self.contents_manager = server_app.contents_manager
        self.kernel_manager = server_app.kernel_manager
        
    async def list_notebooks(self, path=""):
        """List notebooks using internal content manager."""
        try:
            notebooks = []
            contents = await self.contents_manager.get(path)
            
            if contents['type'] == 'directory':
                for item in contents['content']:
                    if item['type'] == 'directory':
                        # Recursively search subdirectories
                        sub_notebooks = await self.list_notebooks(item['path'])
                        notebooks.extend(sub_notebooks)
                    elif item['type'] == 'notebook':
                        notebooks.append(item['path'])
            
            return notebooks
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error listing notebooks: {e}")
            return []
    
    async def list_all_content(self, path="", max_depth=3, current_depth=0):
        """List all files and directories using internal content manager."""
        try:
            files = []
            
            if current_depth > max_depth:
                return files
                
            contents = await self.contents_manager.get(path)
            
            if contents['type'] == 'directory':
                for item in contents['content']:
                    full_path = item['path']
                    
                    # Format size
                    size_str = ""
                    if item.get('size'):
                        size = item['size']
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024 * 1024:
                            size_str = f"{size // 1024}KB"
                        else:
                            size_str = f"{size // (1024 * 1024)}MB"
                    
                    # Format last modified
                    last_modified = ""
                    if item.get('last_modified'):
                        last_modified = item['last_modified']
                    
                    files.append({
                        'path': full_path,
                        'type': item['type'],
                        'size': size_str,
                        'last_modified': last_modified
                    })
                    
                    # Recursively explore directories
                    if item['type'] == 'directory':
                        sub_files = await self.list_all_content(full_path, max_depth, current_depth + 1)
                        files.extend(sub_files)
            
            return files
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error listing content: {e}")
            return []
    
    async def get_notebook_content(self, notebook_path):
        """Get notebook content using internal content manager."""
        try:
            content = await self.contents_manager.get(notebook_path)
            if content['type'] != 'notebook':
                raise ValueError(f"File {notebook_path} is not a notebook")
            return content['content']
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting notebook content: {e}")
            raise
    
    async def save_notebook_content(self, notebook_path, notebook_content):
        """Save notebook content using internal content manager."""
        try:
            model = {
                'type': 'notebook',
                'content': notebook_content,
                'format': 'json'
            }
            await self.contents_manager.save(model, notebook_path)
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving notebook content: {e}")
            return False
    
    async def create_notebook(self, path):
        """Create new notebook using internal content manager."""
        try:
            model = {
                'type': 'notebook'
            }
            result = await self.contents_manager.new(model, path)
            return result['path']
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating notebook: {e}")
            raise
    
    async def delete_notebook(self, path):
        """Delete notebook using internal content manager."""
        try:
            await self.contents_manager.delete(path)
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting notebook: {e}")
            return False
    
    async def rename_notebook(self, old_path, new_path):
        """Rename notebook using internal content manager."""
        try:
            result = await self.contents_manager.rename(old_path, new_path)
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error renaming notebook: {e}")
            return False


class MCPSessionManager:
    """Manages MCP client sessions for HTTP clients."""
    
    def __init__(self, mcp_server_url: str):
        self.mcp_server_url = mcp_server_url
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stacks: Dict[str, AsyncExitStack] = {}
        
    async def create_session(self, session_id: str) -> ClientSession:
        """Create a new MCP client session."""
        if session_id in self.sessions:
            return self.sessions[session_id]
            
        exit_stack = AsyncExitStack()
        self.exit_stacks[session_id] = exit_stack
        
        try:
            # Connect to MCP server
            streams_context = streamablehttp_client(f"{self.mcp_server_url}/mcp")
            read_stream, write_stream, _ = await exit_stack.enter_async_context(streams_context)
            
            # Create session
            session_context = ClientSession(read_stream, write_stream)
            session = await exit_stack.enter_async_context(session_context)
            
            # Initialize session
            await session.initialize()
            
            self.sessions[session_id] = session
            return session
            
        except Exception as e:
            await exit_stack.aclose()
            if session_id in self.exit_stacks:
                del self.exit_stacks[session_id]
            raise e
    
    async def close_session(self, session_id: str):
        """Close an MCP client session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.exit_stacks:
            await self.exit_stacks[session_id].aclose()
            del self.exit_stacks[session_id]
    
    async def get_session(self, session_id: str) -> Optional[ClientSession]:
        """Get an existing session or create a new one."""
        if session_id not in self.sessions:
            return await self.create_session(session_id)
        return self.sessions[session_id]


class EmbeddedMCPAdapter:
    """Adapter that uses embedded MCP server directly without external connections."""
    
    def __init__(self, jupyter_server_app=None):
        self.jupyter_server_app = jupyter_server_app
        self.sessions: Dict[str, str] = {}  # Simple session tracking
        
        # Configure the embedded MCP server with Jupyter server details
        if jupyter_server_app:
            self._configure_embedded_server()
    
    def _configure_embedded_server(self):
        """Configure the embedded MCP server with Jupyter server information."""
        try:
            # Get Jupyter server details
            server_url = "http://localhost:8888"  # Default fallback
            token = "MY_TOKEN"  # Default fallback
            
            if hasattr(self.jupyter_server_app, 'port'):
                server_url = f"http://localhost:{self.jupyter_server_app.port}"
            if hasattr(self.jupyter_server_app, 'token') and self.jupyter_server_app.token:
                token = self.jupyter_server_app.token
            
            # Configure the embedded MCP server using set_config
            from jupyter_mcp_server.config import set_config
            set_config(
                document_url=server_url,
                document_id="notebook.ipynb", 
                document_token=token,
                runtime_url=server_url,
                start_new_runtime=True,
                runtime_token=token
            )
            
            # Store jupyter server app reference for direct access
            self._jupyter_server_app = self.jupyter_server_app
            
            # Create internal client for direct server access
            internal_client = InternalJupyterClient(self.jupyter_server_app)
            
            # Pass internal client to embedded MCP server
            embedded_mcp_server._internal_client = internal_client
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Configured embedded MCP server: server_url={server_url}, token=***")
            
        except Exception as e:
            # Log error but continue - use defaults
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Failed to configure embedded MCP server: %s", e)
    
    async def initialize_session(self) -> str:
        """Initialize a new session and return session ID."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = session_id
        return session_id
    
    async def get_server_info(self, session_id: str) -> Dict[str, Any]:
        """Get server information for the session."""
        return {
            "name": "jupyter-mcp-server-embedded",
            "version": "1.0.0",
            "description": "Embedded Jupyter MCP Server"
        }
    
    async def get_or_create_session(self) -> str:
        """Get or create a session and return session ID."""
        # For simplicity, always create a new session or reuse the default one
        session_id = "default-session"
        if session_id not in self.sessions:
            self.sessions[session_id] = session_id
        return session_id
    
    async def get_capabilities(self, session_id: str) -> Dict[str, Any]:
        """Get capabilities for the session."""
        return {
            "tools": {"listChanged": True},
            "resources": {},
            "prompts": {},
            "logging": {}
        }
    
    async def initialize(self, session_id: str, client_info: Dict[str, Any]) -> InitializeResponse:
        """Initialize MCP session and return capabilities."""
        # Store session
        self.sessions[session_id] = session_id
        
        try:
            # Get tools from embedded server
            tools_list = embedded_mcp_server.list_tools()
            
            capabilities = MCPCapabilities(
                tools={"listChanged": True},
                resources={},
                prompts={},
                logging={}
            )
            
            server_info = {
                "name": "jupyter-mcp-server-embedded",
                "version": "1.0.0",
                "description": "Embedded Jupyter MCP Server"
            }
            
            return InitializeResponse(
                protocolVersion="2025-03-26",
                capabilities=capabilities,
                serverInfo=server_info
            )
            
        except Exception as e:
            raise Exception(f"Failed to initialize embedded MCP session: {str(e)}")
    
    async def list_tools(self, session_id: str, cursor: Optional[str] = None) -> Tuple[List[Tool], Optional[str]]:
        """List available MCP tools from embedded server."""
        if session_id not in self.sessions:
            raise Exception("Session not found")
        
        try:
            # Get tools from the embedded MCP server
            mcp_tools = await embedded_mcp_server.list_tools()
            
            # Convert MCP tools to our Tool format
            tools = []
            for mcp_tool in mcp_tools:
                tools.append(Tool(
                    name=mcp_tool.name,
                    description=mcp_tool.description or "",
                    inputSchema=mcp_tool.inputSchema or {"type": "object", "properties": {}},
                    annotations=getattr(mcp_tool, 'annotations', None)
                ))
            
            return tools, None  # No pagination for now
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise Exception(f"Failed to list tools: {str(e)}")
    
    async def call_tool(self, session_id: str, tool_name: str, arguments: Dict[str, Any]) -> ToolCallResponse:
        """Call an MCP tool on the embedded server."""
        if session_id not in self.sessions:
            raise Exception("Session not found")
        
        try:
            # Use the embedded MCP server's call_tool method
            result = await embedded_mcp_server.call_tool(tool_name, arguments)
            
            # Convert result to HTTP response format
            content_items = []
            
            # Handle MCP result format (which is typically a list of content items)
            if isinstance(result, list):
                for item in result:
                    if hasattr(item, 'type') and hasattr(item, 'text'):
                        # MCP TextContent object
                        content_items.append(ContentItem(
                            type=item.type,
                            text=item.text
                        ))
                    elif hasattr(item, 'type') and hasattr(item, 'data'):
                        # MCP ImageContent object
                        content_items.append(ContentItem(
                            type=item.type,
                            data=getattr(item, 'data', None),
                            mimeType=getattr(item, 'mimeType', None)
                        ))
                    elif isinstance(item, dict):
                        # Dict-like content
                        if 'type' in item and item['type'] == 'text':
                            content_items.append(ContentItem(
                                type="text",
                                text=item.get('text', str(item))
                            ))
                        else:
                            content_items.append(ContentItem(
                                type="text",
                                text=json.dumps(item, indent=2)
                            ))
                    elif isinstance(item, str):
                        content_items.append(ContentItem(
                            type="text", 
                            text=item
                        ))
                    else:
                        content_items.append(ContentItem(
                            type="text",
                            text=str(item)
                        ))
            elif isinstance(result, str):
                content_items.append(ContentItem(
                    type="text",
                    text=result
                ))
            elif isinstance(result, dict):
                content_items.append(ContentItem(
                    type="text",
                    text=json.dumps(result, indent=2)
                ))
            else:
                content_items.append(ContentItem(
                    type="text",
                    text=str(result)
                ))
            
            return ToolCallResponse(
                content=content_items,
                isError=False
            )
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            # Return error response
            return ToolCallResponse(
                content=[ContentItem(
                    type="text",
                    text=f"Error calling tool '{tool_name}': {str(e)}"
                )],
                isError=True
            )


class MCPAdapter:
    """Adapter class that translates between HTTP and MCP protocols."""
    
    def __init__(self, mcp_server_url: str = "http://localhost:4040"):
        self.mcp_server_url = mcp_server_url
        self.session_manager = MCPSessionManager(mcp_server_url)
        
    async def initialize(self, session_id: str, client_info: Dict[str, Any]) -> InitializeResponse:
        """Initialize MCP session and return capabilities."""
        session = await self.session_manager.get_session(session_id)
        
        # Get server capabilities by listing tools (this triggers capability negotiation)
        try:
            tools_response = await session.list_tools()
            
            capabilities = MCPCapabilities(
                tools={"listChanged": True},
                resources={},
                prompts={},
                logging={}
            )
            
            server_info = {
                "name": "jupyter-mcp-server-http-adapter",
                "version": "1.0.0",
                "description": "HTTP adapter for Jupyter MCP Server"
            }
            
            return InitializeResponse(
                protocolVersion="2025-03-26",
                capabilities=capabilities,
                serverInfo=server_info
            )
            
        except Exception as e:
            raise Exception(f"Failed to initialize MCP session: {str(e)}")
    
    async def list_tools(self, session_id: str, cursor: Optional[str] = None) -> Tuple[List[Tool], Optional[str]]:
        """List available MCP tools."""
        session = await self.session_manager.get_session(session_id)
        
        if not session:
            raise Exception("Session not found")
        
        try:
            tools_response = await session.list_tools()
            
            tools = []
            for tool in tools_response.tools:
                tools.append(Tool(
                    name=tool.name,
                    description=tool.description or "",
                    inputSchema=tool.inputSchema or {"type": "object"},
                    annotations=getattr(tool, 'annotations', None)
                ))
            
            # For now, we don't implement pagination cursor logic
            # This can be enhanced later based on MCP server response
            next_cursor = None
            
            return tools, next_cursor
            
        except Exception as e:
            raise Exception(f"Failed to list tools: {str(e)}")
    
    async def call_tool(self, session_id: str, tool_name: str, arguments: Dict[str, Any]) -> ToolCallResponse:
        """Call an MCP tool and return the response."""
        session = await self.session_manager.get_session(session_id)
        
        if not session:
            raise Exception("Session not found")
        
        try:
            result = await session.call_tool(tool_name, arguments=arguments)
            
            # Convert MCP result to HTTP response format
            content_items = []
            
            if hasattr(result, 'content') and result.content:
                for item in result.content:
                    if isinstance(item, types.TextContent):
                        content_items.append(ContentItem(
                            type="text",
                            text=item.text
                        ))
                    elif isinstance(item, types.ImageContent):
                        content_items.append(ContentItem(
                            type="image",
                            data=item.data,
                            mimeType=item.mimeType
                        ))
                    elif hasattr(item, 'type') and item.type == 'text':
                        # Handle dict-like text content
                        content_items.append(ContentItem(
                            type="text",
                            text=getattr(item, 'text', str(item))
                        ))
                    else:
                        # Fallback: convert to text
                        content_items.append(ContentItem(
                            type="text",
                            text=str(item)
                        ))
            
            # Handle structured content from server.py tools
            elif hasattr(result, 'structuredContent'):
                structured = result.structuredContent
                if isinstance(structured, dict):
                    content_items.append(ContentItem(
                        type="text",
                        text=json.dumps(structured, indent=2)
                    ))
                else:
                    content_items.append(ContentItem(
                        type="text",
                        text=str(structured)
                    ))
            
            # If no content, try to extract text from result directly
            if not content_items and hasattr(result, 'text'):
                content_items.append(ContentItem(
                    type="text",
                    text=result.text
                ))
            elif not content_items:
                # Last resort: stringify the result
                content_items.append(ContentItem(
                    type="text",
                    text=str(result) if result else "[No content]"
                ))
            
            is_error = getattr(result, 'isError', False)
            
            return ToolCallResponse(
                content=content_items,
                isError=is_error
            )
            
        except Exception as e:
            # Return error as tool result
            return ToolCallResponse(
                content=[ContentItem(
                    type="text",
                    text=f"Tool execution failed: {str(e)}"
                )],
                isError=True
            )
    
    async def get_capabilities(self, session_id: str) -> MCPCapabilities:
        """Get server capabilities."""
        # For now, return static capabilities
        # This could be enhanced to query the actual MCP server
        return MCPCapabilities(
            tools={"listChanged": True},
            resources={},
            prompts={},
            logging={}
        )
    
    async def cleanup_session(self, session_id: str):
        """Clean up a session."""
        await self.session_manager.close_session(session_id)
    
    async def initialize_session(self) -> str:
        """Initialize a new MCP session and return session ID."""
        session_id = generate_session_id()
        await self.session_manager.create_session(session_id)
        return session_id
    
    async def get_or_create_session(self) -> str:
        """Get or create a default session."""
        # For simplicity, use a default session ID
        session_id = "default"
        if session_id not in self.session_manager.sessions:
            await self.session_manager.create_session(session_id)
        return session_id
    
    async def get_server_info(self, session_id: str) -> Dict[str, Any]:
        """Get server information and capabilities."""
        session = await self.session_manager.get_session(session_id)
        
        if not session:
            raise Exception("Session not found")
        
        # Return server info
        return {
            "name": "jupyter-mcp-server",
            "version": "0.14.0",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {},
                "prompts": {},
                "logging": {}
            }
        }


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())


def http_status_from_mcp_error(error_code: int) -> int:
    """Map MCP error codes to HTTP status codes."""
    error_mapping = {
        -32700: 400,  # Parse error -> Bad Request
        -32600: 400,  # Invalid Request -> Bad Request
        -32601: 404,  # Method not found -> Not Found
        -32602: 400,  # Invalid params -> Bad Request
        -32603: 500,  # Internal error -> Internal Server Error
        -32000: 409,  # Tool error -> Conflict
    }
    return error_mapping.get(error_code, 500)
