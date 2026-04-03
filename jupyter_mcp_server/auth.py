# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Authentication utilities for Jupyter server password login."""

from typing import Optional

import requests

from jupyter_mcp_server.log import logger


class JupyterPasswordAuth:
    """Handles password-based authentication with a Jupyter server.

    Performs POST /login with the password, extracts session cookies
    and XSRF token, and provides them as headers for injection into
    both requests-based and websocket-based clients.
    """

    def __init__(self, server_url: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.password = password
        self._cookies: dict[str, str] = {}
        self._xsrf_token: Optional[str] = None
        self._authenticated = False

    def login(self) -> None:
        """Perform the /login POST to obtain session cookies.

        Raises:
            RuntimeError: If login fails.
        """
        session = requests.Session()

        # GET /login to obtain the initial _xsrf cookie
        try:
            session.get(f"{self.server_url}/login")
        except requests.exceptions.ConnectionError as error:
            raise RuntimeError(
                f"Cannot connect to Jupyter server at {self.server_url}: {error}"
            ) from error

        xsrf = session.cookies.get("_xsrf", "")

        # POST /login with password (and _xsrf if present)
        post_data = {"password": self.password}
        if xsrf:
            post_data["_xsrf"] = xsrf

        response = session.post(
            f"{self.server_url}/login",
            data=post_data,
            allow_redirects=False,
        )

        if response.status_code not in (200, 302):
            raise RuntimeError(
                f"Password login failed with status {response.status_code}. "
                "Check that the Jupyter server is configured for password auth."
            )

        # Verify we actually got authenticated by testing the API.
        # This also ensures we have the latest _xsrf cookie from the server.
        verify = session.get(f"{self.server_url}/api/status")
        if verify.status_code == 403:
            raise RuntimeError(
                "Password login did not produce valid session cookies. "
                "The password may be incorrect."
            )

        self._cookies = dict(session.cookies)
        self._xsrf_token = self._cookies.get("_xsrf", "")
        if not self._xsrf_token:
            logger.warning("No _xsrf cookie found after login — XSRF-protected POST requests may fail")
        self._authenticated = True
        logger.info(f"Password authentication successful for {self.server_url}")

    @property
    def cookie_header(self) -> str:
        """Return cookies formatted as a Cookie header value."""
        return "; ".join(f"{name}={value}" for name, value in self._cookies.items())

    def get_headers(self) -> dict[str, str]:
        """Return headers dict with Cookie and X-XSRFToken for injection.

        Suitable for passing to both jupyter_server_client and
        jupyter_kernel_client (via their headers kwargs).
        """
        if not self._authenticated:
            return {}
        headers = {"Cookie": self.cookie_header}
        if self._xsrf_token:
            headers["X-XSRFToken"] = self._xsrf_token
        return headers

    def inject_into_session(self, session: requests.Session) -> None:
        """Inject auth cookies directly into a requests.Session."""
        if not self._authenticated:
            return
        for name, value in self._cookies.items():
            session.cookies.set(name, value)
        if self._xsrf_token:
            session.headers["X-XSRFToken"] = self._xsrf_token
