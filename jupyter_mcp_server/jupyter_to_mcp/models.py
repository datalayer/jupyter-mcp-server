# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""HTTP request/response models for the Jupyter-to-MCP adapter."""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class MCPError(BaseModel):
    """MCP error response model."""
    code: int
    message: str
    data: Optional[Any] = None


class MCPCapabilities(BaseModel):
    """MCP capabilities model."""
    tools: Optional[Dict[str, Any]] = None
    resources: Optional[Dict[str, Any]] = None
    prompts: Optional[Dict[str, Any]] = None
    logging: Optional[Dict[str, Any]] = None


class InitializeRequest(BaseModel):
    """Initialize request model."""
    protocolVersion: str = "2025-03-26"
    capabilities: MCPCapabilities = Field(default_factory=MCPCapabilities)
    clientInfo: Dict[str, Any] = Field(default_factory=dict)


class InitializeResponse(BaseModel):
    """Initialize response model."""
    protocolVersion: str
    capabilities: MCPCapabilities
    serverInfo: Dict[str, Any]


class Tool(BaseModel):
    """Tool definition model."""
    name: str
    description: str
    inputSchema: Dict[str, Any]
    annotations: Optional[Dict[str, Any]] = None


class ToolListRequest(BaseModel):
    """Tool list request model."""
    cursor: Optional[str] = None


class ToolListResponse(BaseModel):
    """Tool list response model."""
    tools: List[Tool]
    nextCursor: Optional[str] = None


class ToolCallRequest(BaseModel):
    """Tool call request model."""
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ContentItem(BaseModel):
    """Content item model for tool results."""
    type: str
    text: Optional[str] = None
    data: Optional[str] = None
    mimeType: Optional[str] = None


class ToolCallResponse(BaseModel):
    """Tool call response model."""
    content: List[ContentItem]
    isError: bool = False


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    version: str
    capabilities: List[str]
    mcp_server_status: str


class ErrorResponse(BaseModel):
    """Generic error response model."""
    error: MCPError
    message: str
    status_code: int
