"""SSRF guard — https only, public addresses only, every redirect re-checked."""

from __future__ import annotations

import httpx
import pytest

from app.shared.ssrf import FetchError, UnsafeURLError, is_public_ip, safe_get, validate_url

PUBLIC = "93.184.216.34"


def resolver_for(mapping: dict[str, list[str]]):
    async def _resolve(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise OSError("NXDOMAIN")
        return mapping[host]

    return _resolve


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",  # noqa: S104
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_non_public_ips(ip: str) -> None:
    assert not is_public_ip(ip)


def test_public_ip() -> None:
    assert is_public_ip(PUBLIC)
    assert is_public_ip("2606:4700:4700::1111")


@pytest.mark.parametrize(
    "url,msg",
    [
        ("http://example.com/x", "https"),
        ("ftp://example.com/x", "https"),
        ("https://user:pw@example.com/x", "credentials"),
        ("https://localhost/x", "public"),
        ("https://metadata.internal/x", "public"),
        ("https://127.0.0.1/x", "public"),
        ("https://[::1]/x", "public"),
        ("https://169.254.169.254/latest/meta-data", "public"),
    ],
)
async def test_validate_rejects(url: str, msg: str) -> None:
    with pytest.raises(UnsafeURLError, match=msg):
        await validate_url(url, resolver_for({}))


async def test_dns_resolving_to_private_is_rejected() -> None:
    resolver = resolver_for({"evil.example": [PUBLIC, "10.0.0.5"]})
    with pytest.raises(UnsafeURLError, match="public"):
        await validate_url("https://evil.example/skill.md", resolver)


async def test_unresolvable_host_rejected() -> None:
    with pytest.raises(UnsafeURLError, match="resolve"):
        await validate_url("https://nope.example/x", resolver_for({}))


async def test_public_host_allowed() -> None:
    assert await validate_url("https://good.example/x", resolver_for({"good.example": [PUBLIC]}))


async def test_redirect_to_private_host_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.example":
            return httpx.Response(302, headers={"location": "https://inner.example/secret"})
        return httpx.Response(200, text="should never be fetched")

    resolver = resolver_for({"good.example": [PUBLIC], "inner.example": ["192.168.0.10"]})
    with pytest.raises(UnsafeURLError):
        await safe_get(
            "https://good.example/start",
            max_bytes=1000,
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        )


async def test_redirect_to_http_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "http://good.example/plain"})

    with pytest.raises(UnsafeURLError, match="https"):
        await safe_get(
            "https://good.example/start",
            max_bytes=1000,
            resolver=resolver_for({"good.example": [PUBLIC]}),
            transport=httpx.MockTransport(handler),
        )


async def test_follows_safe_redirect_and_caps_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=b"x" * 50)

    resolver = resolver_for({"good.example": [PUBLIC]})
    result = await safe_get(
        "https://good.example/start",
        max_bytes=100,
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    assert result.url == "https://good.example/final" and result.content == b"x" * 50

    with pytest.raises(FetchError, match="larger than"):
        await safe_get(
            "https://good.example/start",
            max_bytes=10,
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        )


async def test_too_many_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchError, match="Too many redirects"):
        await safe_get(
            "https://good.example/loop",
            max_bytes=10,
            max_redirects=3,
            resolver=resolver_for({"good.example": [PUBLIC]}),
            transport=httpx.MockTransport(handler),
        )


async def test_http_error_status() -> None:
    with pytest.raises(FetchError, match="HTTP 404"):
        await safe_get(
            "https://good.example/missing",
            max_bytes=10,
            resolver=resolver_for({"good.example": [PUBLIC]}),
            transport=httpx.MockTransport(lambda r: httpx.Response(404)),
        )
