# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The worker opens a Datalayer document room with a notebook-scoped token.

Spacer hands back a short-lived, document-scoped token beside the session id.
The worker fetches the session id with the caller's own token, then opens the
websocket with the scoped one — so the token the room holds is a key to this
one document and no other. When Spacer offers no scoped token (an older image),
the caller token is used, so the behaviour degrades rather than breaks.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from jupyter_mcp_server.notebook_manager import _datalayer_room_url_with_scoped_token


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _capture(monkeypatch, payload):
    seen: dict = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        return _Resp(payload)

    monkeypatch.setattr("jupyter_mcp_server.notebook_manager.requests.get", fake_get)
    return seen


def test_the_scoped_token_opens_the_room(monkeypatch):
    seen = _capture(
        monkeypatch,
        {"success": True, "sessionId": "sess-1", "token": "scoped-cap"},
    )
    url = _datalayer_room_url_with_scoped_token(
        server_url="https://spacer.example",
        user_token="user-jwt",
        room_id="json:notebook:file-1",
        headers=None,
        timeout=10,
    )

    # The session id was fetched from the documents endpoint as the user.
    assert seen["url"] == "https://spacer.example/api/spacer/v1/documents/json:notebook:file-1"
    assert seen["headers"]["Authorization"] == "Bearer user-jwt"

    parsed = urlparse(url)
    assert parsed.scheme == "wss"
    assert parsed.path == "/api/spacer/v1/documents/ws/json:notebook:file-1"
    query = parse_qs(parsed.query)
    assert query["sessionId"] == ["sess-1"]
    # The websocket carries the scoped capability, not the user token.
    assert query["token"] == ["scoped-cap"]


def test_it_falls_back_to_the_caller_token_when_spacer_offers_none(monkeypatch):
    _capture(monkeypatch, {"success": True, "sessionId": "sess-2"})
    url = _datalayer_room_url_with_scoped_token(
        server_url="http://spacer.example",
        user_token="user-jwt",
        room_id="room-2",
        headers=None,
        timeout=10,
    )
    query = parse_qs(urlparse(url).query)
    # No scoped token offered — the caller token keeps the room reachable.
    assert query["token"] == ["user-jwt"]
    assert urlparse(url).scheme == "ws"


def test_a_failed_session_fetch_raises(monkeypatch):
    _capture(monkeypatch, {"success": False, "message": "no document"})
    with pytest.raises(ValueError, match="session_id"):
        _datalayer_room_url_with_scoped_token(
            server_url="https://spacer.example",
            user_token="user-jwt",
            room_id="gone",
            headers=None,
            timeout=10,
        )


def test_caller_headers_are_carried(monkeypatch):
    # Cookie/XSRF headers a cookie-protected server needs are preserved, and the
    # caller's token becomes the Authorization when they supplied none.
    seen = _capture(monkeypatch, {"success": True, "sessionId": "s", "token": "cap"})
    _datalayer_room_url_with_scoped_token(
        server_url="https://spacer.example",
        user_token="user-jwt",
        room_id="r",
        headers={"Cookie": "session=abc"},
        timeout=10,
    )
    assert seen["headers"]["Cookie"] == "session=abc"
    assert seen["headers"]["Authorization"] == "Bearer user-jwt"


def test_an_authorization_the_caller_set_is_not_clobbered(monkeypatch):
    # The caller's own Authorization wins over the token: a server reached with
    # a scheme of its own (Basic, a proxy's bearer) must keep it, or a session
    # that authenticates by header is silently downgraded to the raw token.
    seen = _capture(monkeypatch, {"success": True, "sessionId": "s", "token": "cap"})
    _datalayer_room_url_with_scoped_token(
        server_url="https://spacer.example",
        user_token="user-jwt",
        room_id="r",
        headers={"Cookie": "session=abc", "Authorization": "Basic existing"},
        timeout=10,
    )
    assert seen["headers"]["Authorization"] == "Basic existing"
    assert seen["headers"]["Cookie"] == "session=abc"
