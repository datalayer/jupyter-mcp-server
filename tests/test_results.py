#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""One place that knows what a tool result looks like on the wire.

A `tools/call` may answer with `content` — text and images, for a person and
for the model — and with `structuredContent`, the same answer as data. A
server cannot know which of the two a client puts in front of the model, and
the Core Primitives Working Group is redesigning that contract for exactly
that reason; content annotations (`audience`, `priority`) are in the same
discussion and may be deprecated outright.

So the shape is built in `results.py` and nowhere else, and these tests are
what say so. The two that matter most:

- text is never dropped. A result with `structuredContent` and empty
  `content` is invisible to every client that has not adopted the former,
  which is most of them.
- `result` keeps carrying the answer. It is the key the SDK's own
  `wrap_output` used, so a client reading it goes on working; the structured
  extras are additions beside it, not a replacement for it.

Launch the tests:
```
$ pytest tests/test_results.py -v
```
"""

import asyncio

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from jupyter_mcp_server import results
from jupyter_mcp_server.results import add_meta, answer, as_text, meta_key, structured


def _image():
    return ImageContent(type="image", data="AAAA", mimeType="image/png")


class TestTheShapeItself:
    def test_a_string_answer_keeps_its_text(self):
        built = answer("done", kind="cell.edit")
        assert isinstance(built, CallToolResult)
        assert built.content[0].text == "done"

    def test_a_string_answer_is_also_data(self):
        built = answer("done", kind="cell.edit")
        assert built.structured_content == {"kind": "cell.edit", "result": "done"}

    def test_the_kind_says_what_the_answer_is(self):
        """So a client can tell one answer from another without matching
        prose that was written for a model to read."""
        assert answer("x", kind="notebooks.list").structured_content["kind"] == (
            "notebooks.list"
        )

    def test_text_is_never_dropped(self):
        """A result with structuredContent and empty content is invisible to
        a client that has not adopted structuredContent — which is most of
        them. Structure is an addition, never a replacement."""
        built = answer({"a": 1}, kind="thing", shape=lambda value: value)
        assert built.content, "the answer has no readable content at all"
        assert "a" in built.content[0].text

    def test_an_image_survives_as_an_image(self):
        """Rendering it as text would throw the picture away."""
        built = answer(["before", _image(), "after"], kind="cell.execute")
        kinds = [block.type for block in built.content]
        assert kinds == ["text", "image", "text"]

    def test_a_shaping_bug_does_not_lose_the_answer(self):
        """The answer is what the caller asked for; the structure is a
        convenience. Losing the first to a bug in the second is the wrong
        trade every time."""

        def explode(_value):
            raise RuntimeError("bad shape")

        built = answer("the answer", kind="thing", shape=explode)
        assert built.content[0].text == "the answer"
        assert built.structured_content["result"] == "the answer"

    def test_a_shape_that_is_not_a_mapping_is_still_carried(self):
        built = answer("x", kind="thing", shape=lambda value: [1, 2])
        assert built.structured_content["result"] == [1, 2]


class TestAnnotationsAreSetInOnePlace:
    def test_an_audience_reaches_the_content(self):
        built = answer("x", kind="thing", audience=(results.AUDIENCE_ASSISTANT,))
        assert built.content[0].annotations.audience == ["assistant"]

    def test_a_priority_reaches_the_content(self):
        built = answer("x", kind="thing", priority=0.9)
        assert built.content[0].annotations.priority == 0.9

    def test_nothing_to_say_means_no_annotations_at_all(self):
        """Rather than an empty object, which a client has to interpret."""
        assert answer("x", kind="thing").content[0].annotations is None

    def test_annotations_are_built_nowhere_else(self):
        """If the Working Group deprecates them, one function stops
        returning them and no tool changes."""
        import pathlib
        import re

        import jupyter_mcp_server

        # Content annotations (audience, priority), not `ToolAnnotations` —
        # the hints on a tool, which belong on each tool's own decorator.
        content_annotations = re.compile(r"(?<!Tool)\bAnnotations\(")
        root = pathlib.Path(jupyter_mcp_server.__file__).parent
        offenders = [
            path.name
            for path in root.rglob("*.py")
            if path.name != "results.py" and content_annotations.search(path.read_text())
        ]
        assert not offenders, f"content annotations built outside results.py: {offenders}"


class TestFactsAttachedFromWhereverTheyAreKnown:
    def test_a_tool_can_attach_facts_to_its_own_result(self):
        @structured("cell.edit")
        async def edit():
            add_meta(cell_id="c-1")
            return "edited"

        assert asyncio.run(edit()).meta == {meta_key("cell_id"): "c-1"}

    def test_the_keys_are_namespaced(self):
        """`_meta` is shared with the protocol and every other extension. A
        bare `cell_id` is a collision waiting to happen."""
        assert meta_key("cell_id").startswith("io.jupyter-mcp/")

    def test_nothing_attached_means_no_meta_at_all(self):
        @structured("cell.edit")
        async def edit():
            return "edited"

        assert asyncio.run(edit()).meta is None

    def test_a_none_is_not_attached(self):
        """An id nobody resolved is absent, not present and null — a client
        reading it back would treat null as a real answer."""

        @structured("cell.edit")
        async def edit():
            add_meta(cell_id=None, notebook="nb")
            return "edited"

        assert asyncio.run(edit()).meta == {meta_key("notebook"): "nb"}

    def test_attaching_outside_a_tool_call_is_harmless(self):
        """The helpers that know these facts are shared with code paths that
        are not tool calls — the Jupyter Server handlers, the tests."""
        add_meta(cell_id="c-1")

    def test_a_finished_call_leaves_nothing_collecting_behind_it(self):
        """Without the reset, the dictionary of the last call stays current
        in this context: a helper attaching a fact from a non-tool code path
        afterwards writes into a result that has already been sent, and the
        next call in the same context inherits it."""

        @structured("cell.edit")
        async def edit():
            add_meta(cell_id="c-1")
            return "edited"

        async def two_calls_in_one_context():
            # How the server actually runs them: awaited inside one request
            # context, not each in a fresh event loop.
            first = await edit()
            add_meta(cell_id="stray")
            still_collecting = results._pending.get()
            second = await edit()
            return first, second, still_collecting

        first, second, still_collecting = asyncio.run(two_calls_in_one_context())
        assert still_collecting is None, "a finished call is still collecting"
        assert first.meta == second.meta == {meta_key("cell_id"): "c-1"}

    def test_one_calls_facts_do_not_leak_into_the_next(self):
        """A context variable per call, reset on the way out. Sharing it
        would attach one notebook's cell id to another notebook's answer."""

        @structured("cell.edit")
        async def edit(**values):
            add_meta(**values)
            return "edited"

        first = asyncio.run(edit(cell_id="c-1"))
        second = asyncio.run(edit(notebook="nb"))
        assert first.meta == {meta_key("cell_id"): "c-1"}
        assert second.meta == {meta_key("notebook"): "nb"}

    def test_a_raising_tool_still_raises(self):
        """The failure path is the SDK's, untouched: a tool that raises must
        reach the client's error handling, not be turned into a result."""

        @structured("cell.edit")
        async def edit():
            raise ValueError("cell 3 is out of range")

        with pytest.raises(ValueError, match="out of range"):
            asyncio.run(edit())


