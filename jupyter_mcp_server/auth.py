# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Authentication utilities for Jupyter server password login."""

from typing import Optional

import requests

from jupyter_mcp_server.log import logger


_BODY_PREVIEW_CHARS = 200


def _truncate(text: str) -> str:
    """Trim a response body for inclusion in an error message."""
    if not text:
        return "<empty>"
    snippet = text.strip().replace("\n", " ")
    if len(snippet) <= _BODY_PREVIEW_CHARS:
        return repr(snippet)
    return repr(snippet[:_BODY_PREVIEW_CHARS] + "…")


class JupyterPasswordAuth:
    """Handles password-based authentication with a Jupyter server.

    Performs POST /login with the password, then keeps a `requests.Session`
    alive so cookies refreshed by the server during subsequent requests are
    visible via `live_headers()`. Use `inject_into_session()` to copy cookies
    into another `Session` (e.g. the one inside `JupyterServerClient`).
    """

    def __init__(self, server_url: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.password = password
        self._session: Optional[requests.Session] = None
        self._xsrf_token: Optional[str] = None
        self._authenticated = False

    def _do_request(self, method: str, url: str, stage: str, timeout: float, **kwargs):
        """Wrap session.request with consistent error translation per stage."""
        assert self._session is not None  # set by login() before calling
        try:
            return self._session.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.Timeout as error:
            raise RuntimeError(
                f"Timed out during {stage} ({method} {url}) after {timeout}s: {error}"
            ) from error
        except requests.exceptions.ConnectionError as error:
            raise RuntimeError(
                f"Connection error during {stage} ({method} {url}): {error}"
            ) from error

    def login(self, timeout: float = 10.0) -> None:
        """Perform the /login POST to obtain session cookies.

        Args:
            timeout: Per-request timeout in seconds (applied to GET /login,
                POST /login, and the verification GET /api/status).

        Raises:
            RuntimeError: If login fails (connection, timeout, bad credentials,
                server error, or missing XSRF cookie).
        """
        # Build the session and only retain it on success — on failure, close
        # it so we don't leak connections.
        session = requests.Session()
        self._session = session
        try:
            # GET /login to obtain the initial _xsrf cookie. Disable redirects
            # so we don't silently follow to a different origin (e.g. JupyterHub).
            self._do_request(
                "GET", f"{self.server_url}/login",
                stage="initial XSRF fetch", timeout=timeout,
                allow_redirects=False,
            )
            xsrf = session.cookies.get("_xsrf", "")

            # POST /login with password (and _xsrf if present).
            post_data = {"password": self.password}
            if xsrf:
                post_data["_xsrf"] = xsrf
            response = self._do_request(
                "POST", f"{self.server_url}/login",
                stage="login POST", timeout=timeout,
                data=post_data, allow_redirects=False,
            )
            if response.status_code >= 500:
                raise RuntimeError(
                    f"Jupyter server returned {response.status_code} on /login — "
                    f"the server is failing, not an auth problem. "
                    f"Body: {_truncate(response.text)}"
                )
            if response.status_code not in (200, 302):
                raise RuntimeError(
                    f"Password login failed with status {response.status_code}. "
                    f"Check that the Jupyter server is configured for password auth. "
                    f"Body: {_truncate(response.text)}"
                )

            # Verify we actually got authenticated by testing the API.
            # Distinguish 401/403 (bad credentials) from other failure modes.
            verify = self._do_request(
                "GET", f"{self.server_url}/api/status",
                stage="session verification", timeout=timeout,
            )
            if verify.status_code in (401, 403):
                raise RuntimeError(
                    f"Password login did not produce a valid session "
                    f"(GET /api/status returned {verify.status_code}). "
                    f"The password may be incorrect. Body: {_truncate(verify.text)}"
                )
            if verify.status_code >= 500:
                raise RuntimeError(
                    f"Jupyter server returned {verify.status_code} on /api/status — "
                    f"the server is failing, not an auth problem. "
                    f"Body: {_truncate(verify.text)}"
                )
            if verify.status_code != 200:
                raise RuntimeError(
                    f"Unexpected status {verify.status_code} from /api/status "
                    f"while verifying the login session. Body: {_truncate(verify.text)}"
                )

            self._xsrf_token = session.cookies.get("_xsrf", "")
            if not self._xsrf_token:
                raise RuntimeError(
                    "Login succeeded but no _xsrf cookie was set. "
                    "XSRF-protected POST requests would deterministically fail; "
                    "refusing to proceed. Check the Jupyter server's XSRF configuration."
                )
            self._authenticated = True
            logger.info(f"Password authentication successful for {self.server_url}")
        except BaseException:
            session.close()
            self._session = None
            raise

    def close(self) -> None:
        """Close the underlying session. Safe to call multiple times."""
        if self._session is not None:
            self._session.close()
            self._session = None
        self._authenticated = False

    def _live_cookies(self) -> dict[str, str]:
        """Snapshot the current cookie jar (post-login, may include refreshes)."""
        if self._session is None:
            return {}
        return dict(self._session.cookies)

    @property
    def cookie_header(self) -> str:
        """Cookie header value built from the current (live) cookie jar."""
        return "; ".join(f"{name}={value}" for name, value in self._live_cookies().items())

    def get_headers(self) -> dict[str, str]:
        """Return headers dict with Cookie and X-XSRFToken for injection.

        Reads the live cookie jar so a refreshed `_xsrf` is picked up.
        Returns an empty dict if `login()` has not been called or has failed.
        """
        if not self._authenticated:
            return {}
        cookies = self._live_cookies()
        if not cookies:
            return {}
        headers = {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}
        xsrf = cookies.get("_xsrf", "")
        if xsrf:
            headers["X-XSRFToken"] = xsrf
        return headers

    def inject_into_session(self, session: requests.Session) -> None:
        """Copy current cookies into another session.

        Deliberately does NOT set `X-XSRFToken` as a default header — if the
        server ever rotates the `_xsrf` cookie, a frozen header value would go
        stale. Callers that need the XSRF token per-request must read it from
        the live cookie jar (see `ServerContext.runtime_auth_headers`) or call
        `get_headers()` on this auth.
        """
        if not self._authenticated:
            return
        for name, value in self._live_cookies().items():
            session.cookies.set(name, value)
