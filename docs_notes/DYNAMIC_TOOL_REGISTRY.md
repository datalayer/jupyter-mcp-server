# Dynamic Tool Registry Implementation

## Overview

The Jupyter MCP Server now dynamically exposes its tool registry instead of hardcoding tool lists. This ensures that the Jupyter extension handlers always return the correct, up-to-date list of available MCP tools.

## Changes Made

### 1. Added `get_registered_tools()` Helper Function

**File**: `jupyter_mcp_server/server.py`

Added an async helper function that queries the FastMCP instance to get all registered tools:

```python
async def get_registered_tools():
    """
    Get list of all registered MCP tools with their metadata.
    
    This function is used by the Jupyter extension to dynamically expose
    the tool registry without hardcoding tool names and parameters.
    
    Returns:
        list: List of tool dictionaries with name, description, and inputSchema
    """
    # Use FastMCP's list_tools method which returns Tool objects
    tools_list = await mcp.list_tools()
    
    tools = []
    for tool in tools_list:
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
        }
        
        # Extract parameter names from inputSchema
        if hasattr(tool, 'inputSchema') and tool.inputSchema:
            input_schema = tool.inputSchema
            if 'properties' in input_schema:
                tool_dict["parameters"] = list(input_schema['properties'].keys())
            else:
                tool_dict["parameters"] = []
            
            # Include full inputSchema for MCP protocol compatibility
            tool_dict["inputSchema"] = input_schema
        else:
            tool_dict["parameters"] = []
        
        tools.append(tool_dict)
    
    return tools
```

### 2. Updated `MCPToolsListHandler`

**File**: `jupyter_mcp_server/jupyter_extension/handlers.py`

Modified the `MCPToolsListHandler.get()` method to call `get_registered_tools()`:

**Before** (hardcoded list of 11 tools):
```python
@tornado.web.authenticated
def get(self):
    """Return list of available tools."""
    tools = [
        {
            "name": "use_notebook",
            "description": "Connect to a notebook file or create a new one",
            "parameters": ["notebook_name", "notebook_path", "mode", "kernel_id"]
        },
        # ... 10 more hardcoded tools
    ]
```

**After** (dynamic from registry):
```python
@tornado.web.authenticated
async def get(self):
    """Return list of available tools dynamically from the tool registry."""
    # Import here to avoid circular dependency
    from jupyter_mcp_server.server import get_registered_tools
    
    # Get tools dynamically from the MCP server registry
    tools = await get_registered_tools()
    
    response = {
        "tools": tools,
        "count": len(tools)
    }
```

### 3. Added Test Coverage

**File**: `tests/test_jupyter_extension.py`

Added a new test to verify the dynamic tool list works correctly:

```python
def test_dynamic_tool_list():
    """Test that tool list is returned dynamically from registry."""
    try:
        import asyncio
        from jupyter_mcp_server.server import get_registered_tools
        
        tools = asyncio.run(get_registered_tools())
        logger.info(f"✅ Found {len(tools)} tools dynamically")
        
        # Verify we have the expected tools
        tool_names = [t['name'] for t in tools]
        expected_tools = ['use_notebook', 'list_notebook', 'read_all_cells', 'execute_cell_simple_timeout']
        
        for expected in expected_tools:
            if expected not in tool_names:
                logger.error(f"❌ Expected tool '{expected}' not found in: {tool_names}")
                return False
        
        # Verify each tool has required fields
        for tool in tools:
            if not all(key in tool for key in ['name', 'description', 'parameters']):
                logger.error(f"❌ Tool missing required fields: {tool.get('name', 'unknown')}")
                return False
        
        logger.info(f"✅ All tools have required metadata")
        return True
    except Exception as e:
        logger.error(f"❌ Dynamic tool list failed: {e}", exc_info=True)
        return False
```

## Benefits

1. **Maintainability**: When new tools are added to `server.py`, they automatically appear in the Jupyter extension without manual updates.

2. **Single Source of Truth**: The FastMCP registry is the only place that defines available tools.

3. **Consistency**: Tool names, descriptions, and parameters are guaranteed to match between the MCP server and Jupyter extension.

4. **MCP Protocol Compliance**: The full `inputSchema` is included, making the handler compatible with MCP protocol clients.

5. **Scalability**: The current implementation returns 18 tools (up from 11 hardcoded), with automatic support for future additions.

## Example Response

The `/mcp/tools/list` endpoint now returns:

```json
{
  "tools": [
    {
      "name": "use_notebook",
      "description": "Use a notebook file (connect to existing or create new)...",
      "parameters": ["notebook_name", "notebook_path", "mode", "kernel_id"],
      "inputSchema": {
        "properties": {
          "notebook_name": {"title": "Notebook Name", "type": "string"},
          "notebook_path": {"title": "Notebook Path", "type": "string"},
          "mode": {"default": "connect", "enum": ["connect", "create"], "type": "string"},
          "kernel_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}
        },
        "required": ["notebook_name", "notebook_path"],
        "type": "object"
      }
    },
    // ... 17 more tools
  ],
  "count": 18
}
```

## Testing

All existing tests pass:
- ✅ `pytest tests/test_mcp.py` - 18/18 tests passing
- ✅ `python tests/test_jupyter_extension.py` - All 4 tests passing, including new dynamic tool list test

## Usage in Jupyter Extension

The Jupyter extension now automatically has access to all registered MCP tools through the `MCPToolsListHandler`. This is particularly useful for:

1. **Discovery**: Clients can query `/mcp/tools/list` to discover available tools
2. **Validation**: The full `inputSchema` allows clients to validate parameters before calling tools
3. **Documentation**: Tool descriptions and parameter lists are always up-to-date

## Future Improvements

Potential enhancements:
1. Add caching to `get_registered_tools()` to avoid repeated FastMCP queries
2. Support tool filtering (by category, capability, etc.)
3. Add versioning information to tools
4. Implement tool deprecation warnings
