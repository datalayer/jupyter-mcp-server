#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Addressing a cell by something that survives an edit.

Every cell tool took a `cell_index`. An index is a position, and a position is
only true until somebody inserts a cell above it — which, in a notebook a
person and an agent are both working in, is constantly. The agent reads cell 3,
decides to fix it, and by the time the edit lands cell 3 is a different cell.
Nothing errors. The wrong cell is quietly overwritten.

nbformat 4.5 gave every cell an id for exactly this. These tests hold the two
halves that make it usable: every result says which id it acted on (an agent
can only use ids it has been given), and an id that is gone is an error naming
it rather than a fall back to the index it came with — falling back would edit
an arbitrary cell in the name of safety, which is the failure this prevents.

Launch the tests:
```
$ pytest tests/test_cell_ids.py -v
```
"""

import asyncio

import pytest

from jupyter_mcp_server import cell_ids, results
from jupyter_mcp_server.cell_ids import UnknownCellId, resolve, resolve_many
from jupyter_mcp_server.results import meta_key, structured


@pytest.fixture
def notebook(monkeypatch):
    """A notebook whose cell ids the resolver can read."""

    def _install(*ids, fail=False):
        async def _ids(**_keywords):
            if fail:
                raise RuntimeError("the notebook could not be read")
            return list(ids)

        monkeypatch.setattr(cell_ids, "cell_ids", _ids)

    return _install


async def _in_a_call(coroutine_factory):
    """Run something as a tool call, so `add_meta` has somewhere to collect."""
    captured = {}

    @structured("cell.test")
    async def call():
        captured["value"] = await coroutine_factory()
        return "done"

    answer = await call()
    return captured["value"], answer


class TestReadingAnIdOffACell:
    """Three representations, and they do not share a base class."""

    def test_a_ydoc_cell_is_mapping_like_but_not_a_dict(self):
        """The bug this test exists for. A YDoc cell is a `pycrdt.Map`:
        it answers `.get("id")` and it is emphatically not a `dict`, so an
        `isinstance(cell, dict)` check returns empty for every cell — and
        does it silently, so the whole feature does nothing and nothing says
        why."""

        class Map:
            def __init__(self, values):
                self._values = values

            def get(self, key, default=None):
                return self._values.get(key, default)

        assert cell_ids._id_of(Map({"id": "c-1"})) == "c-1"

    def test_a_file_cell_is_a_dict_with_attributes(self):
        import nbformat

        cell = nbformat.v4.new_code_cell(source="x")
        cell["id"] = "c-2"
        assert cell_ids._id_of(cell) == "c-2"

    def test_a_cell_from_before_nbformat_45_has_no_id(self):
        """Empty is the honest answer. An id generated on read differs on the
        next read, so it would name a cell only until somebody looked."""

        class Old:
            def get(self, key, default=None):
                return default

        assert cell_ids._id_of(Old()) == ""

    def test_something_whose_get_raises_falls_back_to_the_attribute(self):
        class Awkward:
            def get(self, key, default=None):
                raise RuntimeError("not that kind of get")

            id = "c-3"

        assert cell_ids._id_of(Awkward()) == "c-3"


class TestAddressingByIndex:
    def test_the_index_is_used_as_given(self, notebook):
        notebook("a", "b", "c")
        index, _ = asyncio.run(_in_a_call(lambda: resolve(cell_index=1, mode=None)))
        assert index == 1

    def test_the_result_says_which_cell_was_acted_on(self, notebook):
        """An agent can only address a cell by id if it has been given one.
        Attaching it is what makes the whole feature reachable."""
        notebook("a", "b", "c")
        _, answer = asyncio.run(_in_a_call(lambda: resolve(cell_index=1, mode=None)))
        assert answer.meta[meta_key("cell_id")] == "b"

    def test_an_index_past_the_end_is_left_to_the_tool(self, notebook):
        """The tools already validate ranges and say something useful about
        them. Failing here first would replace a good message with a worse
        one."""
        notebook("a", "b")
        index, answer = asyncio.run(_in_a_call(lambda: resolve(cell_index=9, mode=None)))
        assert index == 9
        assert answer.meta is None

    def test_a_notebook_without_ids_still_works(self, notebook):
        """Written before nbformat 4.5. Nothing to attach, and nothing that
        should stop the call."""
        notebook("", "", "")
        index, answer = asyncio.run(_in_a_call(lambda: resolve(cell_index=1, mode=None)))
        assert index == 1
        assert answer.meta is None

    def test_a_notebook_that_cannot_be_read_does_not_fail_the_call(self, notebook):
        """The tool is about to read it its own way and will say something
        proper about it. Losing the result's id is not worth failing for."""
        notebook(fail=True)
        index, _ = asyncio.run(_in_a_call(lambda: resolve(cell_index=1, mode=None)))
        assert index == 1


