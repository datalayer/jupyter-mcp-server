# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

from itertools import islice
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from jupyter_mcp_server.utils import normalize_cell_source, safe_extract_outputs


class DocumentCodeSandbox(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # `provider` is what this field was called before v1.3.2; the /connect payload
    # of an older client still names it that way.
    document_provider: str = Field(validation_alias=AliasChoices("document_provider", "provider"))
    document_url: str | None = None
    document_id: str
    document_token: str
    code_sandbox_url: str
    code_sandbox_id: str
    code_sandbox_token: str
    allowed_jupyter_tools: str | None = None


class Cell(BaseModel):
    """Notebook cell information as returned by the MCP server"""

    index: Annotated[int, Field(default=0)]
    cell_type: Annotated[Literal["raw", "code", "markdown"], Field(default="raw")]
    source: Annotated[Any, Field(default=[])]
    metadata: Annotated[Any, Field(default={})]
    id: Annotated[str, Field(default="")]
    execution_count: Annotated[int | None, Field(default=None)]
    outputs: Annotated[Any, Field(default=[])]

    def get_source(self, response_format: Literal["raw", "readable"] = "readable"):
        """Get the cell source in the requested format"""
        source = normalize_cell_source(self.source)
        if response_format == "raw":
            return source
        elif response_format == "readable":
            return "\n".join([line.rstrip("\n") for line in source])

    def get_outputs(self, response_format: Literal["raw", "readable"] = "readable"):
        """Get the cell output in the requested format"""
        if response_format == "raw":
            return self.outputs
        elif response_format == "readable":
            return safe_extract_outputs(self.outputs)

    def get_overview(self) -> str:
        """Get the cell overview(First Line and Lines)"""
        source = normalize_cell_source(self.source)
        if len(source) == 0:
            return ""
        first_line = source[0].rstrip("\n")
        if len(source) > 1:
            first_line += f"...({len(source) - 1} lines hidden)"
        return first_line

    def matches(
        self,
        search: str | None = None,
        cell_type: Literal["code", "markdown", "raw"] | None = None,
    ) -> bool:
        """Whether the cell passes the `read_notebook` filters.

        Args:
            search: Text the cell source must contain, ignoring case. Empty or
                None matches every cell.
            cell_type: Type the cell must have. None matches every type.
        """
        if cell_type is not None and self.cell_type != cell_type:
            return False
        if search:
            return search.casefold() in self.get_source("readable").casefold()
        return True


class Notebook(BaseModel):
    cells: Annotated[list[Cell], Field(default=[])]
    metadata: Annotated[dict, Field(default={})]
    nbformat: Annotated[int, Field(default=4)]
    nbformat_minor: Annotated[int, Field(default=4)]

    def __len__(self) -> int:
        """Return the number of cells in the notebook"""
        return len(self.cells)

    def __getitem__(self, key) -> Cell | list[Cell]:
        """Support indexing and slicing operations on cells"""
        return self.cells[key]

    def format_output(
        self,
        response_format: Literal["brief", "detailed"] = "brief",
        start_index: int = 0,
        limit: int = 0,
        search: str | None = None,
        cell_type: Literal["code", "markdown", "raw"] | None = None,
    ):
        """
        Format notebook output based on response format and range parameters.
        Args:
            response_format: Format of the response ("brief" or "detailed")
            start_index: Starting index for cell range (default: 0)
            limit: Maximum number of cells to show (default: 0 means no limit)
            search: Only show cells whose source contains this text, ignoring case
            cell_type: Only show cells of this type
        Returns:
            Formatted output string
        """
        # Determine the range of cells to display
        total_cells = len(self.cells)
        if total_cells == 0:
            return "Notebook is empty"

        # Walk the cells from start_index on, keeping their notebook index, so
        # a filtered listing still shows positions the cell tools accept.
        # limit caps the cells shown, not the cells scanned.
        candidates = (
            (index, cell)
            for index, cell in enumerate(self.cells[start_index:], start=start_index)
            if cell.matches(search, cell_type)
        )
        cells_to_show = list(islice(candidates, limit or None))
        if len(cells_to_show) == 0:
            if search or cell_type is not None:
                return "No matching cells in the specified range"
            return "No cells in the specified range"

        if response_format == "brief":
            # Generate TSV table for brief format using get_overview
            from jupyter_mcp_server.utils import format_TSV

            headers = ["Index", "Type", "Count", "First Line"]
            rows = []

            for absolute_idx, cell in cells_to_show:
                execution_count = cell.execution_count if cell.execution_count else "N/A"
                overview = cell.get_overview()

                rows.append([absolute_idx, cell.cell_type, execution_count, overview])

            return format_TSV(headers, rows)

        elif response_format == "detailed":
            info_list = []
            for absolute_idx, cell in cells_to_show:
                info_list.append(
                    f"=====Cell {absolute_idx} | type: {cell.cell_type} | execution count: {cell.execution_count if cell.execution_count else 'N/A'}=====\n"
                )
                info_list.append(cell.get_source("readable"))
                info_list.append("\n\n")

            return "\n".join(info_list)
