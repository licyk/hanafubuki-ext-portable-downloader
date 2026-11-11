"""The extraction child: ``python -m portable_downloader.extract_child <archive> <target>``.

Runs sd_webui_all_in_one's ``extract_archive`` and writes one JSON object per line
to stdout: ``{"done", "total"}`` as it goes, ``{"error"}`` when it fails. The
library's own output goes to stderr, the extension's log.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

# Progress lines at most five times a second; the last one is always written.
_INTERVAL = 0.2


class _Reports:
    """Writes the reports; py7zr updates progress from a thread of its own."""

    def __init__(self, out: TextIO) -> None:
        self._out = out
        self._lock = threading.Lock()
        self._last = 0.0

    def write(self, report: dict[str, Any], force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last < _INTERVAL:
                return
            self._last = now
            self._out.write(json.dumps(report) + "\n")
            self._out.flush()


class _Bar:
    """Stands in for the library's tqdm bar, which is all its progress goes through."""

    def __init__(self, total: int | None, reports: _Reports) -> None:
        self.total = total
        self.n = 0
        self._reports = reports
        reports.write({"done": 0, "total": total}, force=True)

    def __enter__(self) -> _Bar:
        return self

    def __exit__(self, *exc: object) -> None:
        self._reports.write({"done": self.n, "total": self.total}, force=True)

    def update(self, n: int = 1) -> None:
        self.n += int(n)
        self._reports.write({"done": self.n, "total": self.total})

    def close(self) -> None:
        return None


def main(argv: list[str]) -> int:
    """Extracts ``argv[1]`` into ``argv[2]``."""
    out = sys.stdout
    sys.stdout = sys.stderr
    reports = _Reports(out)
    from sd_webui_all_in_one import archive_manager as library

    archive_manager: Any = library
    # extract_archive takes no callback: its progress goes through the module's private
    # `_progress_bar`. A library without it extracts without progress.
    if hasattr(archive_manager, "_progress_bar"):
        archive_manager._progress_bar = lambda total=None, *_, **__: _Bar(total, reports)
    try:
        archive_manager.extract_archive(Path(argv[1]), Path(argv[2]), progress=True)
    except Exception as error:  # noqa: BLE001 - reported to the parent, which fails the job
        reports.write({"error": str(error) or type(error).__name__}, force=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
