---
title: "Overview"
description: "MCP reference for Jupyter MCP Server: 22 tools and 1 prompt, generated from a live protocol snapshot of the server."
---

# Jupyter MCP Server — MCP reference

[Jupyter MCP Server](https://github.com/datalayer/jupyter-mcp-server) is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets AI agents operate Jupyter notebooks: managing notebooks and cells, executing code on live kernels, and provisioning code sandboxes.

This reference documents the server's complete MCP surface — **22 tools** and **1 prompt** (protocol revision `2025-11-25`) — captured from a running server built from [this repository](https://github.com/datalayer/jupyter-mcp-server/tree/main). Each page shows the exact schema the server advertises plus a link to the decorator that registers it. The [MCP Reference tab](/mcp/reference/) renders the same snapshot as a single interactive page, and [Configuration](/mcp/configuration/) covers every runtime setting and both transports.

## Connection & server

| Tool | Summary |
| --- | --- |
| [`connect_to_jupyter`](/mcp/tools/connect-to-jupyter/) | Connect to a Jupyter server dynamically with URL and token. |
| [`list_files`](/mcp/tools/list-files/) | List all files and directories recursively in the Jupyter server's file system. |
| [`list_kernels`](/mcp/tools/list-kernels/) | List all available kernels in the Jupyter server. |

## Notebooks

| Tool | Summary |
| --- | --- |
| [`use_notebook`](/mcp/tools/use-notebook/) | Use a notebook and activate it for following cell operations. |
| [`list_notebooks`](/mcp/tools/list-notebooks/) | List all notebooks that have been used via use_notebook tool |
| [`read_notebook`](/mcp/tools/read-notebook/) | Read a notebook and return index, source content, type, execution count of each cell. |
| [`restart_notebook`](/mcp/tools/restart-notebook/) | Restart the kernel for a specific notebook. |
| [`unuse_notebook`](/mcp/tools/unuse-notebook/) | Unuse from a specific notebook and release its resources. |

## Cells

| Tool | Summary |
| --- | --- |
| [`insert_cell`](/mcp/tools/insert-cell/) | Insert a cell to specified position from the currently activated notebook. |
| [`read_cell`](/mcp/tools/read-cell/) | Read a cell as readable text entries. |
| [`edit_cell_source`](/mcp/tools/edit-cell-source/) | Perform a surgical find-and-replace within a cell's source (like an editor's Edit tool). |
| [`overwrite_cell_source`](/mcp/tools/overwrite-cell-source/) | Replace the entire source of a cell in the currently activated notebook. |
| [`move_cell`](/mcp/tools/move-cell/) | Move a cell from source_index to target_index within the currently activated notebook. |
| [`delete_cell`](/mcp/tools/delete-cell/) | Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True). |
| [`clear_cell_output`](/mcp/tools/clear-cell-output/) | Clear the outputs and execution count of a single code cell in the currently |

## Execution

| Tool | Summary |
| --- | --- |
| [`execute_cell`](/mcp/tools/execute-cell/) | Execute a cell from the currently activated notebook with timeout and return it's outputs |
| [`insert_execute_code_cell`](/mcp/tools/insert-execute-code-cell/) | Insert a cell at specified index from the currently activated notebook and then execute it with timeout and return it's outputs |
| [`execute_code`](/mcp/tools/execute-code/) | Execute code directly in a kernel (not saved to notebook). |

## Sandboxes (extension)

| Tool | Summary |
| --- | --- |
| [`launch_sandbox`](/mcp/tools/launch-sandbox/) | Launch a code sandbox that can be used instead of Jupyter kernels. |
| [`list_sandboxes`](/mcp/tools/list-sandboxes/) | List launched code sandboxes that can be used as alternatives to kernels. |
| [`use_sandbox`](/mcp/tools/use-sandbox/) | Select which launched sandbox execute_code should use instead of kernels. |
| [`terminate_sandbox`](/mcp/tools/terminate-sandbox/) | Terminate a launched code sandbox. |

## Prompts

| Prompt | Summary |
| --- | --- |
| [`jupyter_cite`](/mcp/prompts/jupyter-cite/) | Like @ or # in Coding IDE or CLI, cite specific cells from specified notebook and insert them into the prompt. |

## About these docs

Generated with [Sourcey](https://www.npmjs.com/package/sourcey) from an [mcp-parser](https://www.npmjs.com/package/mcp-parser) stdio snapshot of the server (`jupyter-mcp-server --transport stdio --start-new-code-sandbox false`). The snapshot, source map, and page generator are checked in under `docs/sourcey/`, and CI regenerates them on every pull request and fails on any difference, so this page cannot drift from the code.

