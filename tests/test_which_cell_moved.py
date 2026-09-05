# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The notification says which **cell** moved, not only which notebook.

`resources/updated` naming `notebook://<handle>` tells an agent to read the
whole notebook again. It does not tell it what changed, so an agent watching
one cell of a hundred-cell notebook refetches the hundred. `CELL_RESOURCE`
has existed as a URI template since resources shipped, and nothing published
it.

Two halves have to agree for that to work. A writing tool knows the cell it
resolved, and says so in its result already, for the agent's benefit. The
watcher sees a pycrdt event and has to map it back to the cells that moved.

And a third thing, which is why this is one change rather than two: the two
halves used to announce the *same edit twice*. The tool published on its way
out; the edit then arrived back over the watcher's own connection with no
origin on it, looking like somebody else's, and was announced again. Naming
the cell would have made that two identical cell frames. So the tool's news
is folded into the watcher's debounce instead.

Launch the tests:
```
$ pytest tests/test_which_cell_moved.py -v
```
"""

from __future__ import annotations

import asyncio

import pycrdt
import pytest

from jupyter_mcp_server import notifications, resources
from jupyter_mcp_server import watchers as module
from jupyter_mcp_server.watchers import NotebookWatchers
from tests.test_notebook_update_notifications import _Bus, _FakeSession, _Server
from tests.test_notebook_watchers import FakeClient
from tests.test_notebook_watchers import FakeManager as PlainManager


class Cells:
    """A notebook's cells array, as the nbmodel client exposes it."""

    def __init__(self, *ids: str) -> None:
        self.ydoc = pycrdt.Doc()
        self.ycells = pycrdt.Array()
        self.ydoc["cells"] = self.ycells
        for one in ids:
            self.ycells.append(
                pycrdt.Map({"id": one, "source": pycrdt.Text(""), "outputs": pycrdt.Array()})
            )
        self.seen: list[set[str]] = []
        self.ycells.observe_deep(self._note)

    def _note(self, events) -> None:
        for event in events:
            self.seen.append(module._ids_of(event, self.ycells))

    def named(self) -> set[str]:
        found: set[str] = set()
        for one in self.seen:
            found |= one
        return found


class FakeNotebookClient:
    """The nbmodel client's shape, with real cells to observe."""

    def __init__(self, *ids: str) -> None:
        self._changes_origin = object()
        self.cells = Cells(*ids)
        self._doc = type(
            "YNotebook", (), {"_ydoc": self.cells.ydoc, "ycells": self.cells.ycells}
        )()

    def edit_source(self, index: int, text: str, *, origin=None) -> None:
        with self.cells.ydoc.transaction(origin=origin):
            self.cells.ycells[index]["source"] = pycrdt.Text(text)

    def insert(self, cell_id: str, *, origin=None) -> None:
        with self.cells.ydoc.transaction(origin=origin):
            self.cells.ycells.append(
                pycrdt.Map({"id": cell_id, "source": pycrdt.Text(""), "outputs": pycrdt.Array()})
            )

    def delete(self, index: int, *, origin=None) -> None:
        with self.cells.ydoc.transaction(origin=origin):
            del self.cells.ycells[index]


class FakeConnection:
    def __init__(self, client) -> None:
        self.client = client
        self.closed = False

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc):
        self.closed = True


class FakeManager:
    def __init__(self, client) -> None:
        self.connection = FakeConnection(client)

    def is_local_notebook(self, name):
        return False

    def get_notebook_connection(self, name):
        return self.connection


