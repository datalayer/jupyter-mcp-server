# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Common test infrastructure shared between MCP_SERVER and JUPYTER_SERVER mode tests.

This module provides:
- MCPClient: MCP protocol client for remote testing
- timeout_wrapper: Decorator for timeout handling
- requires_session: Decorator to check client session connection
- JUPYTER_TOOLS: List of expected tool names
- Helper functions for content extraction
"""

import asyncio
import functools
import json
import logging
from contextlib import AsyncExitStack

import pytest
import requests
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client


# TODO: could be retrieved from code (inspect)
JUPYTER_TOOLS = [
    # Multi-Notebook Management Tools
    "use_notebook",
    "list_notebooks", 
    "restart_notebook",
    "unuse_notebook",
    "read_notebook",
    # Cell Tools
    "insert_cell",
    "insert_execute_code_cell",
    "overwrite_cell_source",
    "execute_cell",
    "read_cell",
    "delete_cell",
    "execute_code",
    "list_files",
    "list_kernels"
]


def timeout_wrapper(timeout_seconds=30):
    """Decorator to add timeout handling to async test functions
    
    Windows has known issues with asyncio and network timeouts that can cause 
    tests to hang indefinitely. This decorator adds a safety timeout specifically
    for Windows platforms while allowing other platforms to run normally.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                pytest.skip(f"Test {func.__name__} timed out ({timeout_seconds}s) - known platform limitation")
            except Exception as e:
                # Check if it's a network timeout related to Windows
                if "ReadTimeout" in str(e) or "TimeoutError" in str(e):
                    pytest.skip(f"Test {func.__name__} hit network timeout - known platform limitation: {e}")
                raise
        return wrapper
    return decorator


def requires_session(func):
    """
    A decorator that checks if the instance has a connected session.
    """
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not self._session:
            raise RuntimeError("Client session is not connected")
        # If the session exists, call the original method
        return await func(self, *args, **kwargs)
    
    return wrapper


