# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

from typing import Optional, Literal, Union
from pydantic import BaseModel
from mcp.types import ImageContent
from jupyter_mcp_server.utils import safe_extract_outputs


class DocumentRuntime(BaseModel):
    provider: str
    document_url: str
    document_id: str
    document_token: str
    runtime_url: str
    runtime_id: str
    runtime_token: str


class CellInfo(BaseModel):
    """Notebook cell information as returned by the MCP server"""

    index: int
    type: Literal["unknown", "code", "markdown"]
    source: list[str]
    outputs: Optional[list[Union[str, ImageContent]]]

    @classmethod
    def from_cell(cls, cell_index: int, cell: dict):
        """Extract cell info (create a CellInfo object) from an index and a Notebook cell"""
        outputs = None
        type = cell.get("cell_type", "unknown")
        if type == "code":
            try:
                outputs = cell.get("outputs", [])
                outputs = safe_extract_outputs(outputs)
            except Exception as e:
                outputs = [f"[Error reading outputs: {str(e)}]"]
        return cls(
            index=cell_index, type=type, source=cell.get("source", ""), outputs=outputs
        )
