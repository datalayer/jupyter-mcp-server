# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Utility functions for the Jupyter-to-MCP adapter."""

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def safe_json_dumps(obj: Any, default_str: str = "Unable to serialize") -> str:
    """Safely convert an object to JSON string."""
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError) as e:
        logger.warning("Failed to serialize object to JSON: %s", e)
        return default_str


def extract_session_id_from_headers(headers: Dict[str, Any]) -> str:
    """Extract or generate session ID from HTTP headers."""
    session_id = headers.get('x-session-id') or headers.get('X-Session-ID')
    if not session_id:
        # Generate a new session ID if not provided
        from .adapter import generate_session_id
        session_id = generate_session_id()
    return session_id


def format_error_response(message: str, status_code: int = 500, error_code: int = -32603) -> Dict[str, Any]:
    """Format an error response in MCP style."""
    return {
        "error": {
            "code": error_code,
            "message": message
        },
        "message": message,
        "status_code": status_code
    }


def validate_tool_arguments(arguments: Dict[str, Any]) -> bool:
    """Basic validation of tool arguments."""
    # This is a basic validation - could be enhanced with JSON Schema
    return isinstance(arguments, dict)


def clean_tool_name(name: str) -> str:
    """Clean and validate tool name."""
    if not name or not isinstance(name, str):
        raise ValueError("Tool name must be a non-empty string")
    
    # Remove any potentially dangerous characters
    cleaned = "".join(c for c in name if c.isalnum() or c in "_-")
    if not cleaned:
        raise ValueError(f"Invalid tool name: {name}")
    
    return cleaned
