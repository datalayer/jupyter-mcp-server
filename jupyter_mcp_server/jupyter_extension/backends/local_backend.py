# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Local Backend Implementation

This backend uses the Jupyter Server's local API directly when running as an extension.
It provides efficient local access to contents_manager and kernel_manager.
"""

from typing import Optional, Any, Union, Literal, TYPE_CHECKING
import asyncio
from mcp.types import ImageContent
from jupyter_mcp_server.jupyter_extension.backends.base import Backend
from jupyter_mcp_server.utils import safe_extract_outputs

if TYPE_CHECKING:
    from jupyter_server.serverapp import ServerApp


class LocalBackend(Backend):
    """
    Backend that uses local Jupyter Server API directly.
    
    Uses:
    - serverapp.contents_manager for notebook file operations
    - serverapp.kernel_manager for kernel management
    - serverapp.kernel_spec_manager for kernel specs
    
    This backend is only available when running as a Jupyter Server extension
    with document_url="local" or runtime_url="local".
    """
    
    def __init__(self, serverapp: 'ServerApp'):
        """
        Initialize local backend with direct serverapp access.
        
        Args:
            serverapp: Jupyter ServerApp instance
        """
        self.serverapp = serverapp
        self.contents_manager = serverapp.contents_manager
        self.kernel_manager = serverapp.kernel_manager
        self.kernel_spec_manager = serverapp.kernel_spec_manager
    
    # Notebook operations
    
    async def get_notebook_content(self, path: str) -> dict[str, Any]:
        """
        Get notebook content using local contents_manager.
        
        Args:
            path: Path to notebook file
            
        Returns:
            Notebook content dictionary
        """
        model = await asyncio.to_thread(
            self.contents_manager.get,
            path,
            type='notebook',
            content=True
        )
        return model['content']
    
    async def list_notebooks(self, path: str = "") -> list[str]:
        """
        List all notebooks recursively using local contents_manager.
        
        Args:
            path: Directory path to search
            
        Returns:
            List of notebook paths
        """
        notebooks = []
        await self._list_notebooks_recursive(path, notebooks)
        return notebooks
    
    async def _list_notebooks_recursive(self, path: str, notebooks: list[str]) -> None:
        """Helper to recursively list notebooks."""
        try:
            model = await asyncio.to_thread(
                self.contents_manager.get,
                path,
                content=True
            )
            
            if model['type'] == 'directory':
                for item in model['content']:
                    item_path = f"{path}/{item['name']}" if path else item['name']
                    
                    if item['type'] == 'directory':
                        await self._list_notebooks_recursive(item_path, notebooks)
                    elif item['type'] == 'notebook' or item['name'].endswith('.ipynb'):
                        notebooks.append(item_path)
        except Exception:
            # Skip directories we can't access
            pass
    
    async def notebook_exists(self, path: str) -> bool:
        """
        Check if notebook exists using local contents_manager.
        
        Args:
            path: Path to notebook
            
        Returns:
            True if exists
        """
        try:
            await asyncio.to_thread(
                self.contents_manager.get,
                path,
                content=False
            )
            return True
        except Exception:
            return False
    
    async def create_notebook(self, path: str) -> dict[str, Any]:
        """
        Create a new notebook using local contents_manager.
        
        Args:
            path: Path for new notebook
            
        Returns:
            Created notebook content
        """
        model = await asyncio.to_thread(
            self.contents_manager.new,
            path=path
        )
        return model['content']
    
    # Cell operations
    
    async def read_cells(
        self, 
        path: str, 
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        Read cells from notebook.
        
        Args:
            path: Notebook path
            start_index: Start index
            end_index: End index
            
        Returns:
            List of cells
        """
        content = await self.get_notebook_content(path)
        cells = content.get('cells', [])
        
        if start_index is not None or end_index is not None:
            start = start_index or 0
            end = end_index if end_index is not None else len(cells)
            cells = cells[start:end]
        
        return cells
    
    async def append_cell(
        self, 
        path: str, 
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """
        Append a cell to notebook.
        
        Args:
            path: Notebook path
            cell_type: Cell type
            source: Cell source
            
        Returns:
            Index of appended cell
        """
        content = await self.get_notebook_content(path)
        cells = content.get('cells', [])
        
        # Normalize source to list of strings
        if isinstance(source, str):
            source = source.splitlines(keepends=True)
        
        new_cell = {
            'cell_type': cell_type,
            'metadata': {},
            'source': source
        }
        
        if cell_type == 'code':
            new_cell['outputs'] = []
            new_cell['execution_count'] = None
        
        cells.append(new_cell)
        content['cells'] = cells
        
        # Save updated notebook
        await asyncio.to_thread(
            self.contents_manager.save,
            {
                'type': 'notebook',
                'content': content
            },
            path
        )
        
        return len(cells) - 1
    
    async def insert_cell(
        self,
        path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """
        Insert a cell at specific index.
        
        Args:
            path: Notebook path
            cell_index: Insert position
            cell_type: Cell type
            source: Cell source
            
        Returns:
            Index of inserted cell
        """
        content = await self.get_notebook_content(path)
        cells = content.get('cells', [])
        
        # Normalize source
        if isinstance(source, str):
            source = source.splitlines(keepends=True)
        
        new_cell = {
            'cell_type': cell_type,
            'metadata': {},
            'source': source
        }
        
        if cell_type == 'code':
            new_cell['outputs'] = []
            new_cell['execution_count'] = None
        
        cells.insert(cell_index, new_cell)
        content['cells'] = cells
        
        # Save updated notebook
        await asyncio.to_thread(
            self.contents_manager.save,
            {
                'type': 'notebook',
                'content': content
            },
            path
        )
        
        return cell_index
    
    async def delete_cell(self, path: str, cell_index: int) -> None:
        """
        Delete a cell from notebook.
        
        Args:
            path: Notebook path
            cell_index: Index to delete
        """
        content = await self.get_notebook_content(path)
        cells = content.get('cells', [])
        
        if 0 <= cell_index < len(cells):
            cells.pop(cell_index)
            content['cells'] = cells
            
            await asyncio.to_thread(
                self.contents_manager.save,
                {
                    'type': 'notebook',
                    'content': content
                },
                path
            )
    
    async def overwrite_cell(
        self,
        path: str,
        cell_index: int,
        new_source: Union[str, list[str]]
    ) -> tuple[str, str]:
        """
        Overwrite cell content.
        
        Args:
            path: Notebook path
            cell_index: Cell index
            new_source: New source
            
        Returns:
            Tuple of (old_source, new_source)
        """
        content = await self.get_notebook_content(path)
        cells = content.get('cells', [])
        
        if cell_index < 0 or cell_index >= len(cells):
            raise ValueError(f"Cell index {cell_index} out of range")
        
        cell = cells[cell_index]
        old_source = ''.join(cell['source']) if isinstance(cell['source'], list) else cell['source']
        
        # Normalize new source
        if isinstance(new_source, str):
            new_source_str = new_source
            new_source = new_source.splitlines(keepends=True)
        else:
            new_source_str = ''.join(new_source)
        
        cell['source'] = new_source
        content['cells'] = cells
        
        await asyncio.to_thread(
            self.contents_manager.save,
            {
                'type': 'notebook',
                'content': content
            },
            path
        )
        
        return (old_source, new_source_str)
    
    # Kernel operations
    
    async def get_or_create_kernel(self, path: str, kernel_id: Optional[str] = None) -> str:
        """
        Get existing kernel or create new one.
        
        Args:
            path: Notebook path (for context)
            kernel_id: Specific kernel ID
            
        Returns:
            Kernel ID
        """
        if kernel_id and kernel_id in self.kernel_manager:
            return kernel_id
        
        # Start new kernel
        kernel_id = await self.kernel_manager.start_kernel()
        return kernel_id
    
    async def execute_cell(
        self,
        path: str,
        cell_index: int,
        kernel_id: str,
        timeout_seconds: int = 300
    ) -> list[Union[str, ImageContent]]:
        """
        Execute a cell using local kernel manager.
        
        Args:
            path: Notebook path
            cell_index: Cell index
            kernel_id: Kernel ID
            timeout_seconds: Timeout
            
        Returns:
            List of outputs
        """
        # Get cell source
        cells = await self.read_cells(path)
        if cell_index < 0 or cell_index >= len(cells):
            raise ValueError(f"Cell index {cell_index} out of range")
        
        cell = cells[cell_index]
        source = ''.join(cell['source']) if isinstance(cell['source'], list) else cell['source']
        
        # Get kernel client
        kernel = self.kernel_manager.get_kernel(kernel_id)
        client = kernel.client()
        
        # Execute code
        msg_id = client.execute(source)
        
        # Collect outputs
        outputs = []
        start_time = asyncio.get_event_loop().time()
        
        while True:
            if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                raise TimeoutError(f"Cell execution exceeded {timeout_seconds} seconds")
            
            try:
                msg = await asyncio.wait_for(
                    asyncio.to_thread(client.get_iopub_msg, timeout=1),
                    timeout=2
                )
                
                msg_type = msg['header']['msg_type']
                
                if msg_type == 'status':
                    if msg['content']['execution_state'] == 'idle':
                        break
                elif msg_type in ['execute_result', 'display_data']:
                    outputs.append(msg['content'])
                elif msg_type == 'stream':
                    outputs.append(msg['content'])
                elif msg_type == 'error':
                    outputs.append(msg['content'])
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
        
        # Update cell with outputs
        content = await self.get_notebook_content(path)
        if cell_index < len(content['cells']):
            content['cells'][cell_index]['outputs'] = outputs
            await asyncio.to_thread(
                self.contents_manager.save,
                {'type': 'notebook', 'content': content},
                path
            )
        
        return safe_extract_outputs(outputs)
    
    async def interrupt_kernel(self, kernel_id: str) -> None:
        """Interrupt a kernel."""
        if kernel_id in self.kernel_manager:
            kernel = self.kernel_manager.get_kernel(kernel_id)
            await kernel.interrupt()
    
    async def restart_kernel(self, kernel_id: str) -> None:
        """Restart a kernel."""
        if kernel_id in self.kernel_manager:
            await self.kernel_manager.restart_kernel(kernel_id)
    
    async def shutdown_kernel(self, kernel_id: str) -> None:
        """Shutdown a kernel."""
        if kernel_id in self.kernel_manager:
            await self.kernel_manager.shutdown_kernel(kernel_id)
    
    async def list_kernels(self) -> list[dict[str, Any]]:
        """List all running kernels."""
        return [
            {
                'id': kid,
                'name': self.kernel_manager.get_kernel(kid).kernel_name
            }
            for kid in self.kernel_manager.list_kernel_ids()
        ]
    
    async def kernel_exists(self, kernel_id: str) -> bool:
        """Check if kernel exists."""
        return kernel_id in self.kernel_manager
