"""The web reader may only reach the public internet (SSRF defence)."""

import httpx
import pytest

from agent_system.adapters.outbound.web import reader, url_guard
from agent_system.adapters.outbound.web.url_guard import BlockedURL, GuardedTransport, is_public_address, public_addresses

pytestmark = pytest.mark.unit

PUBLIC = "93.184.216.34"
DNS = {
    "public.test": [PUBLIC],
    "redirector.test": [PUBLIC],
    "internal.test": ["10.0.0.5"],                 # a public-looking name pointing inside
    "mixed.test": [PUBLIC, "10.0.0.5"],            # one good record, one bad
    "metadata.test": ["169.254.169.254"],
    "agent-neo4j": ["10.0.171.20"],                # a cluster service name
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    async def resolve(host: str, port: int) -> list[str]:
        if host not in DNS:
            raise OSError("no such host")
        return DNS[host]

    monkeypatch.setattr(url_guard, "_resolve", resolve)


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),            # loopback
        ("10.0.0.5", False),             # private
        ("172.16.4.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),      # link-local: the cloud metadata service
        ("100.64.0.1", False),           # carrier-grade NAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),            # multicast
        ("::1", False),
        ("fd00::1", False),              # IPv6 private
        ("fe80::1", False),              # IPv6 link-local
        ("::ffff:10.0.0.5", False),      # IPv4 hidden inside IPv6
        ("64:ff9b::a00:5", False),       # NAT64 to 10.0.0.5
        ("not-an-address", False),
    ],
)
def test_is_public_address(address, public):
    assert is_public_address(address) is public


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost.test/",                      # does not resolve
        "http://169.254.169.254/metadata/instance",    # literal metadata address
        "http://metadata.test/",                       # a name for it
        "http://internal.test/admin",
        "http://mixed.test/",                          # any bad record refuses the name
        "http://agent-neo4j/",
        "http://[::1]/",
        "http://[::ffff:10.0.0.5]/",
        "http://2130706433/",                          # 127.0.0.1 written as one number
        "http://public.test:8000/",                    # unusual port
        "http://public.test:22/",
        "ftp://public.test/file",
        "file:///etc/passwd",
        "http://user:pass@public.test/",
    ],
)
async def test_refused_urls(url):
    with pytest.raises(BlockedURL):
        await public_addresses(url)


async def test_public_url_is_allowed():
    url, addresses = await public_addresses("https://public.test/page?q=1")
    assert url.host == "public.test" and addresses == [PUBLIC]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=GuardedTransport(httpx.MockTransport(handler)), follow_redirects=True)


async def test_connection_is_pinned_to_the_validated_address():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(host=request.url.host, host_header=request.headers["host"], sni=request.extensions.get("sni_hostname"))
        return httpx.Response(200, text="ok")

    async with _client(handler) as client:
        response = await client.get("https://public.test/page")
    assert response.text == "ok"
    # Connected to the address we checked; the name is only a header and the TLS server name.
    assert seen == {"host": PUBLIC, "host_header": "public.test", "sni": "public.test"}


@pytest.mark.parametrize(
    "location",
    ["http://10.0.0.5/secret", "http://internal.test/secret", "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/"],
)
async def test_a_redirect_to_an_internal_address_is_refused(location):
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        reached.append(request.headers["host"])
        return httpx.Response(302, headers={"location": location})

    async with _client(handler) as client:
        with pytest.raises(BlockedURL):
            await client.get("http://redirector.test/")
    assert reached == ["redirector.test"]  # the internal hop was never sent


async def test_a_redirect_to_another_public_site_is_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "redirector.test":
            return httpx.Response(302, headers={"location": "https://public.test/final"})
        return httpx.Response(200, text="final page")

    async with _client(handler) as client:
        assert (await client.get("http://redirector.test/")).text == "final page"


async def test_read_page_reports_an_internal_url_as_disallowed_without_fetching(monkeypatch):
    sent = []
    monkeypatch.setattr(
        reader, "guarded_client",
        lambda **kw: httpx.AsyncClient(transport=GuardedTransport(httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))), **kw),
    )
    reader._robots.clear()
    for url in ("http://169.254.169.254/metadata/identity/oauth2/token", "http://agent-neo4j/", "http://internal.test/"):
        result = await reader.read_page(url)
        assert (result.status, result.text) == ("disallowed", "")
        assert "public" in result.detail
    assert sent == []  # not even robots.txt was requested


async def test_headless_browser_requests_are_checked_too():
    class Request:
        def __init__(self, url, kind="document"):
            self.url, self.resource_type = url, kind

    class Route:
        def __init__(self, url, kind="document"):
            self.request, self.outcome = Request(url, kind), None

        async def abort(self, reason=None):
            self.outcome = "abort"

        async def continue_(self):
            self.outcome = "continue"

    async def decide(url, kind="document"):
        route = Route(url, kind)
        await reader._filter_browser_request(route)
        return route.outcome

    assert await decide("https://public.test/app.js", "script") == "continue"
    assert await decide("data:text/plain,hi") == "continue"
    assert await decide("https://public.test/pic.png", "image") == "abort"        # not needed for text
    # A public page that scripts a request inward:
    assert await decide("http://169.254.169.254/latest/meta-data/", "fetch") == "abort"
    assert await decide("http://internal.test/api", "xhr") == "abort"
    assert await decide("http://localhost.test:8000/", "fetch") == "abort"
