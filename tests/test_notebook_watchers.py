# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""A change made by somebody else reaches a subscriber."""

from __future__ import annotations

import asyncio

import pycrdt
import pytest

from jupyter_mcp_server import watchers as module
from jupyter_mcp_server.watchers import NotebookWatchers
from tests.test_notebook_update_notifications import _Bus, _Server


class FakeClient:
    """An nbmodel client's shape: `_doc._ydoc` and `_changes_origin`."""

    def __init__(self):
        self._changes_origin = object()
        ydoc = pycrdt.Doc()
        self._doc = type("YNotebook", (), {"_ydoc": ydoc})()
        self.ymeta = ydoc.get("meta", type=pycrdt.Map)

    def edit(self, *, origin=None):
        """One transaction: ours when `origin` is our origin, somebody's otherwise."""
        with self._doc._ydoc.transaction(origin=origin):
            self.ymeta["n"] = self.ymeta.get("n", 0) + 1


class FakeConnection:
    def __init__(self, client):
        self.client = client
        self.closed = False

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc):
        self.closed = True


class FakeManager:
    def __init__(self, client, local=False):
        self.client = client
        self.local = local
        self.connection = FakeConnection(client)

    def is_local_notebook(self, name):
        return self.local

    def get_notebook_connection(self, name):
        return self.connection


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(module, "DEBOUNCE_SECONDS", 0.02)


async def _settle(seconds=0.1):
    await asyncio.sleep(seconds)


@pytest.mark.asyncio
class TestSomebodyElsesChange:
    async def test_it_is_published_on_the_bus(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeClient()
        assert watchers.watch("nb", FakeManager(client)) is True
        await _settle(0.05)
        client.edit(origin="jupyterlab-user")
        await _settle()
        assert [e.uri for e in bus.published] == ["notebook://nb"]
        watchers.stop_all()
        await _settle(0.02)

    async def test_our_own_edit_is_not_announced_twice(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeClient()
        watchers.watch("nb", FakeManager(client))
        await _settle(0.05)
        client.edit(origin=client._changes_origin)
        await _settle()
        assert bus.published == [], "the tool that made the edit publishes it; the watcher must not"
        watchers.stop_all()

    async def test_a_burst_is_one_notification(self, fast):
        bus = _Bus()
        watchers = NotebookWatchers()
        watchers.serve(_Server(bus))
        client = FakeClient()
        watchers.watch("nb", FakeManager(client))
        await _settle(0.05)
        for _ in range(20):
            client.edit(origin="typing")
        await _settle()
        assert len(bus.published) == 1
        watchers.stop_all()

    async def test_unwatching_closes_the_connection(self, fast):
        watchers = NotebookWatchers()
        watchers.serve(_Server(_Bus()))
        client = FakeClient()
        manager = FakeManager(client)
        watchers.watch("nb", manager)
        await _settle(0.05)
        assert watchers.unwatch("nb") is True
        await _settle(0.05)
        assert manager.connection.closed is True and watchers.watching() == []

    async def test_a_local_notebook_is_not_watched(self, fast):
        watchers = NotebookWatchers()
        assert watchers.watch("nb", FakeManager(FakeClient(), local=True)) is False

    async def test_turned_off_by_the_environment(self, fast, monkeypatch):
        monkeypatch.setenv(module.ENABLED_ENV, "false")
        assert NotebookWatchers().watch("nb", FakeManager(FakeClient())) is False

    def test_outside_a_loop_nothing_starts(self):
        assert NotebookWatchers().watch("nb", FakeManager(FakeClient())) is False


@pytest.mark.asyncio
class TestTheManagerFollows:
    async def test_a_bound_remote_notebook_is_watched_and_an_unbound_one_is_not(self, fast, monkeypatch):
        from jupyter_mcp_server import notebook_manager as nm

        started, stopped = [], []
        monkeypatch.setattr(module.watchers, "watch", lambda name, manager: started.append(name) or True)
        monkeypatch.setattr(module.watchers, "unwatch", lambda name: stopped.append(name) or True)
        manager = nm.NotebookManager()
        manager.add_notebook("nb", code_sandbox={}, server_url="https://jupyter", token="t", path="nb.ipynb")
        manager.add_notebook("local", code_sandbox={}, server_url="local", path="l.ipynb")
        assert started == ["nb"]
        manager.remove_notebook("nb")
        assert stopped == ["nb"]
