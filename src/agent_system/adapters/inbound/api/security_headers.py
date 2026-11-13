"""Response headers that tell the browser how little to trust an API response.

The API only ever returns data (JSON, images, audio, event streams), never a
page. These headers make the browser hold it to that, so that a response
which somehow carries attacker-controlled HTML is still not rendered, framed
or scripted. Each is set only if the route did not set it itself.

HSTS is not set here: the ingress terminates TLS and adds it to every response.
"""

from __future__ import annotations

from typing import Any

_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    # Don't guess content types: JSON stays JSON even if it looks like HTML.
    (b"x-content-type-options", b"nosniff"),
    # No page may put an API response in a frame.
    (b"x-frame-options", b"DENY"),
    # If a browser does render a response, it may load and run nothing.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    # API URLs can contain IDs; don't send them on as a Referer.
    (b"referrer-policy", b"no-referrer"),
)
_NO_STORE = (b"cache-control", b"no-store")


class SecurityHeadersMiddleware:
    """Pure ASGI, so streaming responses are not buffered."""

    def __init__(self, app: Any, path_prefix: str = "/api") -> None:
        self.app = app
        self.path_prefix = path_prefix

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.extend(pair for pair in _HEADERS if pair[0] not in present)
                # JSON here is personal data; keep it out of shared and disk caches.
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if b"cache-control" not in present and content_type.startswith(b"application/json"):
                    headers.append(_NO_STORE)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
