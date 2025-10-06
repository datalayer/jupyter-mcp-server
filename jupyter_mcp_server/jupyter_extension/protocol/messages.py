# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
MCP Protocol Messages

Pydantic models for MCP protocol requests and responses to ensure consistent
API across both MCP_SERVER and JUPYTER_SERVER modes.
"""

from typing import Any, Optional, Union, Literal
from pydantic import BaseModel, Field
from mcp.types import ImageContent


# Tool execution models
class ToolRequest(BaseModel):
    """Request to execute a tool"""
    tool_name: str = Field(..., description="Name of the tool to execute")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    context: Optional[dict[str, Any]] = Field(None, description="Execution context")


class ToolResponse(BaseModel):
    """Response from tool execution"""
    success: bool = Field(..., description="Whether execution was successful")
    result: Any = Field(None, description="Tool execution result")
    error: Optional[str] = Field(None, description="Error message if execution failed")


# Notebook operation models
class NotebookContentRequest(BaseModel):
    """Request to retrieve notebook content"""
    path: str = Field(..., description="Path to the notebook file")
    include_outputs: bool = Field(True, description="Include cell outputs")


class NotebookContentResponse(BaseModel):
    """Response containing notebook content"""
    path: str = Field(..., description="Notebook path")
    cells: list[dict[str, Any]] = Field(..., description="List of cells")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Notebook metadata")


class NotebookListRequest(BaseModel):
    """Request to list notebooks"""
    path: Optional[str] = Field("", description="Directory path to search")
    recursive: bool = Field(True, description="Search recursively")


class NotebookListResponse(BaseModel):
    """Response containing list of notebooks"""
    notebooks: list[str] = Field(..., description="List of notebook paths")


# Cell operation models
class ReadCellsRequest(BaseModel):
    """Request to read cells from a notebook"""
    path: Optional[str] = Field(None, description="Notebook path (uses current if not specified)")
    start_index: Optional[int] = Field(None, description="Start cell index")
    end_index: Optional[int] = Field(None, description="End cell index")


class ReadCellsResponse(BaseModel):
    """Response containing cell information"""
    cells: list[dict[str, Any]] = Field(..., description="List of cell information")


class AppendCellRequest(BaseModel):
    """Request to append a cell"""
    path: Optional[str] = Field(None, description="Notebook path")
    cell_type: Literal["code", "markdown"] = Field(..., description="Cell type")
    source: Union[str, list[str]] = Field(..., description="Cell source")


class AppendCellResponse(BaseModel):
    """Response after appending a cell"""
    cell_index: int = Field(..., description="Index of the appended cell")
    message: str = Field(..., description="Success message")


class InsertCellRequest(BaseModel):
    """Request to insert a cell"""
    path: Optional[str] = Field(None, description="Notebook path")
    cell_index: int = Field(..., description="Index where to insert")
    cell_type: Literal["code", "markdown"] = Field(..., description="Cell type")
    source: Union[str, list[str]] = Field(..., description="Cell source")


class InsertCellResponse(BaseModel):
    """Response after inserting a cell"""
    cell_index: int = Field(..., description="Index of the inserted cell")
    message: str = Field(..., description="Success message")


class DeleteCellRequest(BaseModel):
    """Request to delete a cell"""
    path: Optional[str] = Field(None, description="Notebook path")
    cell_index: int = Field(..., description="Index of cell to delete")


class DeleteCellResponse(BaseModel):
    """Response after deleting a cell"""
    message: str = Field(..., description="Success message")


class OverwriteCellRequest(BaseModel):
    """Request to overwrite a cell"""
    path: Optional[str] = Field(None, description="Notebook path")
    cell_index: int = Field(..., description="Index of cell to overwrite")
    new_source: Union[str, list[str]] = Field(..., description="New cell source")


class OverwriteCellResponse(BaseModel):
    """Response after overwriting a cell"""
    message: str = Field(..., description="Success message with diff")


# Cell execution models
class ExecuteCellRequest(BaseModel):
    """Request to execute a cell"""
    path: Optional[str] = Field(None, description="Notebook path")
    cell_index: int = Field(..., description="Index of cell to execute")
    timeout_seconds: int = Field(300, description="Execution timeout in seconds")


class ExecuteCellResponse(BaseModel):
    """Response after executing a cell"""
    cell_index: int = Field(..., description="Executed cell index")
    outputs: list[Union[str, ImageContent]] = Field(..., description="Cell outputs")
    execution_count: Optional[int] = Field(None, description="Execution count")
    status: Literal["success", "error", "timeout"] = Field(..., description="Execution status")


# Kernel operation models
class ConnectNotebookRequest(BaseModel):
    """Request to connect to a notebook"""
    notebook_name: str = Field(..., description="Unique notebook identifier")
    notebook_path: str = Field(..., description="Path to notebook file")
    mode: Literal["connect", "create"] = Field("connect", description="Connection mode")
    kernel_id: Optional[str] = Field(None, description="Specific kernel ID")


class ConnectNotebookResponse(BaseModel):
    """Response after connecting to notebook"""
    message: str = Field(..., description="Success message")
    notebook_name: str = Field(..., description="Notebook identifier")
    notebook_path: str = Field(..., description="Notebook path")


class UnuseNotebookRequest(BaseModel):
    """Request to unuse from a notebook"""
    notebook_name: str = Field(..., description="Notebook identifier to disconnect")


class UnuseNotebookResponse(BaseModel):
    """Response after disconnecting"""
    message: str = Field(..., description="Success message")


class RestartNotebookRequest(BaseModel):
    """Request to restart a notebook kernel"""
    notebook_name: str = Field(..., description="Notebook identifier to restart")


class RestartNotebookResponse(BaseModel):
    """Response after restarting kernel"""
    message: str = Field(..., description="Success message")
    notebook_name: str = Field(..., description="Notebook identifier")
