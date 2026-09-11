# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for stripping ANSI escape sequences out of cell output.

strip_ansi_codes matched only the SGR colour sequences, so every other escape
a kernel writes survived into the text handed back to the client. A nested
tqdm bar moves the cursor with ESC[A on each redraw whether or not the stream
is a terminal, and those bytes came through in the stream output.

Widening the pattern to every CSI sequence left the escapes that are not CSI.
An OSC string carries a hyperlink or a window title and is what rich writes for
a link, and a kernel can also emit the two character forms and the device
control strings. None of those are CSI, so all of them still came through.
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


# A link printed by rich, which writes an OSC 8 hyperlink whenever it believes
# it is writing to a terminal, as it does inside Jupyter.
RICH_HYPERLINK_TEXT = (
    "see \x1b]8;id=12903882;https://example.com\x1b\\the docs\x1b]8;;\x1b\\ for details\n"
)


def test_an_osc_hyperlink_is_stripped():
    assert strip_ansi_codes(RICH_HYPERLINK_TEXT) == "see the docs for details\n"


def test_an_osc_string_terminated_by_bel_is_stripped():
    assert strip_ansi_codes("\x1b]0;window title\x07text") == "text"


def test_two_character_escapes_are_stripped():
    assert strip_ansi_codes("a\x1b7b\x1b8c") == "abc"
    assert strip_ansi_codes("a\x1bMb") == "ab"


def test_a_charset_selection_is_stripped():
    assert strip_ansi_codes("\x1b(Btext") == "text"


def test_a_device_control_string_is_stripped():
    assert strip_ansi_codes("a\x1bPsomething\x1b\\b") == "ab"


def test_a_rich_link_reads_back_without_escapes():
    stream = {"output_type": "stream", "name": "stdout", "text": RICH_HYPERLINK_TEXT}
    assert "\x1b" not in extract_output(stream)
