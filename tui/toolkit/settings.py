"""Small user-owned settings; no command input or output is recorded."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "devbox-bootstrap"


def settings_path():
    return config_dir() / "settings.json"


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("Expected a regular JSON file of at most 256 KiB.")
    return json.loads(path.read_text(encoding="utf-8"))


def load():
    path = settings_path()
    if not path.exists():
        return {}
    try:
        value = read_json(path)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(values, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def favorites():
    from .registry import BY_ID
    value = load().get("favorites", [])
    return [v for v in value if isinstance(v, str) and v in BY_ID] if isinstance(value, list) else []


def toggle_favorite(action_id):
    values = load()
    items = favorites()
    if action_id in items:
        items.remove(action_id)
    else:
        items.append(action_id)
    values["favorites"] = items
    save(values)
    return action_id in items
