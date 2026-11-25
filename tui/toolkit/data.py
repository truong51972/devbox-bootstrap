"""Local data transforms. Input/output is not persisted by Devbox."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote


def json_format(value, _cwd):
    return json.dumps(json.loads(value), ensure_ascii=False, indent=2, allow_nan=False)


def json_minify(value, _cwd):
    return json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def b64encode(value, _cwd):
    return base64.b64encode(value.encode()).decode()


def b64decode(value, _cwd):
    return base64.b64decode(value.strip(), validate=True).decode("utf-8")


def url_encode(value, _cwd):
    return quote(value, safe="")


def url_decode(value, _cwd):
    return unquote(value, errors="strict")


def uuid4(_value, _cwd):
    return str(uuid.uuid4())


def uuid7(_value, _cwd):
    # RFC 9562: 48-bit Unix milliseconds, version 7, variant 10, 74 random bits.
    millis = (time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    bits = (millis << 80) | (7 << 76) | (secrets.randbits(12) << 64) | (2 << 62) | secrets.randbits(62)
    return str(uuid.UUID(int=bits))


def token(_value, _cwd):
    return secrets.token_urlsafe(32)


def jwt(value, _cwd):
    parts = value.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Expected a three-part compact JWT.")
    def decode(part):
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return json.dumps({"warning": "Decoded only; signature and claims are NOT verified.",
                       "header": decode(parts[0]), "payload": decode(parts[1])}, indent=2, ensure_ascii=False)


def timestamp(value, _cwd):
    if value:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    return str(int(time.time()))


def checksum(value, cwd):
    if not value:
        raise ValueError("Enter a file path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    if not path.is_file():
        raise ValueError("Select a regular file.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
