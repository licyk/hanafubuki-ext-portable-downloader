"""The 7-Zip executable that extracts a ``.7z`` where py7zr is not installed.

py7zr's codecs publish no wheels for Python 3.15, the application's default (see
``requirements.txt``), so there a ``.7z`` (every Windows package) is extracted by
7-Zip's command line, as the original downloader extracted it: ``7za``, ``7z`` or
``7zz`` on PATH, or ``7z.exe`` in 7-Zip's Program Files folder on Windows, else the
standalone ``7za.exe`` that downloader uses, downloaded once into the extension's
data directory and checked against its SHA-256. Linux and macOS have no such
download (their packages are ``.tar.gz``): they use 7-Zip from PATH only.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

# The sd-webui-all-in-one downloader's 7za.exe (7-Zip 26.00), at the revision whose
# files the checksums below were taken from, so that an upstream replacement cannot
# make every download fail its check.
_REPOSITORY = (
    "https://modelscope.cn/models/licyks/sd-webui-all-in-one/resolve/"
    "5e06d35d99a5494319e5404c1a5a748625b000cf"
)
_NAMES = ("7za", "7z", "7zz")
_TIMEOUT = 30.0
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Download:
    """Where a platform's 7-Zip executable is downloaded from, and what it must be."""

    url: str
    size: int
    sha256: str
    filename: str = "7za.exe"


DOWNLOADS: Mapping[tuple[str, str], Download] = {
    ("win32", "amd64"): Download(
        f"{_REPOSITORY}/7za/windows/amd64/7za.exe",
        1_334_272,
        "3a30d7761967ad217b90e3e3e02aabd82b13065d7401bf436adefdf75cfea72e",
    ),
    ("win32", "arm64"): Download(
        f"{_REPOSITORY}/7za/windows/aarch64/7za.exe",
        1_206_272,
        "0dee7a8e21f56e117022d657ee88eef5b9ac0584ea10342440a24be7f7a550da",
    ),
}

_MACHINES = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}


class SevenZipError(Exception):
    """No 7-Zip executable could be found or downloaded."""


def platform_download() -> Download | None:
    """This system's download, if 7-Zip has one for it."""
    machine = _MACHINES.get(platform.machine().lower(), "")
    return DOWNLOADS.get((sys.platform, machine))


class SevenZip:
    """Finds 7-Zip, or downloads it once into the extension's data directory."""

    def __init__(
        self,
        directory: Callable[[], Path],
        download: Download | None = None,
        environ: Mapping[str, str] = os.environ,
        windows: bool = sys.platform == "win32",
    ) -> None:
        """Builds the finder.

        Args:
            directory: Where a downloaded executable is kept (read when it is needed).
            download: Where to download it from; ``platform_download()`` by default.
            environ: The environment whose ``PATH`` (and Program Files) is searched.
            windows: Whether to look in 7-Zip's Program Files folder too.
        """
        self._directory = directory
        self._download = download if download is not None else platform_download()
        self._environ = environ
        self._windows = windows

    def unavailable(self) -> str | None:
        """Why no 7-Zip can be had, if none can; looks only, never downloads."""
        if self._download is not None or self.installed() is not None:
            return None
        return (
            "7-Zip is not installed; install it (the 7zip or p7zip-full package, "
            "or `brew install sevenzip` on macOS) so that 7zz, 7z or 7za is on PATH"
        )

    def executable(self, cancel: threading.Event) -> Path:
        """The executable: an installed one, the downloaded one, or one downloaded now.

        Raises:
            SevenZipError: There is none, its download failed, or ``cancel`` was set.
        """
        found = self.installed() or self._cached()
        if found is not None:
            return found
        if self._download is None:
            raise SevenZipError(self.unavailable())
        return _fetch(self._download, self._directory() / self._download.filename, cancel)

    def installed(self) -> Path | None:
        """7-Zip on PATH, or in its Program Files folder on Windows."""
        for name in _NAMES:
            found = shutil.which(name, path=self._environ.get("PATH", ""))
            if found:
                return Path(found)
        if not self._windows:
            return None
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            folder = self._environ.get(variable)
            if folder and (Path(folder) / "7-Zip" / "7z.exe").is_file():
                return Path(folder) / "7-Zip" / "7z.exe"
        return None

    def _cached(self) -> Path | None:
        if self._download is None:
            return None
        path = self._directory() / self._download.filename
        if path.is_file() and _sha256(path) == self._download.sha256:
            return path
        return None


def _fetch(download: Download, target: Path, cancel: threading.Event) -> Path:
    # The partial file keeps the executable's extension: Windows runs `-h` on it.
    partial = target.with_name(f"download-{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        digest, size = _write(download, partial, cancel)
        if size != download.size or digest != download.sha256:
            raise SevenZipError(
                f"the 7-Zip downloaded from {download.url} is not the expected file "
                f"({size} bytes, SHA-256 {digest}); install 7-Zip so that 7z is on PATH"
            )
        partial.chmod(0o755)
        _check_runs(partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _write(download: Download, partial: Path, cancel: threading.Event) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(
        download.url, headers={"User-Agent": "hanafubuki-portable-downloader"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=_TIMEOUT) as response,
            partial.open("wb") as out,
        ):
            while chunk := response.read(_CHUNK):
                if cancel.is_set():
                    raise SevenZipError("cancelled")
                size += len(chunk)
                if size > download.size:
                    break
                digest.update(chunk)
                out.write(chunk)
    except OSError as error:
        raise SevenZipError(f"could not download 7-Zip from {download.url}: {error}") from error
    return digest.hexdigest(), size


def _check_runs(path: Path) -> None:
    try:
        result = subprocess.run(
            [str(path), "-h"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SevenZipError(f"the downloaded 7-Zip does not run: {error}") from error
    if result.returncode != 0 or b"7-Zip" not in result.stdout:
        raise SevenZipError(f"the downloaded 7-Zip does not run (exit {result.returncode})")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
