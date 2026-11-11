"""Extracting a downloaded package with sd_webui_all_in_one's archive manager.

A portable package's archive wraps one directory
(``<key>-<author>-<platform>-<date>/``, holding ``core/`` and ``python/``), whose
name is not the archive's. So the archive is extracted into a staging directory
beside the target, and its single top directory is moved into place; an
archive without one becomes ``<folder>/<archive name without extension>``.

The extraction runs in a child process (``extract_child``), as the original
downloader ran 7-Zip: ``extract_archive`` cannot be interrupted (py7zr reports
progress from a thread of its own), so cancelling kills the child.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

ARCHIVE_SUFFIXES = (
    ".tar.gz",
    ".tar.xz",
    ".tar.bz2",
    ".tar.zst",
    ".tar.lzma",
    ".tgz",
    ".txz",
    ".tbz2",
    ".tlz",
    ".tar",
    ".zip",
    ".7z",
    ".rar",
)

Progress = Callable[[int, "int | None"], None]

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class ExtractCancelled(Exception):
    """The job was cancelled while its archive was being extracted."""


class ExtractError(Exception):
    """The archive could not be extracted or put in place."""


def archive_stem(filename: str) -> str:
    """The archive's name without its archive suffix (``a.tar.gz`` → ``a``)."""
    lowered = filename.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def extract_package(
    archive: Path, folder: Path, on_progress: Progress, cancel: threading.Event
) -> Path:
    """Extracts ``archive`` into ``folder`` and answers the directory the package is in.

    Args:
        archive: The downloaded archive.
        folder: The folder it was downloaded to, where the package goes.
        on_progress: Called with the bytes extracted so far and the total, when known.
        cancel: Set to stop the extraction.

    Returns:
        The package's directory.

    Raises:
        ExtractCancelled: ``cancel`` was set.
        ExtractError: The archive did not extract, or the package's directory already exists.
    """
    stem = archive_stem(archive.name)
    staging = folder / f".{stem}.extracting"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        _extract_in_child(archive, staging, on_progress, cancel)
        return _place(staging, folder, stem)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _extract_in_child(
    archive: Path, staging: Path, on_progress: Progress, cancel: threading.Event
) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_BACKEND_DIR), *filter(None, env.get("PYTHONPATH", "").split(os.pathsep))]
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "portable_downloader.extract_child", str(archive), str(staging)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    errors: list[str] = []
    reader = threading.Thread(
        target=_read_reports, args=(process, on_progress, errors), name="extract", daemon=True
    )
    reader.start()
    while process.poll() is None:
        if cancel.wait(0.2):
            process.kill()
            process.wait()
            reader.join()
            raise ExtractCancelled()
    reader.join()
    if process.returncode != 0:
        raise ExtractError(errors[-1] if errors else f"extraction exited with {process.returncode}")


def _read_reports(
    process: subprocess.Popen[bytes], on_progress: Progress, errors: list[str]
) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if not isinstance(report, dict):
            continue
        if isinstance(report.get("error"), str):
            errors.append(report["error"])
        elif isinstance(report.get("done"), int):
            total = report.get("total")
            on_progress(report["done"], total if isinstance(total, int) else None)


def _place(staging: Path, folder: Path, stem: str) -> Path:
    entries = list(staging.iterdir())
    wrapped = len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink()
    source = entries[0] if wrapped else staging
    target = folder / (entries[0].name if wrapped else stem)
    if target.exists():
        raise ExtractError(f"{target} already exists; move or delete it, then try again")
    source.rename(target)
    return target