@pytest.fixture
def fast(monkeypatch):
    # Not smaller: Windows' clock resolution is about 16 ms, so a debounce of
    # 20 ms is a debounce the loop cannot tell from zero.
    monkeypatch.setattr(module, "DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(module, "MAX_WAIT_SECONDS", 0.2)


async def _settle(seconds=0.3):
    await asyncio.sleep(seconds)


class TestTheCellUri:
    """One spelling of a cell's URI, not two."""

    def test_it_is_the_template_filled_in(self):
        assert notifications.cell_uri("welcome", "abc") == resources.CELL_RESOURCE.format(
            name="welcome", cell_id="abc"
        )

    def test_it_sits_under_the_notebook_it_belongs_to(self):
        """A subscriber that asked for the notebook and one that asked for a
        cell must be able to tell from the URI which is which."""
        assert notifications.cell_uri("welcome", "abc").startswith(
            notifications.notebook_uri("welcome") + "/"
        )


class TestWhichCellsAToolTouched:
    """Read off the result's `_meta`, where the resolver already put it."""

    def _result(self, **meta):
        from jupyter_mcp_server.results import meta_key

        return type("R", (), {"meta": {meta_key(k): v for k, v in meta.items()}})()

    def test_the_one_cell_a_tool_resolved(self):
        assert notifications.changed_cells(self._result(cell_id="abc")) == ("abc",)

    def test_the_several_a_delete_resolved(self):
        assert notifications.changed_cells(self._result(cell_ids=["a", "b"])) == ("a", "b")

    def test_a_cell_named_twice_is_said_once(self):
        """A move resolves a source and a target, and a subscriber told about
        the same cell twice refetches it twice."""
        assert notifications.changed_cells(self._result(cell_id="a", cell_ids=["a", "b"])) == (
            "a",
            "b",
        )

    def test_an_insert_names_no_cell(self):
        """Nothing was subscribed to a cell that did not exist."""
        assert notifications.changed_cells(self._result()) == ()

    def test_a_result_with_no_meta_at_all(self):
        assert notifications.changed_cells(type("R", (), {"meta": None})()) == ()

    def test_something_that_is_not_a_result(self):
        assert notifications.changed_cells("not a result") == ()

    def test_a_blank_id_is_not_an_id(self):
        assert notifications.changed_cells(self._result(cell_ids=["", "b"])) == ("b",)

    def test_a_blank_single_id_is_not_an_id_either(self):
        """`notebook://nb/cells/` names no cell, and a subscriber sent it
        would refetch a URI that reads as an error."""
        assert notifications.changed_cells(self._result(cell_id="")) == ()


@pytest.mark.asyncio
class TestPublishingNamesTheCell:
    async def test_the_cell_gets_its_own_frame(self):
        bus = _Bus()
        told = await notifications.publish_notebook_updated(_Server(bus), "nb", ["abc"])
        assert told is True
        assert "notebook://nb/cells/abc" in [event.uri for event in bus.published]

    async def test_the_notebook_frame_is_still_sent(self):
        """As well as, never instead of. A client subscribed to the notebook
        asked about the notebook, and a deletion is a change whose cell id
        nobody can read afterwards."""
        bus = _Bus()
        await notifications.publish_notebook_updated(_Server(bus), "nb", ["abc"])
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/abc",
        ]

    async def test_no_cells_is_the_notebook_alone(self):
        bus = _Bus()
        await notifications.publish_notebook_updated(_Server(bus), "nb")
        assert [event.uri for event in bus.published] == ["notebook://nb"]

    async def test_the_same_cell_twice_is_one_frame(self):
        bus = _Bus()
        await notifications.publish_notebook_updated(_Server(bus), "nb", ["a", "a", "b"])
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/a",
            "notebook://nb/cells/b",
        ]

    async def test_a_uri_that_cannot_be_published_does_not_take_the_rest(self):
        """One frame failing must not silence the others, and must not make a
        publish that did reach somebody answer that nobody was told. The
        caller counts that answer, and `False` there reads as "nothing is
        listening"."""

        class Choosy:
            def __init__(self) -> None:
                self.published: list = []

            async def publish(self, event) -> None:
                if str(event.uri).endswith("/cells/first"):
                    raise RuntimeError("that stream is gone")
                self.published.append(event)

        bus = Choosy()
        told = await notifications.publish_notebook_updated(
            _Server(bus), "nb", ["first", "second"]
        )
        assert told is True, "somebody was told, and the answer said nobody was"
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/second",
        ]

    async def test_a_subscriber_to_one_cell_hears_about_that_cell(self):
        heard: list[str] = []

        class Session(_FakeSession):
            async def send_resource_updated(self, uri):
                heard.append(uri)

        session = Session()
        notifications.legacy_subscribe(session, "notebook://nb/cells/abc")
        try:
            await notifications.publish_notebook_updated(_Server(None), "nb", ["abc"])
        finally:
            notifications.legacy_unsubscribe(session, "notebook://nb/cells/abc")
        assert heard == ["notebook://nb/cells/abc"]

    async def test_a_subscriber_to_one_cell_hears_nothing_about_another(self):
        heard: list[str] = []

        class Session(_FakeSession):
            async def send_resource_updated(self, uri):
                heard.append(uri)

        session = Session()
        notifications.legacy_subscribe(session, "notebook://nb/cells/abc")
        try:
            await notifications.publish_notebook_updated(_Server(None), "nb", ["other"])
        finally:
            notifications.legacy_unsubscribe(session, "notebook://nb/cells/abc")
        assert heard == []


