# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""cite from a notebook."""

from typing import Any, Optional
from mcp.server.fastmcp.prompts.base import UserMessage
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import Notebook


class JupyterCitePrompt(BaseTool):
    """Tool to cite specific cells from specified notebook."""
    
    def _parse_cell_indices(self, cell_indices_str: str, max_cells: int) -> list[int]:
        """
        Parse cell indices from a string with flexible format.
        
        Supports formats like:
        - '0,1,2' for individual indices
        - '0-2' for ranges
        - '0-2,4' for mixed format
        - '3-' for from index 3 to end
        
        Args:
            cell_indices_str: String with cell indices
            max_cells: Maximum number of cells in the notebook
            
        Returns:
            List of integer cell indices
            
        Raises:
            ValueError: If indices are invalid or out of range
        """
        if not cell_indices_str or not cell_indices_str.strip():
            raise ValueError("Cell indices cannot be empty")
            
        # Check if notebook is empty
        if max_cells <= 0:
            raise ValueError("Notebook has no cells")
            
        result = set()
        parts = cell_indices_str.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            if '-' in part:
                # Handle range format
                range_parts = part.split('-', 1)
                
                if len(range_parts) == 2:
                    start_str, end_str = range_parts
                    
                    if not start_str:
                        raise ValueError(f"Invalid range format: {part}")
                    
                    try:
                        start = int(start_str)
                    except ValueError:
                        raise ValueError(f"Invalid start index: {start_str}")
                    
                    if start < 0:
                        raise ValueError(f"Start index cannot be negative: {start}")
                    
                    if not end_str:
                        # Case: '3-' means from 3 to end
                        end = max_cells - 1
                        # Check if start is within range
                        if start >= max_cells:
                            raise ValueError(f"Cell index {start} is out of range. Notebook has {max_cells} cells.")
                    else:
                        try:
                            end = int(end_str)
                        except ValueError:
                            raise ValueError(f"Invalid end index: {end_str}")
                        
                        if end < start:
                            raise ValueError(f"End index ({end}) must be greater than or equal to start index ({start})")
                else:
                    raise ValueError(f"Invalid range format: {part}")
                    
                # Add all indices in the range
                for i in range(start, end + 1):
                    if i >= max_cells:
                        raise ValueError(f"Cell index {i} is out of range. Notebook has {max_cells} cells.")
                    result.add(i)
            else:
                # Handle single index
                try:
                    index = int(part)
                except ValueError:
                    raise ValueError(f"Invalid cell index: {part}")
                
                if index < 0:
                    raise ValueError(f"Cell index cannot be negative: {index}")
                if index >= max_cells:
                    raise ValueError(f"Cell index {index} is out of range. Notebook has {max_cells} cells.")
                
                result.add(index)
        
        # Convert to sorted list
        return sorted(result)
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        contents_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        cell_indices: Optional[str] = None,
        notebook_name: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """Execute the read_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to read
            response_format: Response format (brief or detailed)
            start_index: Starting index for pagination (0-based)
            limit: Maximum number of items to return (0 means no limit)
            **kwargs: Additional parameters
            
        Returns:
            Formatted table with cell information
        """
        if notebook_name == "":
            notebook_name = notebook_manager._current_notebook
        if notebook_name not in notebook_manager:
            raise ValueError(f"Notebook '{notebook_name}' is not connected. All currently connected notebooks: {list(notebook_manager.list_all_notebooks().keys())}")
        
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: read notebook directly from file system
            notebook_path = notebook_manager.get_notebook_path(notebook_name)
            
            model = await contents_manager.get(notebook_path, content=True, type='notebook')
            if 'content' not in model:
                raise ValueError(f"Could not read notebook content from {notebook_path}")
            notebook = Notebook(**model['content'])
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_notebook_connection(notebook_name) as notebook_content:
                notebook = Notebook(**notebook_content.as_dict())
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        # Parse cell indices with flexible format
        parsed_indices = self._parse_cell_indices(cell_indices, len(notebook))

        prompt_list = [f"USER Cite cells {parsed_indices} from notebook {notebook_name}, here are the cells:"]
        for cell_index in parsed_indices:
            cell = notebook.cells[cell_index]
            prompt_list.append(f"=====Cell {cell_index} | type: {cell.cell_type} | execution count: {cell.execution_count if cell.execution_count else 'N/A'}=====")
            prompt_list.append(cell.get_source('readable'))
        
        prompt_list.append("=====End of Cited Cells=====")
        prompt_list.append(f"USER's Instruction are follow: {prompt}")

        return [UserMessage(content="\n".join(prompt_list))]

        

