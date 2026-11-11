"""The portable package list (``portable_list.json``): fetching it, caching it, reading it.

Its shape is ``{update_time, resources: {<source>: {<platform>: {<key>: {display_name,
description, stable: [entry], nightly: [entry]}}}}}``, each entry ``{filename, url, path,
version, build_date, channel, signature, platform, extension}``. It is read
tolerantly: an entry or a package that does not read is left out, the rest stay.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gpu import GpuInfo, compatibility, package_vendor

LIST_URLS = (
    "https://licyk.github.io/resources/portable_list.json",
    "https://github.com/licyk/resources/raw/gh-pages/portable_list.json",
    "https://gitlab.com/licyk/resources/-/raw/gh-pages/portable_list.json",
    "https://gitee.com/licyk/resources/raw/gh-pages/portable_list.json",
)
CACHE_NAME = "portable_list.json"
CHANNELS = ("stable", "nightly")

Fetch = Callable[[str, float], bytes]


class CatalogError(Exception):
    """The list could not be fetched or does not read."""


@dataclass(frozen=True)
class Entry:
    """One downloadable archive of a package."""

    filename: str
    url: str
    channel: str
    version: str | None
    build_date: str | None
    size: int | None

    def to_json(self) -> dict[str, Any]:
        """The entry as the page reads it; its URL stays in the backend."""
        return {
            "filename": self.filename,
            "version": self.version,
            "buildDate": self.build_date,
            "size": self.size,
        }


@dataclass(frozen=True)
class Package:
    """A package of one source and platform, its entries newest first."""

    key: str
    display_name: str
    description: str
    stable: tuple[Entry, ...]
    nightly: tuple[Entry, ...]

    def entries(self, channel: str) -> tuple[Entry, ...]:
        """The entries of ``channel`` (``stable`` or ``nightly``)."""
        return self.stable if channel == "stable" else self.nightly

    def to_json(self, gpu: GpuInfo) -> dict[str, Any]:
        """The package as the page reads it, with its GPU and whether it suits this machine."""
        vendor = package_vendor(self.key)
        return {
            "key": self.key,
            "displayName": self.display_name,
            "description": self.description,
            "gpu": vendor,
            "compatibility": compatibility(vendor, gpu),
            "stable": [entry.to_json() for entry in self.stable],
            "nightly": [entry.to_json() for entry in self.nightly],
        }


@dataclass(frozen=True)
class Catalog:
    """The list as read: its update time and the packages by source and platform."""

    update_time: str
    packages: Mapping[str, Mapping[str, tuple[Package, ...]]]

    def for_platform(self, source: str, platform: str) -> tuple[Package, ...]:
        """The packages of ``source`` built for ``platform``."""
        return self.packages.get(source, {}).get(platform, ())

    def find(
        self, source: str, platform: str, key: str, channel: str, filename: str
    ) -> tuple[Package, Entry] | None:
        """The package and entry a download names, if the list has it."""
        for package in self.for_platform(source, platform):
            if package.key != key:
                continue
            for entry in package.entries(channel):
                if entry.filename == filename:
                    return package, entry
        return None


def parse_catalog(document: Any) -> Catalog:
    """Reads a fetched or cached list.

    Args:
        document: The decoded JSON.

    Returns:
        The catalog.

    Raises:
        CatalogError: It has no ``resources`` object.
    """
    if not isinstance(document, dict) or not isinstance(document.get("resources"), dict):
        raise CatalogError("the package list has no `resources` object")
    packages: dict[str, dict[str, tuple[Package, ...]]] = {}
    for source, platforms in document["resources"].items():
        if not isinstance(platforms, dict):
            continue
        packages[source] = {
            platform: _packages(keys)
            for platform, keys in platforms.items()
            if isinstance(keys, dict)
        }
    update_time = document.get("update_time")
    return Catalog(update_time if isinstance(update_time, str) else "", packages)


def fetch_document(urls: Sequence[str], timeout: float, fetch: Fetch | None = None) -> Any:
    """Fetches the list from the first mirror that answers with a list.

    Args:
        urls: The mirrors, in order.
        timeout: Each attempt's timeout, in seconds.
        fetch: Reads a URL's body (urllib by default).

    Returns:
        The decoded document.

    Raises:
        CatalogError: No mirror answered with a list; says why for each.
    """
    fetch = fetch or _urlopen
    failures = []
    for url in urls:
        try:
            document = json.loads(fetch(url, timeout))
            parse_catalog(document)
            return document
        except Exception as error:  # noqa: BLE001 - every failure means "try the next mirror"
            failures.append(f"{url}: {error}")
    raise CatalogError("; ".join(failures) or "no mirror to fetch the package list from")


class CatalogCache:
    """The last list fetched, kept in the extension's data directory for offline use."""

    def __init__(self, data_dir: Path) -> None:
        """Builds the cache.

        Args:
            data_dir: The extension's data directory.
        """
        self.path = data_dir / CACHE_NAME

    def load(self) -> Catalog | None:
        """The cached list, or none when there is none that reads."""
        try:
            return parse_catalog(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, CatalogError):
            return None

    def save(self, document: Any) -> None:
        """Replaces the cached list."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".partial")
        partial.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        os.replace(partial, self.path)


def _packages(keys: Mapping[str, Any]) -> tuple[Package, ...]:
    packages = []
    for key, value in keys.items():
        if not isinstance(value, dict):
            continue
        name = value.get("display_name")
        description = value.get("description")
        packages.append(
            Package(
                key=key,
                display_name=name if isinstance(name, str) and name else key,
                description=description if isinstance(description, str) else "",
                stable=_entries(value.get("stable"), "stable"),
                nightly=_entries(value.get("nightly"), "nightly"),
            )
        )
    return tuple(sorted(packages, key=lambda package: package.display_name.lower()))


def _entries(raw: Any, channel: str) -> tuple[Entry, ...]:
    if not isinstance(raw, list):
        return ()
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        filename, url = item.get("filename"), item.get("url")
        if not (isinstance(filename, str) and filename and isinstance(url, str) and url):
            continue
        size = item.get("size")
        entries.append(
            Entry(
                filename=filename,
                url=url,
                channel=channel,
                version=_text(item.get("version")),
                build_date=_text(item.get("build_date")),
                size=size if isinstance(size, int) and size > 0 else None,
            )
        )
    return tuple(sorted(entries, key=_newest_first))


def _newest_first(entry: Entry) -> tuple[int, ...]:
    # Nightly builds carry a build date, stable ones a version; either sorts descending.
    if entry.build_date and entry.build_date.isdigit():
        return (-int(entry.build_date),)
    if entry.version:
        return tuple(-int(part) if part.isdigit() else 0 for part in entry.version.split("."))
    return (0,)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _urlopen(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hanafubuki-portable-downloader"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()