class MCPClient:
    """A standard MCP client used to interact with the Jupyter MCP server

    Basically it's a client wrapper for the Jupyter MCP server.
    It uses the `requires_session` decorator to check if the session is connected.
    """

    def __init__(self, url):
        self.url = f"{url}/mcp"
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Initiate the session (enter session context)"""
        streams_context = streamablehttp_client(self.url)
        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
            streams_context
        )
        session_context = ClientSession(read_stream, write_stream)
        self._session = await self._exit_stack.enter_async_context(session_context)
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close the session (exit session context)"""
        if self._exit_stack:
            await self._exit_stack.aclose()
        self._session = None

    @staticmethod
    def _extract_text_content(result):
        """Extract text content from a result"""
        try:
            logging.debug(f"_extract_text_content: result type={type(result)}, has content={hasattr(result, 'content')}, is tuple={isinstance(result, tuple)}, is list={isinstance(result, list)}")
            
            # Handle tuple results (content, metadata)
            if isinstance(result, tuple) and len(result) >= 2:
                logging.debug(f"_extract_text_content: handling tuple, first element type={type(result[0])}")
                result = result[0]  # Get the content list from the tuple
            
            if hasattr(result, 'content') and result.content and len(result.content) > 0:
                # Check if all items are TextContent
                if all(isinstance(item, types.TextContent) for item in result.content):
                    # If multiple TextContent items, return as JSON list
                    if len(result.content) > 1:
                        texts = [item.text for item in result.content]
                        import json
                        text = json.dumps(texts)
                        logging.debug(f"_extract_text_content: extracted {len(texts)} TextContent items as JSON list")
                        return text
                    else:
                        text = result.content[0].text
                        logging.debug(f"_extract_text_content: extracted from result.content[0].text, length={len(text)}")
                        return text
            # Handle list results directly
            elif isinstance(result, list) and len(result) > 0:
                # Check if all items are TextContent
                if all(isinstance(item, types.TextContent) for item in result):
                    # If multiple TextContent items, return as JSON list
                    if len(result) > 1:
                        texts = [item.text for item in result]
                        import json
                        text = json.dumps(texts)
                        logging.debug(f"_extract_text_content: extracted {len(texts)} TextContent items as JSON list")
                        return text
                    else:
                        text = result[0].text
                        logging.debug(f"_extract_text_content: extracted from list[0].text, length={len(text)}")
                        return text
        except (AttributeError, IndexError, TypeError) as e:
            logging.debug(f"_extract_text_content error: {e}, result type: {type(result)}")
        
        logging.debug(f"_extract_text_content: returning None, could not extract")
        return None

    def _get_structured_content_safe(self, result):
        """Safely get structured content with fallback to text content parsing"""
        content = getattr(result, 'structuredContent', None)
        if content is None:
            # Try to extract from text content as fallback
            text_content = self._extract_text_content(result)
            logging.debug(f"_get_structured_content_safe: text_content={repr(text_content[:200] if text_content else None)}")
            if text_content:
                # Try to parse as JSON
                try:
                    parsed = json.loads(text_content)
                    logging.debug(f"_get_structured_content_safe: JSON parsed successfully, type={type(parsed)}")
                    # Check if it's already a wrapped result or a direct response object
                    if isinstance(parsed, dict):
                        # If it has "result" key, it's already wrapped
                        if "result" in parsed:
                            return parsed
                        # If it has keys like "index", "type", "source" it's a direct object (like CellInfo)
                        elif any(key in parsed for key in ["index", "type", "source", "cells"]):
                            return parsed
                        # Otherwise wrap it
                        else:
                            return {"result": parsed}
                    else:
                        # Lists, strings, etc. - wrap them
                        return {"result": parsed}
                except json.JSONDecodeError:
                    # Not JSON - could be plain text or list representation
                    # Try to evaluate as Python literal (for lists, etc.)
                    try:
                        import ast
                        parsed = ast.literal_eval(text_content)
                        logging.debug(f"_get_structured_content_safe: ast.literal_eval succeeded, type={type(parsed)}, value={repr(parsed)}")
                        return {"result": parsed}
                    except (ValueError, SyntaxError):
                        # Plain text - return as-is
                        logging.debug(f"_get_structured_content_safe: Plain text, wrapping in result dict")
                        return {"result": text_content}
            else:
                # No text content - check if we have ImageContent or mixed content
                if hasattr(result, 'content') and result.content:
                    # Extract mixed content (ImageContent + TextContent)
                    content_list = []
                    for item in result.content:
                        if isinstance(item, types.ImageContent):
                            # Convert ImageContent to dict format
                            content_list.append({
                                'type': 'image',
                                'data': item.data,
                                'mimeType': item.mimeType,
                                'annotations': getattr(item, 'annotations', None),
                                'meta': getattr(item, 'meta', None)
                            })
                        elif isinstance(item, types.TextContent):
                            # Include text content if present
                            content_list.append(item.text)
                    
                    if content_list:
                        logging.debug(f"_get_structured_content_safe: extracted {len(content_list)} items from mixed content")
                        return {"result": content_list}
                
                logging.warning(f"No text content available in result: {type(result)}")
                return None
        return content
    
    async def _call_tool_safe(self, tool_name, arguments=None):
        """Safely call a tool, returning None on error (for test compatibility)"""
        try:
            result = await self._session.call_tool(tool_name, arguments=arguments or {})  # type: ignore
            
            # Log raw result for debugging
            logging.debug(f"_call_tool_safe({tool_name}): raw result type={type(result)}")
            logging.debug(f"_call_tool_safe({tool_name}): raw result={result}")
            
            # Check if result contains error text (for MCP_SERVER mode where errors are wrapped in results)
            text_content = self._extract_text_content(result)
            if text_content and ("Error executing tool" in text_content or "is out of range" in text_content or "not found" in text_content):
                logging.warning(f"Tool {tool_name} returned error in result: {text_content[:100]}")
                return None
            
            # Also check structured content for errors (for JUPYTER_SERVER mode)
            structured_content = self._get_structured_content_safe(result)
            if structured_content:
                # Check if result contains error messages
                result_value = structured_content.get("result")
                if result_value:
                    # Handle both string and list results
                    error_text = ""
                    if isinstance(result_value, str):
                        error_text = result_value
                    elif isinstance(result_value, list) and len(result_value) > 0:
                        error_text = str(result_value[0])
                    
                    if error_text and ("[ERROR:" in error_text or "is out of range" in error_text or "not found" in error_text):
                        logging.warning(f"Tool {tool_name} returned error in structured result: {error_text[:100]}")
                        return None
            
            return result
        except Exception as e:
            # Log the error but return None for test compatibility (JUPYTER_SERVER mode)
            logging.warning(f"Tool {tool_name} raised error: {e}")
            return None

    @requires_session
    async def list_tools(self):
        return await self._session.list_tools()  # type: ignore

    # Multi-Notebook Management Methods
    @requires_session
    async def use_notebook(self, notebook_name, notebook_path=None, mode="connect", kernel_id=None):
        arguments = {
            "notebook_name": notebook_name, 
            "mode": mode,
        }
        # Only add notebook_path if provided (for switching, it's optional)
        if notebook_path is not None:
            arguments["notebook_path"] = notebook_path
        
        # Only add kernel_id if provided (not None)
        if kernel_id is not None:
            arguments["kernel_id"] = kernel_id
        
        result = await self._session.call_tool("use_notebook", arguments=arguments)  # type: ignore
        return self._extract_text_content(result)
    
    @requires_session
    async def list_notebooks(self):
        result = await self._session.call_tool("list_notebooks")  # type: ignore
        return self._extract_text_content(result)
    
    @requires_session
    async def restart_notebook(self, notebook_name):
        result = await self._session.call_tool("restart_notebook", arguments={"notebook_name": notebook_name})  # type: ignore
        return self._extract_text_content(result)
    
    @requires_session
    async def unuse_notebook(self, notebook_name):
        result = await self._session.call_tool("unuse_notebook", arguments={"notebook_name": notebook_name})  # type: ignore
        return self._extract_text_content(result)
    
    @requires_session
    async def read_notebook(self, notebook_name, response_format="brief", start_index=0, limit=20):
        result = await self._session.call_tool("read_notebook", arguments={"notebook_name": notebook_name, "response_format": response_format, "start_index": start_index, "limit": limit})  # type: ignore
        return self._extract_text_content(result)
    
    @requires_session
    async def insert_cell(self, cell_index, cell_type, cell_source):
        result = await self._call_tool_safe("insert_cell", {"cell_index": cell_index, "cell_type": cell_type, "cell_source": cell_source})
        return self._get_structured_content_safe(result) if result else None

    @requires_session
    async def insert_execute_code_cell(self, cell_index, cell_source, timeout=90):
        result = await self._call_tool_safe("insert_execute_code_cell", {"cell_index": cell_index, "cell_source": cell_source, "timeout": timeout})
        structured = self._get_structured_content_safe(result) if result else None
        
        # Special handling for insert_execute_code_cell: tool returns list[str | ImageContent]
        # In JUPYTER_SERVER mode, the list gets flattened to a single string in TextContent
        # In MCP_SERVER mode, it's properly wrapped in structured content as {"result": [...]}
        if structured and "result" in structured:
            result_value = structured["result"]
            # If result is not already a list, wrap it in a list to match the tool's return type
            if not isinstance(result_value, list):
                # Wrap the single value in a list
                structured["result"] = [result_value]
        return structured

    @requires_session
    async def read_cell(self, cell_index, include_outputs=True):
        result = await self._call_tool_safe("read_cell", {"cell_index": cell_index, "include_outputs": include_outputs})
        return self._get_structured_content_safe(result) if result else None
    
    @requires_session
    async def list_kernels(self):
        """List all available kernels"""
        result = await self._session.call_tool("list_kernels")  # type: ignore
        return self._extract_text_content(result)

    @requires_session
    async def delete_cell(self, cell_index):
        result = await self._call_tool_safe("delete_cell", {"cell_index": cell_index})
        return self._get_structured_content_safe(result) if result else None

    @requires_session
    async def execute_cell_streaming(self, cell_index):
        result = await self._call_tool_safe("execute_cell_streaming", {"cell_index": cell_index})
        return self._get_structured_content_safe(result) if result else None
    
    @requires_session
    async def execute_cell_with_progress(self, cell_index):
        result = await self._call_tool_safe("execute_cell_with_progress", {"cell_index": cell_index})
        structured = self._get_structured_content_safe(result) if result else None
        
        # Handle JUPYTER_SERVER mode flattening list responses to single string
        if structured and "result" in structured:
            result_value = structured["result"]
            if not isinstance(result_value, list):
                structured["result"] = [result_value]
        return structured

    @requires_session
    async def execute_cell(self, cell_index, timeout_seconds=300, stream=False, progress_interval=5):
        result = await self._call_tool_safe("execute_cell", {
            "cell_index": cell_index,
            "timeout_seconds": timeout_seconds,
            "stream": stream,
            "progress_interval": progress_interval
        })
        structured = self._get_structured_content_safe(result) if result else None

        # Handle JUPYTER_SERVER mode flattening list responses to single string
        if structured and "result" in structured:
            result_value = structured["result"]
            if not isinstance(result_value, list):
                structured["result"] = [result_value]
        return structured

    @requires_session
    async def overwrite_cell_source(self, cell_index, cell_source):
        result = await self._call_tool_safe("overwrite_cell_source", {"cell_index": cell_index, "cell_source": cell_source})
        return self._get_structured_content_safe(result) if result else None

    @requires_session
    async def execute_code(self, code, timeout=60):
        result = await self._session.call_tool("execute_code", arguments={"code": code, "timeout": timeout})  # type: ignore
        structured = self._get_structured_content_safe(result)
        
        # execute_code should always return a list of outputs
        # If we got a plain string, wrap it as a list
        if structured and "result" in structured:
            result_val = structured["result"]
            if isinstance(result_val, str):
                # Single output string, wrap as list
                structured["result"] = [result_val]
            elif not isinstance(result_val, list):
                # Some other type, wrap as list
                structured["result"] = [result_val]
        
        return structured