class TestWhichCellsAnEventNames:
    """Mapping a pycrdt event back to the cells that moved."""

    def test_a_change_inside_a_cell_names_it(self):
        client = FakeNotebookClient("one", "two")
        client.edit_source(1, "print(1)")
        assert client.cells.named() == {"two"}

    def test_an_output_appended_names_the_cell(self):
        client = FakeNotebookClient("one")
        with client.cells.ydoc.transaction():
            client.cells.ycells[0]["outputs"].append(pycrdt.Map({"output_type": "stream"}))
        assert client.cells.named() == {"one"}

    def test_an_inserted_cell_names_itself(self):
        client = FakeNotebookClient("one")
        client.cells.seen.clear()
        client.insert("two")
        assert client.cells.named() == {"two"}

    def test_a_deleted_cell_names_nobody(self):
        """Its id went with it. The notebook frame is what covers a deletion,
        which is why the notebook frame is never replaced by cell frames."""
        client = FakeNotebookClient("one", "two")
        client.cells.seen.clear()
        client.delete(0)
        assert client.cells.named() == set()


@pytest.mark.asyncio
class TestTheWatcherSaysWhichCell:
    async def test_somebody_elses_edit_names_the_cell_they_edited(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeNotebookClient("one", "two")
        assert watchers.watch("nb", FakeManager(client)) is True
        await _settle(0.1)
        client.edit_source(1, "print(1)", origin="jupyterlab-user")
        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/two",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_a_notebook_with_no_readable_cells_still_announces(self, fast):
        """The deep observation is an improvement on the notebook frame, not
        a replacement for it: a client that exposes no cells array is watched
        exactly as before."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeClient()
        watchers.watch("nb", PlainManager(client))
        await _settle(0.1)
        client.edit(origin="somebody")
        await _settle()
        assert [event.uri for event in bus.published] == ["notebook://nb"]
        watchers.stop_all()
        await _settle(0.05)


@pytest.mark.asyncio
class TestFoldingTheToolsOwnNews:
    async def test_an_unwatched_notebook_is_not_folded(self, fast):
        """Which is what makes the caller publish it itself."""
        watchers = NotebookWatchers()
        assert watchers.fold("nb", ["abc"]) is False

    async def test_a_watched_one_takes_it_and_announces_it(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        await _settle(0.1)
        assert watchers.fold("nb", ["one"]) is True
        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_one_edit_seen_twice_is_one_notification(self, fast):
        """The tool folds its news in, and the same edit then arrives over
        the watcher's connection carrying no origin. Two sightings, one
        frame — which is the whole reason the fold exists."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeNotebookClient("one")
        watchers.watch("nb", FakeManager(client))
        await _settle(0.1)
        watchers.fold("nb", ["one"])
        client.edit_source(0, "print(1)")  # the same edit, arriving from the wire
        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_a_watch_on_another_loop_does_not_take_it(self, fast):
        """The watchers outlive the loop they were started on — one object
        per process, and the next call may arrive on a different one. Arming
        a timer on a closed loop raises, and it would raise inside a writing
        tool's result wrapper: the news about an edit taking the edit down
        with it. Refusing sends the caller back to publishing for itself."""
        watchers = NotebookWatchers()
        watchers.serve(_Server(_Bus()))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        await _settle(0.1)
        watch = watchers._watching["nb"]
        assert watchers.fold("nb", ["one"]) is True, "the live loop should be taken"

        gone = asyncio.new_event_loop()
        gone.close()
        watch.loop = gone
        assert watchers.fold("nb", ["one"]) is False

        watch.loop = asyncio.new_event_loop()
        try:
            assert watchers.fold("nb", ["one"]) is False, "a different live loop is not this one"
        finally:
            watch.loop.close()

    async def test_a_watch_that_has_not_connected_yet_does_not_take_it(self, fast):
        """Its loop is set when the connection opens. Taking the news before
        then would arm nothing and tell nobody, which is worse than the
        caller publishing it."""
        watchers = NotebookWatchers()
        watchers.serve(_Server(_Bus()))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        assert watchers.fold("nb", ["one"]) is False
        watchers.stop_all()
        await _settle(0.05)


@pytest.mark.asyncio
class TestTheDebounceHasACeiling:
    async def test_continuous_editing_is_still_announced(self, fast):
        """A debounce with no ceiling is starvation waiting for a fast enough
        typist: every keystroke pushes the timer back, and a subscriber hears
        nothing until the typing stops."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeNotebookClient("one")
        watchers.watch("nb", FakeManager(client))
        await _settle(0.1)
        for index in range(60):
            client.edit_source(0, f"print({index})", origin="typing")
            await asyncio.sleep(0.01)
        assert len(bus.published) >= 2, "the ceiling never fired"
        watchers.stop_all()
        await _settle(0.05)

    async def test_a_later_arming_takes_over_from_one_that_has_fired(self, fast):
        """A timer fires and hands the announcement to a task, which runs a
        turn later; a change arriving in between re-arms. Without the
        generation both announce, and the debounce that exists to make one
        frame makes two.

        A counter rather than a look at the pending timer's deadline: asyncio
        fires a timer when the loop is within one clock resolution of it, so
        on a coarse clock a timer fires with its own deadline still in the
        future — and reading that as "a later timer is armed" is a
        notification that never arrives."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        await _settle(0.1)
        watch = watchers._watching["nb"]

        watchers.fold("nb", ["one"])
        superseded = watch.armed
        watchers.fold("nb", ["one"])
        await watchers._announce("nb", superseded)
        assert bus.published == [], "an announcement from an arming already taken over"

        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ], "and the arming that took over still announces"
        watchers.stop_all()
        await _settle(0.1)

    async def test_a_timer_that_fires_early_still_announces(self, fast):
        """asyncio runs a timer once the loop's time is within one clock
        resolution of its deadline. On Windows that resolution is about 16 ms,
        so a 50 ms debounce fires with its own deadline still in the future —
        and an announcement that declined on "the deadline has not passed" was
        an announcement that never arrived at all. Two Windows jobs failed on
        exactly this, on a Linux-green suite."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        await _settle(0.1)
        watch = watchers._watching["nb"]

        watchers.fold("nb", ["one"])
        assert watch.pending.when() > watch.loop.time(), "the deadline is still ahead"
        await watchers._announce("nb", watch.armed)
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_one_burst_s_cells_are_not_the_next_one_s(self, fast):
        """Otherwise a subscriber is told to refetch a cell that has not
        changed since it last did — every burst carrying every cell the
        notebook has ever had."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeNotebookClient("one", "two")
        watchers.watch("nb", FakeManager(client))
        await _settle(0.1)
        client.edit_source(0, "print(1)", origin="typing")
        await _settle()
        client.edit_source(1, "print(2)", origin="typing")
        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
            "notebook://nb",
            "notebook://nb/cells/two",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_a_quiet_notebook_is_announced_once(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeNotebookClient("one")
        watchers.watch("nb", FakeManager(client))
        await _settle(0.1)
        client.edit_source(0, "print(1)", origin="typing")
        await _settle(0.3)
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]
        watchers.stop_all()
        await _settle(0.05)


