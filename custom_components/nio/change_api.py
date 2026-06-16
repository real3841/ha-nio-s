"""Async client for the NIO service-order / battery-swap API.

Replays a sniffed getTabOrder request (POST + query params, or GET) from the
NIO app / Postman. Distinct from the vehicle status client in api.py.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from yarl import URL

from .change_data import extract_orders
from .const import DEFAULT_CHANGE_METHOD

_LOGGER = logging.getLogger(__name__)

# Headers commonly present in Postman captures for getTabOrder.
_DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Content-Type": "application/json",
    "Connection": "keep-alive",
    "Origin": "null",
    "Priority": "u=3, i",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}


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
        user_agent: str | None = None,
        mobileinfo: str | None = None,
    ) -> None:
        self._session = session
        self._url = URL(url, encoded=True)
        self._method = method.upper()
        self._headers: dict[str, str] = {
            **_DEFAULT_HEADERS,
            "Authorization": f"Bearer {token}",
        }
        if user_agent:
            self._headers["User-Agent"] = user_agent
        if mobileinfo:
            self._headers["mobileinfo"] = mobileinfo
        if cookie:
            self._headers["Cookie"] = cookie
        self.last_meta: dict[str, Any] = {}

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
            count = len(extract_orders(payload))
            self.last_meta = {
                "http_status": status,
                "method": self._method,
                "order_count": count,
            }
            _LOGGER.debug(
                "NIO change API ok (HTTP %s, resultCode=%s, orders=%s)",
                status,
                code,
                count,
            )
            if count == 0:
                _LOGGER.warning(
                    "NIO change API returned 0 orders (HTTP %s %s, resultCode=%s) — "
                    "check the full Postman URL (all Params in query string) and Bearer token",
                    status,
                    self._method,
                    code,
                )
            return payload

        desc = (
            payload.get("resultDesc")
            or payload.get("result_desc")
            or payload.get("debug_msg")
            or payload.get("resultMsg")
            or str(code)
        )
        codestr = str(code or "").lower()
        self.last_meta = {
            "http_status": status,
            "method": self._method,
            "order_count": 0,
            "api_error": desc,
        }
        if status in (401, 403) or "auth" in codestr or "token" in codestr:
            raise NioChangeAuthError(
                f"Service-order API rejected credentials (HTTP {status}, {desc})"
            )
        raise NioChangeApiError(
            f"Service-order API error (HTTP {status}, resultCode={code}, {desc})"
        )
