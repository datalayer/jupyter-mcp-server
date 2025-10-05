<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Tool Class Reference Guide

Quick reference for all 18 extracted tool classes.

## Import All Tools

```python
from jupyter_mcp_server.tools import (
    # Notebook Management
    ListNotebookTool,
    ConnectNotebookTool,
    RestartNotebookTool,
    DisconnectNotebookTool,
    SwitchNotebookTool,
    # Cell Reading
    ReadAllCellsTool,
    ListCellTool,
    ReadCellTool,
    # Cell Writing
    InsertCellTool,
    InsertExecuteCodeCellTool,
    OverwriteCellSourceTool,
    DeleteCellTool,
    # Cell Execution
    ExecuteCellSimpleTimeoutTool,
    ExecuteCellStreamingTool,
    ExecuteCellWithProgressTool,
    # Other Tools
    ExecuteIpythonTool,
    ListAllFilesTool,
    ListKernelTool,
)
```

## Tool Categories

### Notebook Management (5 tools)

#### ListNotebookTool
Lists all notebooks in the Jupyter server.
```python
result = await list_notebook_tool.execute(
    mode=ServerMode.MCP_SERVER,
    path="",
    contents_manager=contents_manager,  # For local mode
    kernel_manager=kernel_manager,      # For local mode
)
```

#### ConnectNotebookTool
Connects to or creates a notebook file.
```python
result = await connect_notebook_tool.execute(
    mode=ServerMode.MCP_SERVER,
    notebook_path="notebook.ipynb",
    ensure_kernel_alive_fn=__ensure_kernel_alive,
    contents_manager=contents_manager,  # For local mode
    kernel_manager=kernel_manager,      # For local mode
)
```

#### RestartNotebookTool
Restarts the kernel for a specific notebook.
```python
result = await restart_notebook_tool.execute(
    mode=ServerMode.MCP_SERVER,
    notebook_name="notebook.ipynb",
)
```

#### DisconnectNotebookTool
Disconnects from a notebook and releases resources.
```python
result = await disconnect_notebook_tool.execute(
    mode=ServerMode.MCP_SERVER,
    notebook_name="notebook.ipynb",
)
```

#### SwitchNotebookTool
Switches the currently active notebook.
```python
result = await switch_notebook_tool.execute(
    mode=ServerMode.MCP_SERVER,
    notebook_name="notebook.ipynb",
)
```

### Cell Reading (3 tools)

#### ReadAllCellsTool
Reads all cells from the notebook.
```python
result = await read_all_cells_tool.execute(
    mode=ServerMode.MCP_SERVER,
)
```

#### ListCellTool
Lists basic cell information in formatted table.
```python
result = await list_cell_tool.execute(
    mode=ServerMode.MCP_SERVER,
)
```

#### ReadCellTool
Reads a specific cell by index.
```python
result = await read_cell_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
)
```

### Cell Writing (4 tools)

#### InsertCellTool
Inserts a code or markdown cell at specified position.
```python
result = await insert_cell_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    source="print('Hello')",
    cell_type="code",  # or "markdown"
)
```

#### InsertExecuteCodeCellTool
Inserts and immediately executes a code cell.
```python
result = await insert_execute_code_cell_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    source="print('Hello')",
    ensure_kernel_alive_fn=__ensure_kernel_alive,
)
```

#### OverwriteCellSourceTool
Overwrites existing cell source with diff display.
```python
result = await overwrite_cell_source_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    new_source="print('Updated')",
)
```

#### DeleteCellTool
Deletes a specific cell from the notebook.
```python
result = await delete_cell_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
)
```

### Cell Execution (3 tools)

#### ExecuteCellSimpleTimeoutTool
Executes a cell with simple timeout (for short-running cells).
```python
result = await execute_cell_simple_timeout_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    timeout_seconds=300,
    ensure_kernel_alive_fn=__ensure_kernel_alive,
    wait_for_kernel_idle_fn=__wait_for_kernel_idle,
    safe_extract_outputs_fn=safe_extract_outputs,
)
```

