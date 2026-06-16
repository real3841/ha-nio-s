"""Parse a sniffed NIO service-order (battery swap) request capture.

Unlike the vehicle status API (icar.nio.com GET), the swap/order API uses
gateway-front-external.nio.com with POST + query params. The captured URL is
stored and replayed verbatim, same philosophy as capture.py for vehicle status.
"""

from __future__ import annotations

import hashlib
import re

try:
    from . import const
except ImportError:  # pragma: no cover - HA-free tests
    import const  # type: ignore[no-redefine]

_METHOD_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD)\s+", re.IGNORECASE)


def parse_change_capture(raw: str) -> tuple[str, str]:
    """Split a pasted service-order request into ``(url, method)``.

    Accepts a full URL (``https://gateway-front-external.nio.com/...?...``) or
    a proxy request line (``POST https://...?... HTTP/2``). The URL is returned
    verbatim (encoded=True safe) for replay. Method defaults to POST when not
    present in the capture.

    Raises ``ValueError`` if the text doesn't look like a service-order request.
    """
    text = (raw or "").strip().strip("\"'")
    if not text:
        raise ValueError("empty capture")

    method = const.DEFAULT_CHANGE_METHOD
    method_match = _METHOD_RE.match(text)
    if method_match:
        method = method_match.group(1).upper()
        text = text[method_match.end() :].strip()

    # Drop trailing HTTP version / header junk after the URL.
    text = re.split(r"\s", text, maxsplit=1)[0].strip()
    if text.startswith("/"):
        text = f"https://{const.CHANGE_API_HOST}{text}"

    if const.CHANGE_API_PATH_MARKER not in text:
        raise ValueError(
            f"no {const.CHANGE_API_PATH_MARKER} segment found — "
            "paste the getTabOrder request URL from Postman"
        )
    if "?" not in text:
        raise ValueError("no query string (nothing after '?')")

    return text, method


def change_unique_id(url: str) -> str:
    """Stable unique_id for a change config entry from the captured URL."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"change_{digest}"
