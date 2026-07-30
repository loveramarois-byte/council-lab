from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
from urllib.parse import urlsplit


INTERNAL_API_HEADER = "X-Council-Internal-Token"
INTERNAL_API_ENV = "COUNCIL_INTERNAL_API_TOKEN"
FRONTEND_PORT_ENV = "COUNCIL_FRONTEND_PORT"
MIN_TOKEN_LENGTH = 32
PUBLIC_API_PATHS = frozenset({"/api/health"})
PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)


def load_trusted_frontend_ports() -> frozenset[int]:
    raw_port = os.environ.get(FRONTEND_PORT_ENV, "").strip() or "3000"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"{FRONTEND_PORT_ENV} must be a valid TCP port.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{FRONTEND_PORT_ENV} must be between 1 and 65535.")
    return frozenset({port})


TRUSTED_FRONTEND_PORTS = load_trusted_frontend_ports()


def load_internal_api_token() -> str:
    configured = os.environ.get(INTERNAL_API_ENV, "").strip()
    if configured:
        if len(configured) < MIN_TOKEN_LENGTH:
            raise RuntimeError(
                f"{INTERNAL_API_ENV} must contain at least {MIN_TOKEN_LENGTH} characters."
            )
        return configured
    # Direct backend starts remain observable through /api/health, but no caller
    # can use the private API unless a launcher shares this ephemeral token.
    return secrets.token_urlsafe(32)


def request_requires_internal_auth(path: str) -> bool:
    return path.startswith("/api/") and path not in PUBLIC_API_PATHS


def token_matches(expected: str, supplied: str | None) -> bool:
    return bool(supplied) and secrets.compare_digest(expected, supplied)


def token_identifier(token: str) -> str:
    """Return a non-secret identifier used to detect stale launcher processes."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def browser_origin_is_trusted(origin: str | None, sec_fetch_site: str | None) -> bool:
    if sec_fetch_site and sec_fetch_site.lower() not in {"same-origin", "none"}:
        return False
    if origin is None:
        return True
    if origin == "null":
        return False

    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.port not in TRUSTED_FRONTEND_PORTS:
            return False
        if parsed.username or parsed.password or parsed.path not in {"", "/"}:
            return False
        if parsed.query or parsed.fragment:
            return False
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost":
            return True
        address = ipaddress.ip_address(hostname)
        if address.is_loopback:
            return True
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            return False
        if isinstance(address, ipaddress.IPv4Address):
            return any(address in network for network in PRIVATE_IPV4_NETWORKS)
        return address.is_private or address.is_link_local
    except (ValueError, TypeError):
        return False
