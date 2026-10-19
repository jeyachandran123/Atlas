"""
SSRF-guarded outbound HTTP fetch.

Used for every user-supplied URL (skill installer today; MCP servers later).

Guarantees:
  - https only, no userinfo in the URL
  - the hostname is resolved and EVERY address must be public
    (private, loopback, link-local, CGNAT, reserved, multicast and
    unspecified ranges are rejected, including IPv4-mapped IPv6)
  - redirects are followed manually and each hop is re-validated
  - after connecting, the actual peer address is checked too (defeats DNS
    rebinding between our resolution and the client's)
  - the body is streamed with a hard byte cap
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]

_REDIRECT_CODES = {301, 302, 303, 307, 308}


class UnsafeURLError(ValueError):
    """The URL (or a redirect/peer) points somewhere we refuse to fetch."""


class FetchError(RuntimeError):
    """The fetch itself failed (status, size, timeout). Message is user-safe."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


async def validate_url(url: str, resolver: Resolver | None = None) -> str:
    """Raise UnsafeURLError unless `url` is https and resolves only to public IPs."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsafeURLError("Only https:// URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        port = parts.port or 443
    except ValueError as e:
        raise UnsafeURLError("URL has an invalid port") from e

    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        if host.lower() in ("localhost", "localhost.localdomain") or host.lower().endswith(
            (".localhost", ".local", ".internal")
        ):
            raise UnsafeURLError("URL host is not a public address") from None
        try:
            addresses = await (resolver or default_resolver)(host, port)
        except OSError as e:
            raise UnsafeURLError(f"Could not resolve host '{host}'") from e
    if not addresses:
        raise UnsafeURLError(f"Could not resolve host '{host}'")
    for addr in addresses:
        if not is_public_ip(addr):
            raise UnsafeURLError("URL host is not a public address")
    return url


def _peer_ip(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    try:
        addr = stream.get_extra_info("server_addr")
    except Exception:  # noqa: BLE001 — transport-specific; absence is fine
        return None
    if isinstance(addr, tuple) and addr:
        return str(addr[0])
    return None


async def safe_get(
    url: str,
    *,
    max_bytes: int,
    headers: dict[str, str] | None = None,
    headers_for: Callable[[str], dict[str, str]] | None = None,
    timeout: float = 15.0,
    max_redirects: int = 5,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """GET `url` with SSRF protection. `headers_for(url)` adds per-host headers
    (e.g. a token only for github.com) and is re-evaluated on every hop."""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout, transport=transport
    ) as client:
        for _hop in range(max_redirects + 1):
            await validate_url(current, resolver)
            req_headers = dict(headers or {})
            if headers_for:
                req_headers.update(headers_for(current))
            try:
                async with client.stream("GET", current, headers=req_headers) as resp:
                    peer = _peer_ip(resp)
                    if peer is not None and not is_public_ip(peer):
                        raise UnsafeURLError("URL host is not a public address")
                    if resp.status_code in _REDIRECT_CODES:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError(f"Redirect without location from {current}")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code >= 400:
                        raise FetchError(f"Fetching {current} failed with HTTP {resp.status_code}")
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError(f"Response is larger than {max_bytes} bytes")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError(f"Response is larger than {max_bytes} bytes")
                        chunks.append(chunk)
                    return FetchResult(
                        url=current,
                        status_code=resp.status_code,
                        content=b"".join(chunks),
                        content_type=resp.headers.get("content-type", ""),
                    )
            except httpx.TimeoutException as e:
                raise FetchError(f"Timed out fetching {current}") from e
            except httpx.HTTPError as e:
                raise FetchError(f"Could not fetch {current}: {type(e).__name__}") from e
    raise FetchError("Too many redirects")
