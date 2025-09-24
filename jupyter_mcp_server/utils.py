# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import re
from typing import Any, Union
from mcp.types import ImageContent
from .config_env import ALLOW_IMG_OUTPUT


def extract_output(output: Union[dict, Any]) -> Union[str, ImageContent]:
    """
    Extracts readable output from a Jupyter cell output dictionary.
    Handles both traditional and CRDT-based Jupyter formats.

    Args:
        output: The output from a Jupyter cell (dict or CRDT object).

    Returns:
        str: A string representation of the output.
    """
    # Handle pycrdt._text.Text objects
    if hasattr(output, 'source'):
        return str(output.source)
    
    # Handle CRDT YText objects
    if hasattr(output, '__str__') and 'Text' in str(type(output)):
        text_content = str(output)
        return strip_ansi_codes(text_content)
    
    # Handle lists (common in error tracebacks)
    if isinstance(output, list):
        return '\n'.join(extract_output(item) for item in output)
    
    # Handle traditional dictionary format
    if not isinstance(output, dict):
        return strip_ansi_codes(str(output))
    
    output_type = output.get("output_type")
    
    if output_type == "stream":
        text = output.get("text", "")
        if isinstance(text, list):
            text = ''.join(text)
        elif hasattr(text, 'source'):
            text = str(text.source)
        return strip_ansi_codes(str(text))
    
    elif output_type in ["display_data", "execute_result"]:
        data = output.get("data", {})
        if "image/png" in data:
            if ALLOW_IMG_OUTPUT:
                try:
                    return ImageContent(type="image", data=data["image/png"], mimeType="image/png")
                except Exception:
                    # Fallback to text placeholder on error
                    return "[Image Output (PNG) - Error processing image]"
            else:
                return "[Image Output (PNG) - Image display disabled]"
        if "text/plain" in data:
            plain_text = data["text/plain"]
            if hasattr(plain_text, 'source'):
                plain_text = str(plain_text.source)
            return strip_ansi_codes(str(plain_text))
        elif "text/html" in data:
            return "[HTML Output]"
        else:
            return f"[{output_type} Data: keys={list(data.keys())}]"
    
    elif output_type == "error":
        traceback = output.get("traceback", [])
        if isinstance(traceback, list):
            clean_traceback = []
            for line in traceback:
                if hasattr(line, 'source'):
                    line = str(line.source)
                clean_traceback.append(strip_ansi_codes(str(line)))
            return '\n'.join(clean_traceback)
        else:
            if hasattr(traceback, 'source'):
                traceback = str(traceback.source)
            return strip_ansi_codes(str(traceback))
    
    else:
        return f"[Unknown output type: {output_type}]"


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def safe_extract_outputs(outputs: Any) -> list[Union[str, ImageContent]]:
    """
    Safely extract all outputs from a cell, handling CRDT structures.
    
    Args:
        outputs: Cell outputs (could be CRDT YArray or traditional list)
        
    Returns:
        list[Union[str, ImageContent]]: List of outputs (strings or image content)
    """
    if not outputs:
        return []
    
    result = []
    
    # Handle CRDT YArray
    if hasattr(outputs, '__iter__') and not isinstance(outputs, (str, dict)):
        try:
            for output in outputs:
                extracted = extract_output(output)
                if extracted:
                    result.append(extracted)
        except Exception as e:
            result.append(f"[Error extracting output: {str(e)}]")
    else:
        # Handle single output or traditional list
        extracted = extract_output(outputs)
        if extracted:
            result.append(extracted)
    
    return result


def format_cell_list(ydoc_cells: Any) -> str:
    """
    Format notebook cells into a readable table format.
    
    Args:
        ydoc_cells: The cells from the notebook's Y document
        
    Returns:
        str: Formatted table string with cell information
    """
    total_cells = len(ydoc_cells)
    
    if total_cells == 0:
        return "Notebook is empty, no cells found."
    
    # Create header
    lines = ["Index\tType\tCount\tFirst Line"]
    lines.append("-" * 60)  # Separator line
    
    # Process each cell
    for i, cell_data in enumerate(ydoc_cells):
        cell_type = cell_data.get("cell_type", "unknown")
        
        # Get execution count for code cells
        if cell_type == "code":
            execution_count = cell_data.get("execution_count") or "None"
        else:
            execution_count = "N/A"
        
        # Get first line of source
        source = cell_data.get("source", "")
        if isinstance(source, list):
            first_line = source[0] if source else ""
        else:
            first_line = str(source)
        
        # Get just the first line and truncate if too long
        first_line = first_line.split('\n')[0]
        if len(first_line) > 50:
            first_line = first_line[:47] + "..."
        
        # Add to table
        lines.append(f"{i}\t{cell_type}\t{execution_count}\t{first_line}")
    
    return "\n".join(lines)

def get_surrounding_cells_info(notebook, cell_index: int, total_cells: int) -> str:
    """Get information about surrounding cells for context."""
    start_index = max(0, cell_index - 5)
    end_index = min(total_cells, cell_index + 6)
    
    if total_cells == 0:
        return "Notebook is now empty, no cells remaining"
    
    lines = ["Index\tType\tCount\tFirst Line"]
    lines.append("-" * 60)
    
    for i in range(start_index, end_index):
        if i >= total_cells:
            break
            
        ydoc = notebook._doc
        cell_data = ydoc._ycells[i]
        cell_type = cell_data.get("cell_type", "unknown")
        
        # Get execution count for code cells
        if cell_type == "code":
            execution_count = cell_data.get("execution_count") or "None"
        else:
            execution_count = "N/A"
        
        # Get first line of source
        source = cell_data.get("source", "")
        if isinstance(source, list):
            first_line = source[0] if source else ""
        else:
            first_line = str(source)
        
        # Get just the first line and truncate if too long
        first_line = first_line.split('\n')[0]
        if len(first_line) > 50:
            first_line = first_line[:47] + "..."
        
        # Mark the target cell
        marker = " ← inserted" if i == cell_index else ""
        
        lines.append(f"{i}\t{cell_type}\t{execution_count}\t{first_line}{marker}")
    
    return "\n".join(lines)