class TestTheTextRendering:
    def test_a_string_renders_as_itself(self):
        assert as_text("hello") == "hello"

    def test_nothing_renders_as_nothing(self):
        assert as_text(None) == ""

    def test_data_renders_as_readable_json(self):
        assert '"a": 1' in as_text({"a": 1})

    def test_something_unserialisable_still_renders(self):
        assert as_text(object())


class TestEveryToolGoesThroughIt:
    def test_all_eighteen_are_decorated(self):
        import pathlib

        import jupyter_mcp_server.server as server_module

        source = pathlib.Path(server_module.__file__).read_text()
        assert source.count("@mcp.tool(") == source.count("@structured(")

    def test_no_tool_advertises_an_output_schema_it_does_not_build(self):
        """`structured` builds the structured answer itself, so the SDK must
        not also check it against a schema derived from a return annotation
        that describes a string."""
        import asyncio as _asyncio

        from jupyter_mcp_server.server import mcp

        listed = _asyncio.run(mcp.list_tools())
        assert not [tool.name for tool in listed if tool.output_schema]

    def test_the_shapes_all_keep_the_answer_under_result(self):
        """Whatever a tool is, one key holds its answer. A client that reads
        `result` never has to know which tool it called."""
        from jupyter_mcp_server.server import _outputs, _rows

        assert "result" in _rows("a\tb\n1\t2")
        assert "result" in _rows("not a table")
        assert "result" in _outputs(["one", "two"])

    def test_a_table_becomes_rows_a_client_can_use(self):
        """An agent wanting one field out of a TSV table had to split the
        text and hope the columns had not moved."""
        from jupyter_mcp_server.server import _rows

        shaped = _rows("ID\tName\nk-1\tPython 3\nk-2\tR")
        assert shaped["columns"] == ["ID", "Name"]
        assert shaped["items"][0] == {"ID": "k-1", "Name": "Python 3"}
        assert shaped["count"] == 2

    def test_something_that_is_not_a_table_is_left_as_a_message(self):
        from jupyter_mcp_server.server import _rows

        assert _rows("No notebooks are open.")["result"] == "No notebooks are open."

    def test_outputs_keep_their_order_and_say_where_the_images_were(self):
        from jupyter_mcp_server.server import _outputs

        shaped = _outputs(["before", _image(), "after"])
        assert shaped["result"] == ["before", "after"]
        assert [entry["type"] for entry in shaped["outputs"]] == ["text", "image", "text"]
        assert shaped["images"] == 1