#### ExecuteCellStreamingTool
Executes a cell with streaming progress updates (for long-running cells).
```python
result = await execute_cell_streaming_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    timeout_seconds=300,
    progress_interval=5,
    ensure_kernel_alive_fn=__ensure_kernel_alive,
    wait_for_kernel_idle_fn=__wait_for_kernel_idle,
    extract_output_fn=extract_output,
)
```

#### ExecuteCellWithProgressTool
Executes a cell with progress monitoring and forced sync.
```python
result = await execute_cell_with_progress_tool.execute(
    mode=ServerMode.MCP_SERVER,
    cell_index=0,
    timeout_seconds=300,
    ensure_kernel_alive_fn=__ensure_kernel_alive,
    wait_for_kernel_idle_fn=__wait_for_kernel_idle,
    safe_extract_outputs_fn=safe_extract_outputs,
    execute_cell_with_forced_sync_fn=__execute_cell_with_forced_sync,
)
```

### Other Tools (3 tools)

#### ExecuteIpythonTool
Executes IPython code directly in the kernel (supports magic commands).
```python
result = await execute_ipython_tool.execute(
    mode=ServerMode.MCP_SERVER,
    code="%timeit sum(range(1000))",
    timeout=60,
    ensure_kernel_alive_fn=__ensure_kernel_alive,
    wait_for_kernel_idle_fn=__wait_for_kernel_idle,
    safe_extract_outputs_fn=safe_extract_outputs,
)
```

#### ListAllFilesTool
Lists all files and directories in the Jupyter server's file system.
```python
result = await list_all_files_tool.execute(
    mode=ServerMode.MCP_SERVER,
    path="",
    max_depth=3,
    list_files_recursively_fn=_list_files_recursively,
)
```

#### ListKernelTool
Lists all available kernels in the Jupyter server.
```python
result = await list_kernel_tool.execute(
    mode=ServerMode.MCP_SERVER,
)
```

## Helper Functions Reference

Many tools require helper functions to be passed as parameters. Here's what each helper function does:

### `ensure_kernel_alive_fn`
Ensures that a kernel is running for the current notebook. Returns the kernel instance.

### `wait_for_kernel_idle_fn`
Waits for the kernel to reach an idle state before executing code.

### `safe_extract_outputs_fn`
Safely extracts and formats outputs from executed cells (handles errors, images, text).

### `extract_output_fn`
Extracts a single output item from a cell output list.

### `list_files_recursively_fn`
Recursively lists files in the Jupyter server's file system.

### `execute_cell_with_forced_sync_fn`
Executes a cell with forced synchronization to ensure real-time progress updates.

### `get_surrounding_cells_info_fn`
Gets information about cells surrounding a specific cell index.

## Mode Detection

All tools support two modes:

- **`ServerMode.MCP_SERVER`**: HTTP mode using JupyterServerClient
- **`ServerMode.JUPYTER_SERVER`**: Local mode using contents_manager/kernel_manager

Most tools are mode-agnostic and use `notebook_manager.get_current_connection()` which works in both modes. Only tools that need file system operations or path checking require mode-specific logic.

## Usage in server.py

To integrate a tool into server.py:

```python
# 1. Initialize tool instance
list_notebook_tool = ListNotebookTool(notebook_manager)

# 2. Use tool in @mcp.tool() function
@mcp.tool()
async def list_notebook(path: str = "") -> str:
    """List all notebooks in the Jupyter server."""
    return await __safe_notebook_operation(
        lambda: list_notebook_tool.execute(
            mode=ServerMode.MCP_SERVER,
            path=path,
            contents_manager=notebook_manager.contents_manager,
            kernel_manager=notebook_manager.kernel_manager,
        )
    )
```

## Testing

Test imports:
```bash
cd /path/to/jupyter-mcp-server
PYTHONPATH=. python -c "from jupyter_mcp_server.tools import ListNotebookTool; print('✅ Import successful')"
```

Test all imports:
```bash
PYTHONPATH=. python -c "from jupyter_mcp_server.tools import *; print('✅ All imports successful')"
```
