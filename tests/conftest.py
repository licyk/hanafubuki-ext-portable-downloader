"""Fixtures shared by the suites; the helpers themselves are in ``support``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from support import HttpServer, recorded_list, serve_http


@pytest.fixture
def http_server() -> Iterator[HttpServer]:
    """A local HTTP server whose routes the test sets."""
    with serve_http() as server:
        yield server


@pytest.fixture
def fixture_list() -> dict:
    """The recorded ``portable_list.json``."""
    return recorded_list()
