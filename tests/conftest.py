"""Fixtures shared by the suites; the helpers themselves are in ``support``."""

from __future__ import annotations

import importlib.util
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


@pytest.fixture
def no_py7zr(monkeypatch: pytest.MonkeyPatch) -> None:
    """py7zr is not installed, as on Python 3.15 (the development environment has it)."""
    find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args: None if name == "py7zr" else find_spec(name, *args),
    )