class TestAddressingById:
    def test_the_id_becomes_the_current_index(self, notebook):
        notebook("a", "b", "c")
        index, _ = asyncio.run(_in_a_call(lambda: resolve(cell_id="c", mode=None)))
        assert index == 2

    def test_the_id_wins_over_a_stale_index(self, notebook):
        """The whole point. The agent read cell 1, somebody inserted a cell
        above it, and the agent's edit must still land on the cell it read."""
        notebook("new", "a", "b", "c")
        index, _ = asyncio.run(
            _in_a_call(lambda: resolve(cell_index=1, cell_id="c", mode=None))
        )
        assert index == 3

    def test_an_id_that_is_gone_is_an_error_naming_it(self, notebook):
        notebook("a", "b")
        with pytest.raises(UnknownCellId, match="gone-id"):
            asyncio.run(_in_a_call(lambda: resolve(cell_id="gone-id", mode=None)))

    def test_an_id_that_is_gone_never_falls_back_to_the_index(self, notebook):
        """Falling back would edit an arbitrary cell in the name of being
        forgiving — which is exactly the accident the id exists to stop."""
        notebook("a", "b")
        with pytest.raises(UnknownCellId):
            asyncio.run(_in_a_call(lambda: resolve(cell_index=0, cell_id="gone", mode=None)))

    def test_an_unreadable_notebook_refuses_rather_than_guesses(self, notebook):
        """There is no index to fall back to that means anything."""
        notebook(fail=True)
        with pytest.raises(UnknownCellId):
            asyncio.run(_in_a_call(lambda: resolve(cell_index=0, cell_id="c", mode=None)))

    def test_naming_neither_is_refused(self):
        with pytest.raises(ValueError, match="cell_index or by cell_id"):
            asyncio.run(_in_a_call(lambda: resolve(mode=None)))


class TestSeveralCellsAtOnce:
    def test_ids_become_indices_in_the_order_given(self, notebook):
        notebook("a", "b", "c", "d")
        indices, _ = asyncio.run(
            _in_a_call(lambda: resolve_many(cell_ids_wanted=["d", "b"], mode=None))
        )
        assert indices == [3, 1]

    def test_one_bad_id_fails_the_whole_call(self, notebook):
        """Resolved before anything is touched, so a bad id in a list cannot
        half-delete a notebook."""
        notebook("a", "b")
        with pytest.raises(UnknownCellId, match="gone"):
            asyncio.run(
                _in_a_call(lambda: resolve_many(cell_ids_wanted=["a", "gone"], mode=None))
            )

    def test_the_error_says_how_many_more_are_missing(self, notebook):
        notebook("a")
        with pytest.raises(UnknownCellId, match="1 more"):
            asyncio.run(
                _in_a_call(lambda: resolve_many(cell_ids_wanted=["x", "y"], mode=None))
            )

    def test_the_result_says_which_cells_were_acted_on(self, notebook):
        notebook("a", "b", "c")
        _, answer = asyncio.run(
            _in_a_call(lambda: resolve_many(cell_indices=[0, 2], mode=None))
        )
        assert answer.meta[meta_key("cell_ids")] == ["a", "c"]

    def test_naming_neither_is_refused(self):
        with pytest.raises(ValueError, match="cell_indices or by cell_ids"):
            asyncio.run(_in_a_call(lambda: resolve_many(mode=None)))


class TestEveryCellToolOffersIt:
    """The feature is only real if the tools expose it."""

    @pytest.fixture(scope="class")
    def tools(self):
        import jupyter_mcp_server.server as server_module

        return {tool.name: tool for tool in asyncio.run(server_module.mcp.list_tools())}

    @pytest.mark.parametrize(
        "name",
        [
            "read_cell", "execute_cell", "edit_cell_source",
            "overwrite_cell_source", "clear_cell_output",
        ],
    )
    def test_a_single_cell_tool_takes_an_id(self, tools, name):
        assert "cell_id" in tools[name].input_schema["properties"]

    def test_deleting_takes_ids(self, tools):
        assert "cell_ids_to_delete" in tools["delete_cell"].input_schema["properties"]

    def test_moving_takes_ids_for_both_ends(self, tools):
        properties = tools["move_cell"].input_schema["properties"]
        assert "source_cell_id" in properties and "target_cell_id" in properties

    @pytest.mark.parametrize(
        "name",
        [
            "read_cell", "execute_cell", "edit_cell_source", "overwrite_cell_source",
            "clear_cell_output", "delete_cell", "move_cell",
        ],
    )
    def test_the_index_is_no_longer_required(self, tools, name):
        """An id alone has to be enough, or the id is unusable."""
        required = tools[name].input_schema.get("required", [])
        assert not [field for field in required if "index" in field], required
