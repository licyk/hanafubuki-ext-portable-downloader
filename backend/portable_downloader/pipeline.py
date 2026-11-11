"""One job's work: download the archive, extract it, register what it holds."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .archive import ExtractCancelled, extract_package, needs_sevenzip
from .jobs import Job, JobCancelled, JobQueue
from .sevenzip import SevenZip, SevenZipError

# How often the download's progress reaches the job (the library reports every chunk).
_PROGRESS_INTERVAL = 0.2


@dataclass(frozen=True)
class Registration:
    """What ``instances.scan`` answered: the instances attached and the warnings."""

    instances: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


Register = Callable[[Path], Registration]


class JobRunner:
    """Runs a job through its steps; the queue calls it on its worker thread."""

    def __init__(self, register: Register, sevenzip: SevenZip) -> None:
        """Builds the runner.

        Args:
            register: Registers the extracted package with the application (``instances.scan``).
            sevenzip: Finds or downloads 7-Zip, for a ``.7z`` where py7zr is not installed.
        """
        self._register = register
        self._sevenzip = sevenzip

    def __call__(self, job: Job, queue: JobQueue) -> None:
        """Runs ``job``.

        Raises:
            JobCancelled: It was cancelled.
        """
        folder = Path(job.folder)
        folder.mkdir(parents=True, exist_ok=True)
        # Before the package's download, which a missing 7-Zip would waste.
        sevenzip = self._find_sevenzip(job)
        archive = self._download(job, queue, folder)
        if not job.auto_extract:
            queue.update(job, state="done")
            return
        queue.update(job, state="extracting")
        try:
            package = extract_package(
                archive,
                folder,
                lambda done, total: queue.update(job, extracted=done, extract_total=total),
                job.cancel,
                sevenzip,
            )
        except ExtractCancelled as error:
            raise JobCancelled() from error
        if job.delete_archive:
            archive.unlink(missing_ok=True)
        queue.update(job, state="registering", package_path=str(package))
        registration = self._register(package)
        queue.update(
            job, state="done", instances=registration.instances, warnings=registration.warnings
        )

    def _find_sevenzip(self, job: Job) -> Path | None:
        if not (job.auto_extract and needs_sevenzip(job.filename)):
            return None
        try:
            return self._sevenzip.executable(job.cancel)
        except SevenZipError:
            if job.cancel.is_set():
                raise JobCancelled() from None
            raise

    def _download(self, job: Job, queue: JobQueue, folder: Path) -> Path:
        from sd_webui_all_in_one.downloader import DownloadToolType, download_file

        last = 0.0

        def on_progress(event: Any) -> None:
            nonlocal last
            now = time.monotonic()
            total = event.total_size or None
            if now - last < _PROGRESS_INTERVAL and event.completed_size != total:
                return
            last = now
            queue.update(
                job, downloaded=event.completed_size, total=total, speed=event.average_speed
            )

        try:
            path = download_file(
                url=[job.url],
                path=folder,
                save_name=job.filename,
                tool=cast("DownloadToolType", job.tool),
                progress=False,
                existing_file_policy="resume",
                progress_callback=on_progress,
                cancel_event=job.cancel,
            )
        except Exception:
            if job.cancel.is_set():
                raise JobCancelled() from None
            raise
        if job.cancel.is_set():
            raise JobCancelled()
        size = path.stat().st_size
        queue.update(job, archive_path=str(path), downloaded=size, total=size, speed=0.0)
        return path
