"""The queue on its own: order, one job at a time, cancelling and removing."""

from __future__ import annotations

import threading

from portable_downloader.jobs import Job, JobCancelled, JobQueue
from support import wait_for


def _job(name: str) -> Job:
    return Job(
        key=name,
        display_name=name,
        source="modelscope",
        channel="nightly",
        filename=f"{name}.7z",
        version=None,
        build_date="20261109",
        url=f"https://example.invalid/{name}.7z",
        folder="/tmp/packages",
        tool="requests",
        auto_extract=True,
        delete_archive=False,
    )


class Gate:
    """A runner that holds each job until the test releases it, recording the order."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.release: dict[str, threading.Event] = {}
        self.running = 0
        self.most_running = 0
        self.lock = threading.Lock()

    def __call__(self, job: Job, queue: JobQueue) -> None:
        event = self.release.setdefault(job.key, threading.Event())
        with self.lock:
            self.started.append(job.key)
            self.running += 1
            self.most_running = max(self.most_running, self.running)
        try:
            while not event.wait(0.02):
                if job.cancel.is_set():
                    raise JobCancelled()
            if job.key == "broken":
                raise RuntimeError("the archive is damaged")
            queue.update(job, state="done")
        finally:
            with self.lock:
                self.running -= 1


def _states(queue: JobQueue) -> dict[str, str]:
    return {job["key"]: job["state"] for job in queue.snapshot()}


def test_jobs_run_one_at_a_time_in_order() -> None:
    gate = Gate()
    changes: list[int] = []
    queue = JobQueue(gate, lambda: changes.append(1))
    for name in ("a", "b", "c"):
        gate.release[name] = threading.Event()
        queue.enqueue(_job(name))

    wait_for(lambda: gate.started == ["a"])
    assert _states(queue) == {"a": "downloading", "b": "queued", "c": "queued"}
    gate.release["a"].set()
    wait_for(lambda: gate.started == ["a", "b"])
    gate.release["b"].set()
    gate.release["c"].set()
    wait_for(lambda: _states(queue) == {"a": "done", "b": "done", "c": "done"})

    assert gate.started == ["a", "b", "c"]
    assert gate.most_running == 1
    assert changes


def test_a_queued_job_is_cancelled_at_once_and_a_running_one_when_it_notices() -> None:
    gate = Gate()
    queue = JobQueue(gate, lambda: None)
    running, waiting = _job("running"), _job("waiting")
    queue.enqueue(running)
    queue.enqueue(waiting)
    wait_for(lambda: gate.started == ["running"])

    assert queue.cancel(waiting.id)
    assert _states(queue)["waiting"] == "cancelled"
    assert queue.cancel(running.id)
    wait_for(lambda: _states(queue)["running"] == "cancelled")

    assert gate.started == ["running"]
    assert not queue.cancel(running.id)
    assert not queue.cancel("no-such-job")


def test_a_failure_is_reported_with_its_reason_and_the_queue_goes_on() -> None:
    gate = Gate()
    queue = JobQueue(gate, lambda: None)
    gate.release["broken"] = threading.Event()
    gate.release["broken"].set()
    gate.release["next"] = threading.Event()
    gate.release["next"].set()
    broken = _job("broken")
    queue.enqueue(broken)
    queue.enqueue(_job("next"))

    wait_for(lambda: _states(queue) == {"broken": "failed", "next": "done"})
    failed = queue.get(broken.id)
    assert failed is not None
    assert failed.error == "the archive is damaged"


def test_only_finished_jobs_are_removed() -> None:
    gate = Gate()
    queue = JobQueue(gate, lambda: None)
    job = _job("a")
    queue.enqueue(job)
    wait_for(lambda: gate.started == ["a"])

    assert not queue.remove(job.id)
    gate.release["a"].set()
    wait_for(lambda: _states(queue) == {"a": "done"})
    assert queue.remove(job.id)
    assert queue.snapshot() == []


def test_stop_cancels_everything_and_refuses_new_jobs() -> None:
    gate = Gate()
    queue = JobQueue(gate, lambda: None)
    queue.enqueue(_job("a"))
    queue.enqueue(_job("b"))
    wait_for(lambda: gate.started == ["a"])

    queue.stop()

    wait_for(lambda: _states(queue) == {"a": "cancelled", "b": "cancelled"})
    try:
        queue.enqueue(_job("c"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("a stopped queue took a job")
