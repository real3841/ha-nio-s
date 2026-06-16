"""Async client for the NIO service-order / battery-swap API.

Replays a sniffed getTabOrder request (POST + query params, or GET) from the
NIO app / Postman. Distinct from the vehicle status client in api.py.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from yarl import URL

from .const import DEFAULT_CHANGE_METHOD

_LOGGER = logging.getLogger(__name__)


class NioChangeApiError(Exception):
    """Generic service-order API failure."""


class NioChangeAuthError(NioChangeApiError):
    """Token or cookie rejected — needs re-auth."""


class NioChangeApiClient:
    """Read-only client for gateway-front-external.nio.com service orders."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        token: str,
        url: str,
        method: str = DEFAULT_CHANGE_METHOD,
        cookie: str | None = None,
    ) -> None:
        self._session = session
        self._url = URL(url, encoded=True)
        self._method = method.upper()
        self._headers: dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Authorization": f"Bearer {token}",
        }
        if self._method not in ("GET", "HEAD"):
            self._headers.setdefault("Content-Type", "application/json")
        if cookie:
            self._headers["Cookie"] = cookie

    async def async_get_orders(self) -> dict[str, Any]:
        """Fetch service orders; return the full JSON payload."""
        try:
            kwargs: dict[str, Any] = {"headers": self._headers}
            if self._method in ("GET", "HEAD"):
                request = self._session.get
            else:
                request = self._session.post
                # Postman POST: empty body (Content-Length: 0).
                kwargs["data"] = b""
            async with request(self._url, **kwargs) as resp:
                status = resp.status
                try:
                    payload = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    payload = None
        except aiohttp.ClientError as err:
            raise NioChangeApiError(f"Connection error: {err}") from err

        if not isinstance(payload, dict):
            raise NioChangeApiError("Malformed response: not a JSON object")

        code = payload.get("resultCode") or payload.get("result_code")
        if code in ("0000", "success"):
            return payload

        desc = (
            payload.get("resultDesc")
            or payload.get("result_desc")
            or payload.get("debug_msg")
            or payload.get("resultMsg")
            or str(code)
        )
        codestr = str(code or "").lower()
        if status in (401, 403) or "auth" in codestr or "token" in codestr:
            raise NioChangeAuthError(
                f"Service-order API rejected credentials (HTTP {status}, {desc})"
            )
        raise NioChangeApiError(
            f"Service-order API error (HTTP {status}, resultCode={code}, {desc})"
        )
