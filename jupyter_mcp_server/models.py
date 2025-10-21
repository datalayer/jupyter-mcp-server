# Copyright (c) 2023-2024 Datalayer, Inc.
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


class Cell(BaseModel):
    """Notebook cell information as returned by the MCP server"""

    index: Annotated[int,Field(default=0)]
    cell_type: Annotated[Literal["raw", "code", "markdown"],Field(default="raw")]
    source: Annotated[Any,Field(default=[])]
    metadata: Annotated[Any,Field(default={})]
    id: Annotated[str,Field(default="")]
    execution_count: Annotated[Optional[int],Field(default=None)]
    outputs: Annotated[Any,Field(default=[])]

    @classmethod
    def from_cell(cls, cell_index: int, cell: dict):
        """Extract cell info (create a Cell object) from an index and a Notebook cell"""
        outputs = None
        type = cell.get("cell_type", "unknown")
        if type == "code":
            try:
                outputs = cell.get("outputs", [])
                outputs = safe_extract_outputs(outputs)
            except Exception as e:
                outputs = [f"[Error reading outputs: {str(e)}]"]
        
        # Properly normalize the cell source to a list of lines
        source = normalize_cell_source(cell.get("source", ""))
        
        return cls(
            index=cell_index, type=type, source=source, outputs=outputs
        )
    
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

    def format_output(self, response_format: Literal["brief", "full"] = "brief", start_index: int = 0, limit: int = 0):
        """
        Format notebook output based on response format and range parameters.

        Args:
            response_format: Format of the response ("brief" or "full")
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

        if response_format == "brief":
            # Generate TSV table for brief format using get_overview
            from jupyter_mcp_server.utils import format_TSV

            headers = ["Index", "Type", "Count", "First Line"]
            rows = []

            for idx, cell in enumerate(cells_to_show):
                absolute_idx = start_index + idx
                cell_type = cell.cell_type
                execution_count = cell.execution_count if cell_type == 'code' and cell.execution_count else '-'
                overview = cell.get_overview()

                rows.append([absolute_idx, cell_type, execution_count, overview])

            if rows:
                result = format_TSV(headers, rows)
                return result
            else:
                return "No cells in the specified range"

        elif response_format == "full":
            # For full format, return a summary (as requested by user)
            if cells_to_show:
                result = f"Notebook with {total_cells} cells (showing {len(cells_to_show)} cells starting from index {start_index}):\n\n"

                for idx, cell in enumerate(cells_to_show):
                    absolute_idx = start_index + idx
                    result += f"Cell {absolute_idx} ({cell.cell_type}):\n"
                    if cell.cell_type == 'code' and cell.execution_count:
                        result += f"Execution count: {cell.execution_count}\n"
                    result += f"Source:\n{cell.get_source('readable')}\n"

                    if cell.outputs:
                        result += "Outputs:\n"
                        for output in cell.outputs:
                            result += f"  {output}\n"
                    result += "\n" + "="*50 + "\n"

                return result
            else:
                return "No cells in the specified range"

        else:
            raise ValueError(f"Unsupported response_format: {response_format}. Supported formats: 'brief', 'full'")

