"""Only let the app fetch URLs that point at the public internet.

The agent reads web pages whose addresses come from search results, from the
model, or from text on other pages. Any of those can be steered by an
attacker ("server-side request forgery"): a URL such as
`http://169.254.169.254/...` (the cloud metadata service, which hands out
credentials), `http://agent-neo4j:7474/` (a service inside the cluster) or
`http://localhost:8000/` would be fetched *from inside our network*, and the
response handed back to the model.

Checking the URL's text is not enough, for three reasons, each handled here:

* **Names resolve to anything.** `evil.example` can have an A record of
  `10.0.0.5`. So the name is resolved and every address it resolves to must
  be public.
* **Redirects.** A public page can answer `302 Location: http://10.0.0.5/`.
  The check runs in the transport, so it runs again on every hop.
* **DNS rebinding.** A name can resolve to a public address when we check and
  a private one a moment later when the HTTP library connects. So the
  connection is *pinned*: we connect to the exact address we validated, and
  send the original name only as the Host header and TLS server name.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any

import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}

# Ranges `is_global` calls public but which translate to arbitrary IPv4
# addresses, internal ones included.
_TRANSLATING = (
    ipaddress.ip_network("64:ff9b::/96"),   # NAT64
    ipaddress.ip_network("2002::/16"),      # 6to4
)


class BlockedURL(httpx.RequestError):
    """The URL is not one this app is willing to fetch."""


def is_public_address(address: str) -> bool:
    """True for addresses on the public internet; False for loopback, private,
    link-local (cloud metadata), CGNAT, multicast, reserved and the like."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop any IPv6 zone
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:  # ::ffff:10.0.0.5 is 10.0.0.5
            return is_public_address(str(ip.ipv4_mapped))
        if any(ip in net for net in _TRANSLATING):
            return False
    return ip.is_global and not ip.is_multicast


async def _resolve(host: str, port: int) -> list[str]:
    """Every address the name resolves to (tests replace this)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def public_addresses(url: str | httpx.URL) -> tuple[httpx.URL, list[str]]:
    """Validate a URL and return it with the public addresses it resolves to.

    Raises BlockedURL when the scheme, port or any resolved address is not
    allowed. *Any*, not all: a name that resolves to one public and one
    private address is refused, since we could be handed either.
    """
    parsed = httpx.URL(str(url))
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme not allowed: {parsed.scheme or 'none'}")
    if parsed.userinfo:
        raise BlockedURL("URLs with embedded credentials are not fetched")
    host = parsed.host
    if not host:
        raise BlockedURL("no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise BlockedURL(f"port not allowed: {port}")

    try:
        ipaddress.ip_address(host)
        addresses = [host]  # already a literal; nothing to resolve
    except ValueError:
        try:
            addresses = await _resolve(host, port)
        except OSError as exc:
            raise BlockedURL(f"could not resolve {host}") from exc
    if not addresses:
        raise BlockedURL(f"could not resolve {host}")
    refused = [a for a in addresses if not is_public_address(a)]
    if refused:
        raise BlockedURL(f"{host} resolves to a non-public address")
    return parsed, addresses


class GuardedTransport(httpx.AsyncBaseTransport):
    """Validates the destination of every request, redirects included, and
    connects to the validated address rather than resolving the name again."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url, addresses = await public_addresses(request.url)
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=addresses[0]),
            headers=request.headers,  # still carries Host: <original name>
            stream=request.stream,
            # TLS: present and verify the certificate for the name, not the IP.
            extensions={**request.extensions, "sni_hostname": url.host},
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


def guarded_client(**kwargs: Any) -> httpx.AsyncClient:
    """An httpx client that can only reach public addresses. Use it for any
    URL that was not written by us: search results, model output, page links."""
    return httpx.AsyncClient(transport=GuardedTransport(), **kwargs)
