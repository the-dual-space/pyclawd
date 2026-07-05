"""Version-string parsing shared across the CLI, doctor, and changelog.

Three modules independently parsed dotted version strings — ``cli`` and ``doctor``
each had an identical ``major.minor`` parser, and ``changelog`` a full-tuple one. They
live here now so version handling has one home.
"""

from __future__ import annotations


def major_minor(v: str) -> tuple[int, int] | None:
    """Parse a ``major.minor`` pair from a version string, or ``None`` if unparseable.

    Args:
        v: A version string (e.g. ``"0.1.0"``); trailing components are ignored.

    Returns:
        The ``(major, minor)`` pair, or ``None`` when the first two dotted components
        are not both integers.
    """
    parts = v.strip().split(".")
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def version_tuple(token: str) -> tuple[int, ...] | None:
    """Parse a dotted version token into an int tuple, or ``None`` if not numeric.

    Non-numeric tokens (e.g. ``"Unreleased"``) return ``None`` and are treated by the
    caller as newer than any released version.

    Args:
        token: A dotted version token (e.g. ``"1.10.3"``).

    Returns:
        The component tuple (e.g. ``(1, 10, 3)``), or ``None`` when any component is
        not an integer.
    """
    try:
        return tuple(int(x) for x in token.strip().split("."))
    except ValueError:
        return None
