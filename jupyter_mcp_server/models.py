# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

from typing import Annotated, Optional, Literal
from typing import Any
from pydantic import BaseModel, Field
from jupyter_mcp_server.utils import safe_extract_outputs, normalize_cell_source


class DocumentRuntime(BaseModel):
    provider: str
    document_url: str
    document_id: str
    document_token: str
    runtime_url: str
    runtime_id: str
    runtime_token: str
    allowed_jupyter_tools: Optional[str] = None

class Cell(BaseModel):
    """Notebook cell information as returned by the MCP server"""

    index: Annotated[int,Field(default=0)]
    cell_type: Annotated[Literal["raw", "code", "markdown"],Field(default="raw")]
    source: Annotated[Any,Field(default=[])]
    metadata: Annotated[Any,Field(default={})]
    id: Annotated[str,Field(default="")]
    execution_count: Annotated[Optional[int],Field(default=None)]
    outputs: Annotated[Any,Field(default=[])]

    def get_source(self, response_format: Literal['raw','readable'] = 'readable'):
        """Get the cell source in the requested format"""
        source = normalize_cell_source(self.source)
        if response_format == 'raw':
            return source
        elif response_format == 'readable':
            return "\n".join([line.rstrip("\n") for line in source])

    def get_outputs(self, response_format : Literal["raw",'readable']='readable'):
        """Get the cell output in the requested format"""
        if response_format == "raw":
            return self.outputs
        elif response_format == "readable":
            return safe_extract_outputs(self.outputs)

    def get_overview(self)  -> str:
        """Get the cell overview(First Line and Lines)"""
        source = normalize_cell_source(self.source)
        if len(source) == 0:
            return ""
        first_line = source[0].rstrip("\n")
        if len(source) > 1:
            first_line += f"...({len(source) - 1} lines hidden)"
        return first_line


class Notebook(BaseModel):

    cells: Annotated[list[Cell],Field(default=[])]
    metadata: Annotated[dict,Field(default={})]
    nbformat: Annotated[int,Field(default=4)]
    nbformat_minor: Annotated[int,Field(default=4)]

    def __len__(self) -> int:
        """Return the number of cells in the notebook"""
        return len(self.cells)

    def __getitem__(self, key) -> Cell | list[Cell]:
        """Support indexing and slicing operations on cells"""
        return self.cells[key]

    def format_output(self, response_format: Literal["brief", "detailed"] = "brief", start_index: int = 0, limit: int = 0):
        """
        Format notebook output based on response format and range parameters.
        Args:
            response_format: Format of the response ("brief" or "detailed")
            start_index: Starting index for cell range (default: 0)
            limit: Maximum number of cells to show (default: 0 means no limit)
        Returns:
            Formatted output string
        """
        # Determine the range of cells to display
        total_cells = len(self.cells)
        if total_cells == 0:
            return "Notebook is empty"

        # Calculate end index
        end_index = total_cells if limit == 0 else min(start_index + limit, total_cells)
        cells_to_show = self.cells[start_index:end_index]
        if len(cells_to_show) == 0:
            return "No cells in the specified range"

        if response_format == "brief":
            # Generate TSV table for brief format using get_overview
            from jupyter_mcp_server.utils import format_TSV

            headers = ["Index", "Type", "Count", "First Line"]
            rows = []

            for idx, cell in enumerate(cells_to_show):
                absolute_idx = start_index + idx
                cell_type = cell.cell_type
                execution_count = cell.execution_count if cell.execution_count else 'N/A'
                overview = cell.get_overview()

                rows.append([absolute_idx, cell_type, execution_count, overview])
            
            return format_TSV(headers, rows)

        elif response_format == "detailed":
            info_list = []
            for idx, cell in enumerate(cells_to_show):
                absolute_idx = start_index + idx
                info_list.append(f"=====Cell {absolute_idx} | type: {cell.cell_type} | execution count: {cell.execution_count if cell.execution_count else 'N/A'}=====\n")
                info_list.append(cell.get_source('readable'))
                info_list.append("\n\n")

            return "\n".join(info_list)