@pytest.mark.asyncio
class TestTheWrapperHandsItToTheWatcher:
    """The decorator around every writing tool, run rather than read.

    The tests next door assert on the *source* of `results.structured`, which
    says the call is written and not that it happens. These two run a
    decorated tool and watch where its news goes.
    """

    def _tool(self):
        from jupyter_mcp_server.results import add_meta, structured

        @structured("cell.edit")
        async def edit_a_cell(notebook_name: str = "nb"):
            add_meta(cell_id="one")
            return "edited"

        return edit_a_cell

    def _stubs(self, monkeypatch, watchers):
        from jupyter_mcp_server import server as server_module
        from jupyter_mcp_server import watchers as watchers_module

        monkeypatch.setattr(watchers_module, "watchers", watchers)
        monkeypatch.setattr(
            server_module.notebook_manager, "get_current_notebook", lambda: "nb", raising=False
        )

    async def test_a_watched_notebook_s_edit_is_folded_rather_than_published(
        self, monkeypatch, fast
    ):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        watchers.watch("nb", FakeManager(FakeNotebookClient("one")))
        await _settle(0.1)
        self._stubs(monkeypatch, watchers)

        await self._tool()(notebook_name="nb")
        assert bus.published == [], "published straight out; the watcher will announce it again"
        await _settle()
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]
        watchers.stop_all()
        await _settle(0.05)

    async def test_an_unwatched_one_is_published_at_once_and_names_the_cell(
        self, monkeypatch, fast
    ):
        """Nothing is watching, so nothing else will say it. Waiting for a
        debounce that will never fire is how a subscriber hears nothing."""
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        self._stubs(monkeypatch, watchers)
        from jupyter_mcp_server import server as server_module

        monkeypatch.setattr(server_module, "mcp", _Server(bus), raising=False)

        await self._tool()(notebook_name="nb")
        assert [event.uri for event in bus.published] == [
            "notebook://nb",
            "notebook://nb/cells/one",
        ]


@pytest.mark.asyncio
class TestTheNewsNeverTakesTheEditWithIt:
    """The edit is done and the answer is in hand when the news goes out.

    An agent told its edit failed when it did not makes the edit again — so
    an announcement that raises must cost the announcement and nothing else.
    This is the failure that reached the integration suite: folding into a
    watcher whose loop had been closed raised out of the wrapper, and every
    writing tool in the run answered `Event loop is closed`.
    """

    async def test_a_failing_announcement_still_answers(self, monkeypatch):
        from jupyter_mcp_server import results

        async def explode(*_arguments, **_keywords):
            raise RuntimeError("Event loop is closed")

        monkeypatch.setattr(results, "_announce", explode)

        @results.structured("cell.edit")
        async def edit_a_cell(notebook_name: str = "nb"):
            return "edited"

        answer = await edit_a_cell(notebook_name="nb")
        assert answer.structured_content["result"] == "edited"
        assert not answer.is_error
