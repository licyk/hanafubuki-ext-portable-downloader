"""Extracting a downloaded package with sd_webui_all_in_one's archive manager.

A portable package's archive wraps one directory
(``<key>-<author>-<platform>-<date>/``, holding ``core/`` and ``python/``), whose
name is not the archive's. So the archive is extracted into a staging directory
beside the target, and its single top directory is moved into place; an
archive without one becomes ``<folder>/<archive name without extension>``.

The extraction runs in a child process, so that cancelling kills it:
``extract_child``, since ``extract_archive`` cannot be interrupted (py7zr reports
progress from a thread of its own), or, for a ``.7z`` where py7zr is not
installed, 7-Zip itself (``x <archive> -o<staging> -y``, as the original
downloader ran it; see ``sevenzip``).
"""

from __future__ import annotations

import codecs
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

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
# 7-Zip redraws its progress (`-bsp1`: " 45% 12 - core/main.py") over backspaces or
# carriage returns rather than on new lines.
_SEVENZIP_SEPARATORS = re.compile(r"[\b\r\n]+")
_SEVENZIP_PERCENT = re.compile(r"(\d{1,3})%")


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


def needs_sevenzip(filename: str) -> bool:
    """Whether ``filename`` is a ``.7z`` that py7zr, which is not installed, would extract."""
    return filename.lower().endswith(".7z") and importlib.util.find_spec("py7zr") is None


def extract_package(
    archive: Path,
    folder: Path,
    on_progress: Progress,
    cancel: threading.Event,
    sevenzip: Path | None = None,
) -> Path:
    """Extracts ``archive`` into ``folder`` and answers the directory the package is in.

    Args:
        archive: The downloaded archive.
        folder: The folder it was downloaded to, where the package goes.
        on_progress: Called with the bytes (with 7-Zip, the percent) extracted so far and
            the total, when known.
        cancel: Set to stop the extraction.
        sevenzip: The 7-Zip executable that extracts it, instead of ``extract_archive``.

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
        if sevenzip is None:
            _extract_in_child(archive, staging, on_progress, cancel)
        else:
            _extract_with_sevenzip(sevenzip, archive, staging, on_progress, cancel)
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
    errors: list[str] = []
    code = _run(
        [sys.executable, "-m", "portable_downloader.extract_child", str(archive), str(staging)],
        lambda stdout: _read_reports(stdout, on_progress, errors),
        cancel,
        env=env,
    )
    if code != 0:
        raise ExtractError(errors[-1] if errors else f"extraction exited with {code}")


def _extract_with_sevenzip(
    executable: Path,
    archive: Path,
    staging: Path,
    on_progress: Progress,
    cancel: threading.Event,
) -> None:
    messages: deque[str] = deque(maxlen=4)
    code = _run(
        [str(executable), "x", str(archive), f"-o{staging}", "-y", "-bsp1", "-bso0"],
        lambda stdout: _read_sevenzip(stdout, on_progress, messages),
        cancel,
        stderr=subprocess.STDOUT,
    )
    if code != 0:
        detail = "; ".join(messages) or "no message"
        raise ExtractError(f"7-Zip ({executable.name}) exited with {code}: {detail}")
    on_progress(100, 100)


def _run(
    command: Sequence[str],
    read: Callable[[IO[bytes]], None],
    cancel: threading.Event,
    env: dict[str, str] | None = None,
    stderr: int | None = None,
) -> int:
    """Runs ``command`` with ``read`` on its stdout; kills it when ``cancel`` is set."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=stderr,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.stdout is not None
    reader = threading.Thread(target=read, args=(process.stdout,), name="extract", daemon=True)
    reader.start()
    while process.poll() is None:
        if cancel.wait(0.2):
            process.kill()
            process.wait()
            reader.join()
            raise ExtractCancelled()
    reader.join()
    return process.returncode


def _read_reports(stdout: IO[bytes], on_progress: Progress, errors: list[str]) -> None:
    for line in stdout:
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


def _read_sevenzip(stdout: IO[bytes], on_progress: Progress, messages: deque[str]) -> None:
    """Reports 7-Zip's percentages and keeps its last other lines (its errors)."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending, last = "", -1

    def report(text: str) -> bool:
        nonlocal last
        match = _SEVENZIP_PERCENT.match(text.strip())
        if match is not None and int(match.group(1)) != last:
            last = int(match.group(1))
            on_progress(min(100, last), 100)
        return match is not None

    # Read as it comes: the progress has no line ends to wait for, and the last one
    # drawn is reported before it is redrawn.
    while chunk := os.read(stdout.fileno(), 4096):
        *parts, pending = _SEVENZIP_SEPARATORS.split(pending + decoder.decode(chunk))
        for part in parts:
            if not report(part) and part.strip():
                messages.append(part.strip())
        report(pending)
    pending += decoder.decode(b"", final=True)
    if not report(pending) and pending.strip():
        messages.append(pending.strip())


def _place(staging: Path, folder: Path, stem: str) -> Path:
    entries = list(staging.iterdir())
    wrapped = len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink()
    source = entries[0] if wrapped else staging
    target = folder / (entries[0].name if wrapped else stem)
    if target.exists():
        raise ExtractError(f"{target} already exists; move or delete it, then try again")
    source.rename(target)
    return target
