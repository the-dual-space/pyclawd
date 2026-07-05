"""Shared fixtures for the pyclawd test suite.

``_reset_discovery`` isolates each test from config-discovery state. The ``--config``
override and the loaded-project cache in :mod:`pyclawd.discovery` are process-wide, so a
test that sets an override (or loads a project) would otherwise leak into the next one.
This autouse fixture clears both before and after every test. It lived, copy-pasted, in
several test modules before moving here.
"""

from __future__ import annotations

import pytest

from pyclawd import discovery


@pytest.fixture(autouse=True)
def _reset_discovery():
    """Clear the ``--config`` override + load cache around every test (process-wide state)."""
    discovery.set_config_override(None)
    discovery._CACHE.clear()
    yield
    discovery.set_config_override(None)
    discovery._CACHE.clear()
