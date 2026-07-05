"""Tiny JSON-file persistence shared by the dashboard's on-disk stores.

The registry and the comment store both persist plain JSON via the standard library
(no dependency added to pyclawd's core), and both had the same read-with-fallback /
write-with-mkdir pair copied out. That pair lives here now — :func:`read_json` and
:func:`write_json` — so both stores share one implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")


def read_json(path: Path, default: _T) -> _T:
    """Return the parsed JSON at *path*, or *default* if it is absent or unreadable.

    Args:
        path: The JSON file to read.
        default: The value to return when the file does not exist, cannot be read, or
            does not contain valid JSON (also used when the file holds ``null``/empty).

    Returns:
        The parsed JSON value, or *default* on any absence/parse error.
    """
    if not path.exists():
        return default
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    return loaded or default


def write_json(path: Path, data: object, *, sort_keys: bool = False) -> None:
    """Write *data* to *path* as indented JSON, creating parent directories as needed.

    Args:
        path: The destination file (its parent directory is created if missing).
        data: Any JSON-serialisable value.
        sort_keys: Whether to sort object keys (stable diffs for config-like files).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=sort_keys))
