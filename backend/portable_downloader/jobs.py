"""The download queue: one job at a time, in the order they were added, like the original."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ACTIVE = ("downloading", "extracting", "registering")
FINISHED = ("done", "failed", "cancelled")


class JobCancelled(Exception):
    """The job's cancellation was requested and it stopped."""


@dataclass
class Job:
    """One package to download, extract and register; mutated only through ``JobQueue.update``."""

    key: str
    display_name: str
    source: str
    channel: str
    filename: str
    version: str | None
    build_date: str | None
    url: str
    folder: str
    tool: str
    auto_extract: bool
    delete_archive: bool
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    downloaded: int = 0
    total: int | None = None
    speed: float = 0.0
    extracted: int = 0
    extract_total: int | None = None
    archive_path: str | None = None
    package_path: str | None = None
    instances: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_json(self) -> dict[str, Any]:
        """The job as the page reads it."""
        return {
            "id": self.id,
            "key": self.key,
            "displayName": self.display_name,
            "source": self.source,
            "channel": self.channel,
            "filename": self.filename,
            "version": self.version,
            "buildDate": self.build_date,
            "folder": self.folder,
            "autoExtract": self.auto_extract,
            "deleteArchive": self.delete_archive,
            "state": self.state,
            "cancelling": self.cancel.is_set() and self.state not in FINISHED,
            "downloaded": self.downloaded,
            "total": self.total,
            "speed": round(self.speed),
            "extracted": self.extracted,
            "extractTotal": self.extract_total,
            "archivePath": self.archive_path,
            "packagePath": self.package_path,
            "instances": list(self.instances),
            "warnings": list(self.warnings),
            "error": self.error,
        }


Runner = Callable[[Job, "JobQueue"], None]


class JobQueue:
    """Runs jobs one at a time on a worker thread, telling ``on_change`` after every change."""

    def __init__(self, runner: Runner, on_change: Callable[[], None]) -> None:
        """Builds the queue; its worker starts with the first job.

        Args:
            runner: Runs one job, reporting through ``update``; raises ``JobCancelled``
                when it stopped for its cancellation, anything else when it failed.
            on_change: Called after each change, from any thread; must return quickly.
        """
        self._runner = runner
        self._on_change = on_change
        self._jobs: list[Job] = []
        self._condition = threading.Condition()
        self._worker: threading.Thread | None = None
        self._stopped = False

    def snapshot(self) -> list[dict[str, Any]]:
        """Every job as the page reads it, oldest first."""
        with self._condition:
            return [job.to_json() for job in self._jobs]

    def get(self, job_id: str) -> Job | None:
        """The job of ``job_id``, if there is one."""
        with self._condition:
            return next((job for job in self._jobs if job.id == job_id), None)

    def enqueue(self, job: Job) -> dict[str, Any]:
        """Adds ``job`` at the end of the queue.

        Returns:
            The job as the page reads it.
        """
        with self._condition:
            if self._stopped:
                raise RuntimeError("the downloader is stopping")
            self._jobs.append(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="downloads", daemon=True)
                self._worker.start()
            self._condition.notify_all()
            snapshot = job.to_json()
        self._on_change()
        return snapshot

    def update(self, job: Job, **changes: Any) -> None:
        """Changes ``job``'s fields (the runner's progress) and tells ``on_change``."""
        with self._condition:
            for name, value in changes.items():
                setattr(job, name, value)
        self._on_change()

    def cancel(self, job_id: str) -> bool:
        """Cancels a job: a queued one at once, a running one once its step notices.

        Returns:
            Whether there was such a job that had not finished.
        """
        with self._condition:
            job = next((job for job in self._jobs if job.id == job_id), None)
            if job is None or job.state in FINISHED:
                return False
            job.cancel.set()
            if job.state == "queued":
                job.state = "cancelled"
        self._on_change()
        return True

    def remove(self, job_id: str) -> bool:
        """Removes a finished job from the list.

        Returns:
            Whether a finished job of that id was removed.
        """
        with self._condition:
            job = next((job for job in self._jobs if job.id == job_id), None)
            if job is None or job.state not in FINISHED:
                return False
            self._jobs.remove(job)
        self._on_change()
        return True

    def stop(self) -> None:
        """Cancels every job that has not finished and stops the worker; does not wait for it."""
        with self._condition:
            self._stopped = True
            for job in self._jobs:
                if job.state not in FINISHED:
                    job.cancel.set()
                    if job.state == "queued":
                        job.state = "cancelled"
            self._condition.notify_all()

    def _next(self) -> Job | None:
        with self._condition:
            while True:
                if self._stopped:
                    return None
                job = next((job for job in self._jobs if job.state == "queued"), None)
                if job is not None:
                    job.state = "downloading"
                    return job
                self._condition.wait()

    def _work(self) -> None:
        while (job := self._next()) is not None:
            self._on_change()
            try:
                self._runner(job, self)
            except JobCancelled:
                self.update(job, state="cancelled", speed=0.0)
            except Exception as error:  # noqa: BLE001 - a job's failure is reported, never raised
                if job.cancel.is_set():
                    self.update(job, state="cancelled", speed=0.0)
                else:
                    self.update(job, state="failed", speed=0.0, error=_reason(error))


def _reason(error: Exception) -> str:
    text = str(error).strip()
    return text or type(error).__name__
