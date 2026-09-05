# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for stripping ANSI escape sequences out of cell output.

strip_ansi_codes matched only the SGR colour sequences, so every other escape
a kernel writes survived into the text handed back to the client. A nested
tqdm bar moves the cursor with ESC[A on each redraw whether or not the stream
is a terminal, and those bytes came through in the stream output.
"""

from jupyter_mcp_server.utils import extract_output, strip_ansi_codes

# Two redraws of a nested tqdm bar, captured from tqdm writing to a
# non-terminal stream with position=1.
NESTED_TQDM_TEXT = (
    "\r  0%|   | 0/2 [00:00<?, ?it/s]\x1b[A\n"
    "\r 50%|5| 1/2 [00:00<00:00, 1075it/s]\x1b[A\n"
)


def test_colour_sequences_are_still_stripped():
    assert strip_ansi_codes("\x1b[31mred\x1b[0m") == "red"


def test_cursor_movement_is_stripped():
    assert strip_ansi_codes("done\x1b[A") == "done"


def test_erase_line_and_cursor_visibility_are_stripped():
    assert strip_ansi_codes("\x1b[2K\x1b[?25lworking\x1b[?25h") == "working"


def test_a_nested_progress_bar_reads_back_without_escapes():
    stream = {"output_type": "stream", "name": "stderr", "text": NESTED_TQDM_TEXT}
    assert "\x1b" not in extract_output(stream)


def test_brackets_without_an_escape_are_left_alone():
    assert strip_ansi_codes("matched [0-9]* twice") == "matched [0-9]* twice"
