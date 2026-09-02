# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""How much this server tells a client, and who decides.

A client sets a floor with `logging/setLevel` and gets everything at or above
it. Without the method served it was refused `-32601`, so a client had no way
to turn the volume down — and the alternative to turning it down is turning
the connection off.

`logging-set-level` left the conformance baseline because of this. Verified
the only way that means anything: by removing the handler and watching the
specification's own suite fail.

Launch the tests:
```
$ pytest tests/test_client_logging.py -v
```
"""

from __future__ import annotations

import pytest

from jupyter_mcp_server import client_logging


class _Session:
    def __init__(self, explode: bool = False) -> None:
        self.sent: list[tuple[str, object, str | None]] = []
        self._explode = explode

    async def send_log_message(self, level, data, logger=None) -> None:
        if self._explode:
            raise RuntimeError("the connection is gone")
        self.sent.append((level, data, logger))


class TestTheFloor:
    def test_a_session_gets_info_before_it_asks(self):
        """`debug` would send every client a stream it did not ask for and
        mostly cannot use; `warning` would hide the progress notes a long
        cell sends, which are what somebody watching a ten-minute execution
        actually wants."""
        assert client_logging.level_of(_Session()) == "info"

    def test_setting_a_level_is_remembered(self):
        session = _Session()
        assert client_logging.set_level(session, "warning") is True
        assert client_logging.level_of(session) == "warning"

    def test_each_session_has_its_own(self):
        """Two agents of the same user share this worker. One debugging a
        notebook and one running a pipeline want different amounts, and a
        single global level would have the quiet one shouting or the loud one
        silent."""
        loud, quiet = _Session(), _Session()
        client_logging.set_level(loud, "debug")
        client_logging.set_level(quiet, "error")
        assert client_logging.level_of(loud) == "debug"
        assert client_logging.level_of(quiet) == "error"

    def test_an_unknown_level_is_neither_stored_nor_raised(self):
        """Refusing would refuse a client for asking about a level a later
        specification added. Storing it would silently mute the session,
        because nothing compares greater than a name with no position."""
        session = _Session()
        client_logging.set_level(session, "warning")
        assert client_logging.set_level(session, "chatty") is False
        assert client_logging.level_of(session) == "warning"

    def test_a_session_that_goes_away_takes_its_level_with_it(self):
        import gc

        session = _Session()
        client_logging.set_level(session, "error")
        held = client_logging.level_of(session)
        del session
        gc.collect()
        assert held == "error"


class TestWhatClearsIt:
    def test_the_same_level_clears_its_own_floor(self):
        session = _Session()
        client_logging.set_level(session, "warning")
        assert client_logging.should_send(session, "warning") is True

    def test_something_more_severe_clears_it(self):
        session = _Session()
        client_logging.set_level(session, "warning")
        assert client_logging.should_send(session, "error") is True

    def test_something_less_severe_does_not(self):
        session = _Session()
        client_logging.set_level(session, "warning")
        assert client_logging.should_send(session, "info") is False

    def test_the_order_is_the_specification_s(self):
        """A floor is only meaningful against a sequence, and getting the
        sequence wrong inverts every comparison silently."""
        assert client_logging.LEVELS.index("debug") < client_logging.LEVELS.index("info")
        assert client_logging.LEVELS.index("info") < client_logging.LEVELS.index("warning")
        assert client_logging.LEVELS.index("warning") < client_logging.LEVELS.index("error")
        assert client_logging.LEVELS.index("error") < client_logging.LEVELS.index("emergency")

    def test_an_unknown_level_is_sent_rather_than_dropped(self):
        """The failure modes are not symmetric: sending something nobody
        wanted is noise, and dropping something somebody needed is an outage
        they cannot see."""
        session = _Session()
        client_logging.set_level(session, "emergency")
        assert client_logging.should_send(session, "from-the-future") is True


@pytest.mark.asyncio
class TestSending:
    async def test_a_message_above_the_floor_goes(self):
        session = _Session()
        client_logging.set_level(session, "info")
        assert await client_logging.log_to_client(session, "warning", "careful") is True
        assert session.sent == [("warning", "careful", None)]

    async def test_a_message_below_the_floor_does_not(self):
        session = _Session()
        client_logging.set_level(session, "error")
        assert await client_logging.log_to_client(session, "info", "fyi") is False
        assert session.sent == []

    async def test_the_source_is_carried_when_given(self):
        session = _Session()
        await client_logging.log_to_client(session, "info", "x", source="cells")
        assert session.sent[0][2] == "cells"

    async def test_a_broken_connection_never_fails_the_work(self):
        """A note *about* work, sent from a path that is doing the work.
        Failing a cell because the note about the cell would not go out
        trades the work for the story about the work."""
        assert await client_logging.log_to_client(_Session(explode=True), "error", "x") is False

    async def test_no_session_is_not_an_error(self):
        assert await client_logging.log_to_client(None, "error", "x") is False


class TestTheMethodIsServed:
    def test_the_handler_is_registered(self):
        """A client that cannot turn the volume down turns the connection off
        instead."""
        from jupyter_mcp_server.server import mcp

        assert "logging/setLevel" in mcp._lowlevel_server._request_handlers

    def test_it_is_not_in_the_conformance_baseline_any_more(self):
        """It came off because it started passing, which is the only reason
        an entry should ever come off."""
        import pathlib

        baseline = pathlib.Path(__file__).resolve().parent / "conformance-baseline.yaml"
        if not baseline.exists():
            pytest.skip("no baseline here")
        assert "logging-set-level" not in baseline.read_text()
