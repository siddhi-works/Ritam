"""SSRF guard: only public http(s) hosts, re-checked on every redirect."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class BlockedURL(ValueError):
    pass


ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def resolve(host: str, attempts: int = 3) -> list[str]:
    """Retry DNS briefly; lookups sometimes fail transiently."""
    loop = asyncio.get_running_loop()
    for attempt in range(1, attempts + 1):
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            return sorted({str(info[4][0]) for info in infos})
        except OSError:
            if attempt == attempts:
                raise
            await asyncio.sleep(0.5 * attempt)
    raise RuntimeError("unreachable")


async def check_url(url: str) -> str:
    """Return the normalised URL, or raise BlockedURL."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme not allowed: {parts.scheme or '(none)'}")
    if not parts.hostname:
        raise BlockedURL("URL has no host")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URL are not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURL("invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise BlockedURL(f"port not allowed: {port}")

    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        if host.lower() in {"localhost"} or host.lower().endswith((".local", ".internal")):
            raise BlockedURL(f"host not allowed: {host}")
        try:
            addresses = await resolve(host)
        except OSError as exc:
            raise BlockedURL(f"cannot resolve host: {host}") from exc
    for addr in addresses:
        if not _is_public(ipaddress.ip_address(addr.split("%", 1)[0])):
            raise BlockedURL(f"host resolves to a non-public address: {host}")
    return parts.geturl()
