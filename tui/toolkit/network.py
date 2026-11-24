"""Explicit local network and endpoint inspection."""
from __future__ import annotations

import socket
import ssl
from urllib.parse import urlsplit

from .native import native


def port_number(value):
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError("Enter a port from 1 to 65535.")
    return int(value)


def endpoint(value, default_port=None):
    parsed = urlsplit("//" + value)
    if not parsed.hostname or parsed.hostname.startswith("-") or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Enter host:port (IPv6 in brackets).")
    port = parsed.port if parsed.port is not None else default_port
    if not port or not 1 <= port <= 65535:
        raise ValueError("A valid port is required.")
    return parsed.hostname, port


def ports(_value, _cwd):
    return native(["ss", "-lntup"])


def port(value, _cwd):
    return native(["ss", "-lntup", "sport", "=", ":" + str(port_number(value))])


def addresses(_value, _cwd):
    return native(["ip", "-brief", "address"])


def routes(_value, _cwd):
    return native(["ip", "route"])


def dns(value, _cwd):
    if not value or value.startswith("-") or any(c.isspace() for c in value):
        raise ValueError("Enter a hostname without spaces.")
    return native(["getent", "--", "ahosts", value])


def tcp(value, _cwd):
    host, port = endpoint(value)
    # Bound DNS resolution through a native command as well as the connect.
    resolved = native(["getent", "--", "ahosts", host], timeout=5).splitlines()
    for line in resolved[:8]:
        addr = line.split()[0]
        try:
            with socket.create_connection((addr, port), timeout=2):
                return f"Connected to {host}:{port} ({addr})"
        except OSError:
            continue
    raise ValueError("TCP connection failed.")


def http(value, _cwd):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter an HTTP(S) URL without credentials.")
    # curl has an end-to-end time bound, no redirects, no response body or headers.
    return native(["curl", "--disable", "--silent", "--show-error", "--head",
                   "--max-time", "8", "--output", "/dev/null", "--write-out",
                   "HTTP %{http_code}\\nRemote %{remote_ip}\\nTotal %{time_total}s\\n",
                   "--proto", "=http,https", "--", value], timeout=10)


def tls(value, _cwd):
    host, port = endpoint(value, 443)
    resolved = native(["getent", "--", "ahosts", host], timeout=5).splitlines()
    addr = resolved[0].split()[0]
    with socket.create_connection((addr, port), timeout=4) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as conn:
            cert = conn.getpeercert()
            return f"TLS: {conn.version()}\nSubject: {cert.get('subject')}\nIssuer: {cert.get('issuer')}\nExpires: {cert.get('notAfter')}"
