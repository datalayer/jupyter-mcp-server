# Quick Reference: Creating a New Tool

## Template

```python
# Copyright (c) 2023-2024 Datalayer, Inc.
# BSD 3-Clause License

"""Tool name implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class MyNewTool(BaseTool):
    """Tool to do something."""
    
    @property
    def name(self) -> str:
        return "my_new_tool"
    
    @property
    def description(self) -> str:
        return """Brief description.
    
Args:
    param1: Description
    param2: Description
    
Returns:
    Return type and description"""
    
    def _operation_http(self, server_client: JupyterServerClient, **kwargs):
        """Implementation using HTTP API (MCP_SERVER mode)."""
        # Use server_client.contents.*, server_client.kernels.*, etc.
        pass
    
    def _operation_local(self, contents_manager, kernel_manager, **kwargs):
        """Implementation using local API (JUPYTER_SERVER mode)."""
        # Use contents_manager.get(), kernel_manager.start_kernel(), etc.
        pass
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[KernelClient] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        # Add tool-specific parameters here
        param1: Optional[str] = None,
        param2: Optional[int] = None,
        **kwargs
    ) -> Any:  # Replace Any with actual return type
        """Execute the tool logic.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            kernel_client: Kernel HTTP client for MCP_SERVER mode
            contents_manager: Local API for JUPYTER_SERVER mode
            kernel_manager: Local API for JUPYTER_SERVER mode
            kernel_spec_manager: Local API for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            param1: Tool-specific parameter
            param2: Tool-specific parameter
            **kwargs: Additional parameters
            
        Returns:
            Tool result
        """
        # Validate required parameters
        if not param1:
            raise ValueError("param1 is required")
        
        # Route based on mode
        if mode == ServerMode.JUPYTER_SERVER:
            if not contents_manager:
                raise ValueError("contents_manager required for JUPYTER_SERVER mode")
            return self._operation_local(contents_manager, kernel_manager, **kwargs)
        else:
            if not server_client:
                raise ValueError("server_client required for MCP_SERVER mode")
            return self._operation_http(server_client, **kwargs)
```

## Integration Steps

### 1. Create the tool file
```bash
touch jupyter_mcp_server/tools/my_new_tool.py
# Copy template above and implement
```

### 2. Add to __init__.py
```python
# In jupyter_mcp_server/tools/__init__.py
from jupyter_mcp_server.tools.my_new_tool import MyNewTool

__all__ = [
    # ... existing exports
    "MyNewTool",
]
```

### 3. Register the tool
```python
# In server.py, in _initialize_tools() function
from jupyter_mcp_server.tools import MyNewTool

def _initialize_tools():
    # ... existing registrations
    register_tool(MyNewTool())
```

### 4. Add wrapper in server.py
```python
# In server.py, with other @mcp.tool() functions
@mcp.tool()
async def my_new_tool(param1: str, param2: int = 0) -> str:
    """Brief description.
    
    Args:
        param1: Description
        param2: Description
        
    Returns:
        Return type and description
    """
    mode = _get_server_mode()
    return await registry.execute_tool(
        "my_new_tool",
        mode=mode,
        param1=param1,
        param2=param2
    )
```

### 5. Test
```bash
# Syntax check
python -m py_compile jupyter_mcp_server/tools/my_new_tool.py

# Test MCP_SERVER mode
make start

# Test JUPYTER_SERVER mode
make jupyterlab
# Configure Claude Desktop to connect to http://localhost:8888/mcp
```

## Common Patterns

### Pattern 1: Simple notebook_manager-only tool
```python
async def execute(self, mode, notebook_manager=None, notebook_name=None, **kwargs):
    # Doesn't need different logic for different modes
    return notebook_manager.do_something(notebook_name)
```

### Pattern 2: File/directory listing
```python
def _list_http(self, server_client, path):
    return server_client.contents.list_directory(path)

def _list_local(self, contents_manager, path):
    model = contents_manager.get(path, content=True, type='directory')
    return model.get('content', [])
```

### Pattern 3: Kernel operations
```python
def _kernel_http(self, kernel_client):
    kernel_client.start()
    return kernel_client.execute(code)

def _kernel_local(self, kernel_manager, kernel_id):
    kernel = kernel_manager.get_kernel(kernel_id)
    return kernel.execute(code)
```

## API Reference

### HTTP API (MCP_SERVER mode)

**server_client** (JupyterServerClient):
- `.contents.list_directory(path)` → List directory contents
- `.contents.get(path)` → Get file/directory model
- `.contents.create_notebook(path)` → Create new notebook
- `.kernels.list_kernels()` → List all kernels
- `.kernels.start_kernel()` → Start new kernel
- `.kernelspecs.list_kernelspecs()` → List kernel specs

**kernel_client** (KernelClient):
- `.start()` → Start/connect to kernel
- `.execute(code)` → Execute code
- `.is_alive()` → Check kernel status
- `.restart()` → Restart kernel

### Local API (JUPYTER_SERVER mode)

**contents_manager**:
- `.get(path, content=True, type='directory')` → Get directory contents
- `.get(path)` → Get file/notebook model
- `.new(path=path, type='notebook')` → Create new notebook
- `.save(model, path)` → Save file/notebook
- `.delete(path)` → Delete file/notebook

**kernel_manager**:
- `.start_kernel(**kwargs)` → Start new kernel, returns kernel_id
- `.get_kernel(kernel_id)` → Get kernel instance
- `.list_kernel_ids()` → List all kernel IDs
- `.restart_kernel(kernel_id)` → Restart kernel
- `.interrupt_kernel(kernel_id)` → Interrupt kernel
- `.shutdown_kernel(kernel_id)` → Shutdown kernel

**kernel_spec_manager**:
- `.get_all_specs()` → Get all kernel specifications
- `.get_kernel_spec(name)` → Get specific kernel spec

## Checklist

- [ ] Tool class created in `jupyter_mcp_server/tools/`
- [ ] Inherits from `BaseTool`
- [ ] Implements `name` property
- [ ] Implements `description` property with full docstring
- [ ] Implements `execute()` method
- [ ] Has HTTP implementation method (if needed)
- [ ] Has local implementation method (if needed)
- [ ] Routes correctly based on `mode` parameter
- [ ] Validates required parameters
- [ ] Exported in `__init__.py`
- [ ] Registered in `_initialize_tools()`
- [ ] Wrapper function added to `server.py`
- [ ] Syntax validated (`python -m py_compile`)
- [ ] Tested in MCP_SERVER mode
- [ ] Tested in JUPYTER_SERVER mode
