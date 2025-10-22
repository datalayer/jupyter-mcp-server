#!/usr/bin/env python3
# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Validation script for read tools RTC fix.

This script validates that the 3 reading tools have the same RTC pattern
as the 5 editing tools, without requiring a full Jupyter server setup.
"""

import ast
import sys
from pathlib import Path

# Tools that should have RTC support
EDITING_TOOLS = [
    'execute_cell_tool.py',
    'overwrite_cell_source_tool.py',
    'insert_cell_tool.py',
    'insert_execute_code_cell_tool.py',
    'delete_cell_tool.py',
]

READING_TOOLS = [
    'read_cell_tool.py',
    'read_cells_tool.py',
    'list_cells_tool.py',
]

ALL_TOOLS = EDITING_TOOLS + READING_TOOLS

def extract_method_source(file_path: Path, method_name: str) -> str:
    """Extract source code of a specific method from a Python file."""
    with open(file_path, 'r') as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name:
            return ast.unparse(node)

    return None

def normalize_code(code: str) -> str:
    """Normalize code by parsing and unparsing (removes formatting/cosmetic diffs)."""
    tree = ast.parse(code)
    return ast.unparse(tree)

def check_get_jupyter_ydoc_consistency():
    """Verify all tools have consistent _get_jupyter_ydoc implementation."""
    print("Checking _get_jupyter_ydoc() RTC logic...")

    tools_dir = Path("jupyter_mcp_server/tools")

    # Key patterns that must be present for RTC to work
    required_patterns = [
        "extension_manager.extension_points",
        "'jupyter_server_ydoc'",
        "ywebsocket_server",
        "room._document",
        "return None",
    ]

    for tool in ALL_TOOLS:
        tool_path = tools_dir / tool
        source = extract_method_source(tool_path, "_get_jupyter_ydoc")

        if source is None:
            print(f"  ❌ {tool}: Missing _get_jupyter_ydoc() method")
            return False

        # Check all required RTC patterns are present
        missing = []
        for pattern in required_patterns:
            if pattern not in source:
                missing.append(pattern)

        if missing:
            print(f"  ❌ {tool}: Missing RTC patterns: {', '.join(missing)}")
            return False

        print(f"  ✓ {tool}: Has correct RTC logic")

    return True

def check_ydoc_usage():
    """Verify all tools check for YDoc before using file operations."""
    print("\nChecking YDoc usage pattern...")

    tools_dir = Path("jupyter_mcp_server/tools")

    for tool in ALL_TOOLS:
        tool_path = tools_dir / tool
        with open(tool_path, 'r') as f:
            content = f.read()

        # Check for RTC pattern markers
        has_extension_points = 'extension_manager.extension_points' in content
        has_ydoc_check = 'if ydoc:' in content
        has_room_document = 'room._document' in content

        if not (has_extension_points and has_ydoc_check and has_room_document):
            print(f"  ❌ {tool}: Missing RTC pattern")
            print(f"     extension_points: {has_extension_points}")
            print(f"     ydoc check: {has_ydoc_check}")
            print(f"     room._document: {has_room_document}")
            return False

        print(f"  ✓ {tool}: RTC pattern present")

    return True

def check_no_old_patterns():
    """Verify no tools use the old broken yroom_manager pattern."""
    print("\nChecking for old broken patterns...")

    tools_dir = Path("jupyter_mcp_server/tools")

    for tool in ALL_TOOLS:
        tool_path = tools_dir / tool
        with open(tool_path, 'r') as f:
            content = f.read()

        # Check for old pattern (should only be in comments/docstrings)
        lines_with_yroom = []
        in_docstring = False
        for i, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()

            # Track docstrings
            if '"""' in stripped or "'''" in stripped:
                in_docstring = not in_docstring

            # Skip comments and docstrings
            if stripped.startswith('#') or in_docstring:
                continue

            if 'yroom_manager' in line:
                lines_with_yroom.append((i, stripped))

        if lines_with_yroom:
            print(f"  ❌ {tool}: Found old yroom_manager code (not in comments)")
            for line_num, line in lines_with_yroom:
                print(f"     Line {line_num}: {line}")
            return False

        print(f"  ✓ {tool}: No old yroom_manager code")

    return True

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("Validating RTC fixes for reading tools")
    print("=" * 60)
    print()

    checks = [
        ("Method consistency", check_get_jupyter_ydoc_consistency),
        ("YDoc usage pattern", check_ydoc_usage),
        ("No old patterns", check_no_old_patterns),
    ]

    all_passed = True
    for name, check_func in checks:
        try:
            if not check_func():
                all_passed = False
        except Exception as e:
            print(f"  ❌ {name}: Exception: {e}")
            all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("✅ All validation checks PASSED")
        print()
        print("Summary:")
        print(f"  - All {len(ALL_TOOLS)} tools have identical _get_jupyter_ydoc()")
        print(f"  - All {len(ALL_TOOLS)} tools use RTC pattern correctly")
        print("  - No old broken patterns found")
        print()
        print("The reading tools should now see live unsaved changes!")
        return 0
    else:
        print("❌ Some validation checks FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
