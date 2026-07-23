# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for the text extract_output surfaces from a rich-display bundle.

IPython.display.* objects emit a MIME bundle whose text/plain is only the bare
object repr (e.g. "<IPython.core.display.Markdown object>"); the readable
content lives in a richer key (text/markdown, text/latex, application/json).
These tests pin that extract_output returns that content instead of the repr,
while leaving ordinary text/plain results (and the text/html placeholder)
unchanged.
"""

import json

from jupyter_mcp_server.utils import extract_output

MARKDOWN_OUTPUT = {
    "output_type": "execute_result",
    "data": {
        "text/plain": "<IPython.core.display.Markdown object>",
        "text/markdown": "# hi",
    },
}

LATEX_OUTPUT = {
    "output_type": "execute_result",
    "data": {
        "text/plain": "<IPython.core.display.Latex object>",
        "text/latex": "$x^2$",
    },
}

JSON_OUTPUT = {
    "output_type": "execute_result",
    "data": {
        "text/plain": "<IPython.core.display.JSON object>",
        "application/json": {"a": 1, "b": [2, 3]},
    },
}

PLAIN_ONLY_OUTPUT = {
    "output_type": "execute_result",
    "data": {"text/plain": "42"},
}

# A pandas DataFrame emits both a readable text/plain table and a text/html
# table. The ASCII table must win: text/html must not override a real
# text/plain.
PLAIN_AND_HTML_OUTPUT = {
    "output_type": "execute_result",
    "data": {"text/plain": "   a\n0  1", "text/html": "<table>...</table>"},
}

HTML_ONLY_OUTPUT = {
    "output_type": "display_data",
    "data": {"text/html": "<b>bold</b>"},
}


def test_markdown_returns_source_not_repr():
    assert extract_output(MARKDOWN_OUTPUT) == "# hi"


def test_latex_returns_source_not_repr():
    assert extract_output(LATEX_OUTPUT) == "$x^2$"


def test_json_returns_payload_not_repr():
    result = extract_output(JSON_OUTPUT)
    # The readable JSON content is surfaced, not the "<...JSON object>" repr.
    assert "IPython" not in result
    assert json.loads(result) == {"a": 1, "b": [2, 3]}


def test_plain_only_output_unchanged():
    assert extract_output(PLAIN_ONLY_OUTPUT) == "42"


def test_text_html_does_not_override_real_text_plain():
    assert extract_output(PLAIN_AND_HTML_OUTPUT) == "   a\n0  1"


def test_html_only_placeholder_unchanged():
    # text/html handling is intentionally left as-is (out of scope here).
    assert extract_output(HTML_ONLY_OUTPUT) == "[HTML Output]"
