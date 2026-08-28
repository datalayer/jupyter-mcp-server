#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What a client is told about a tool before it calls it.

A client decides two things from a tool's annotations: whether to ask a person
first, and whether it is safe to retry. Both defaults are the cautious ones —
`idempotentHint` defaults to false, `openWorldHint` to true — so a tool that
says nothing is treated as unsafe to repeat and as reaching an open-ended
world. That is the right default and the wrong *answer* for most of the tools
here: reading a cell is perfectly safe to repeat, and listing notebooks does
not reach anything beyond one known server.

Getting these wrong in the other direction is worse than leaving them out.
`idempotentHint: true` on `insert_cell` would invite a client to retry a
timed-out call and insert the cell twice. So each one is asserted here rather
than left to whoever edits the decorator next.

Launch the tests:
```
$ pytest tests/test_tool_annotations.py -v
```
"""

import asyncio

import pytest

from jupyter_mcp_server.server import mcp


@pytest.fixture(scope="module")
def tools():
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def _hints(tool):
    annotations = tool.annotations
    return {
        "read_only": getattr(annotations, "read_only_hint", None),
        "destructive": getattr(annotations, "destructive_hint", None),
        "idempotent": getattr(annotations, "idempotent_hint", None),
        "open_world": getattr(annotations, "open_world_hint", None),
    }


class TestEveryToolSaysAll4:
    def test_every_tool_is_annotated_at_all(self, tools):
        missing = [name for name, tool in tools.items() if tool.annotations is None]
        assert not missing, f"no annotations: {missing}"

    def test_every_tool_answers_idempotent_and_open_world(self, tools):
        """Left unset, the defaults answer for them — and the defaults are
        wrong for most of these."""
        missing = [
            name
            for name, tool in tools.items()
            if _hints(tool)["idempotent"] is None or _hints(tool)["open_world"] is None
        ]
        assert not missing, f"no idempotent/open-world hint: {missing}"

    def test_every_tool_has_a_title(self, tools):
        """It is what a person sees in a consent prompt."""
        untitled = [name for name, tool in tools.items() if not (tool.annotations.title or "")]
        assert not untitled


class TestReadingIsSafeToRepeat:
    @pytest.mark.parametrize(
        "name", ["read_cell", "read_notebook", "list_notebooks", "list_files", "list_kernels"]
    )
    def test_a_read_is_read_only_and_idempotent(self, tools, name):
        hints = _hints(tools[name])
        assert hints["read_only"] is True
        assert hints["idempotent"] is True

    @pytest.mark.parametrize(
        "name", ["read_cell", "read_notebook", "list_notebooks", "list_files", "list_kernels"]
    )
    def test_a_read_is_not_also_destructive(self, tools, name):
        """`readOnlyHint` means the tool changes nothing; saying both leaves
        a client with no way to decide whether to ask a person first."""
        assert _hints(tools[name])["destructive"] is not True


class TestRepeatingAWriteIsNotAlwaysSafe:
    @pytest.mark.parametrize("name", ["insert_cell", "delete_cell", "move_cell"])
    def test_a_positional_edit_is_not_idempotent(self, tools, name):
        """The dangerous one. `delete_cell(3)` twice deletes two different
        cells; `insert_cell` twice inserts two. A client that retried a
        timed-out call on the strength of an idempotent hint would do real
        damage to somebody's notebook."""
        assert _hints(tools[name])["idempotent"] is False

    @pytest.mark.parametrize("name", ["overwrite_cell_source", "clear_cell_output"])
    def test_setting_a_value_is_idempotent(self, tools, name):
        """The same call twice leaves the same value, so a client may retry
        one that timed out rather than leaving a notebook half-edited."""
        assert _hints(tools[name])["idempotent"] is True

    def test_a_find_and_replace_is_not_idempotent(self, tools):
        """`edit_cell_source` replaces `old_string` with `new_string`. If the
        replacement contains the thing it replaced, applying it again
        changes the cell again."""
        assert _hints(tools["edit_cell_source"])["idempotent"] is False

    def test_restarting_is_not_idempotent(self, tools):
        """Each restart throws away a different session."""
        assert _hints(tools["restart_notebook"])["idempotent"] is False


class TestOnlyRunningCodeReachesTheOpenWorld:
    @pytest.mark.parametrize(
        "name", ["execute_cell", "execute_code", "insert_execute_code_cell"]
    )
    def test_running_code_is_open_world(self, tools, name):
        """Arbitrary code can reach anything at all — the network included —
        so a client must not treat it as acting on one known server."""
        assert _hints(tools[name])["open_world"] is True

    @pytest.mark.parametrize(
        "name",
        [
            "read_cell", "read_notebook", "list_notebooks", "list_files", "list_kernels",
            "insert_cell", "delete_cell", "move_cell", "overwrite_cell_source",
            "edit_cell_source", "clear_cell_output", "use_notebook", "unuse_notebook",
        ],
    )
    def test_everything_else_acts_on_one_known_server(self, tools, name):
        assert _hints(tools[name])["open_world"] is False


class TestTheOrderIsDeterministic:
    def test_the_tools_come_back_sorted(self, tools):
        """Registration order is deterministic for one build and nothing
        more: it moves when a tool is added, when one is moved in the file,
        and — now that extensions register after configuration rather than
        at import — depending on when an extension got its turn. A client
        that caches the list would see a change that is not one."""
        names = list(tools)
        assert names == sorted(names)

    def test_two_listings_are_the_same_listing(self, tools):
        first = [tool.name for tool in asyncio.run(mcp.list_tools())]
        second = [tool.name for tool in asyncio.run(mcp.list_tools())]
        assert first == second

    def test_a_tool_registered_late_still_lands_in_order(self):
        """An extension's tool must not end up appended at the end merely
        because its extension registered last."""
        names = [tool.name for tool in asyncio.run(mcp.list_tools())]
        assert names == sorted(names)
