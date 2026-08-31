# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for reading back an error output that carries no traceback.

A kernel may report an error with an empty traceback, and
execute_via_execution_stack builds exactly that shape when ExecutionStack
reports a request-level failure. extract_output rendered such an output as the
empty string, safe_extract_outputs drops an empty rendering, and the cell then
read back with no sign that it had failed at all.
"""

from jupyter_mcp_server.models import Cell
from jupyter_mcp_server.utils import extract_output, safe_extract_outputs

NO_TRACEBACK_OUTPUT = {
    "output_type": "error",
    "ename": "ExecutionError",
    "evalue": "Kernel 5f1c not found",
    "traceback": [],
}

WITH_TRACEBACK_OUTPUT = {
    "output_type": "error",
    "ename": "ZeroDivisionError",
    "evalue": "division by zero",
    "traceback": [
        "Traceback (most recent call last):",
        "ZeroDivisionError: division by zero",
    ],
}

STREAM_OUTPUT = {"output_type": "stream", "name": "stdout", "text": "starting\n"}


def test_error_without_traceback_reports_name_and_message():
    assert extract_output(NO_TRACEBACK_OUTPUT) == "ExecutionError: Kernel 5f1c not found"


def test_error_without_traceback_survives_safe_extract_outputs():
    assert safe_extract_outputs([NO_TRACEBACK_OUTPUT]) == [
        "ExecutionError: Kernel 5f1c not found"
    ]


def test_a_cell_that_printed_then_failed_still_shows_the_failure():
    cell = Cell(
        cell_type="code",
        source="run()",
        execution_count=1,
        outputs=[STREAM_OUTPUT, NO_TRACEBACK_OUTPUT],
        metadata={},
    )
    assert cell.get_outputs("readable") == [
        "starting\n",
        "ExecutionError: Kernel 5f1c not found",
    ]


def test_error_with_a_traceback_is_unchanged():
    assert extract_output(WITH_TRACEBACK_OUTPUT) == (
        "Traceback (most recent call last):\nZeroDivisionError: division by zero"
    )


def test_an_error_with_nothing_at_all_is_still_reported():
    assert extract_output({"output_type": "error"}) == "[Error output with no details]"
