"""The backend: its UI's state and actions, the catalog, the queue and the host calls they need."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hanafubuki_extension import INVALID_PARAMS, Handler, Host, RpcError

from . import gpu
from .archive import needs_sevenzip
from .catalog import (
    LIST_URLS,
    Catalog,
    CatalogCache,
    CatalogError,
    Fetch,
    fetch_document,
    parse_catalog,
)
from .jobs import ACTIVE, Job, JobQueue
from .pipeline import JobRunner, Registration
from .settings import CHANNELS, SOURCES, Settings
from .sevenzip import SevenZip
from .throttle import Throttle

# State pushes and Task Center progress at most four times a second.
_PUSH_INTERVAL = 0.25
_LIST_TIMEOUT = 10.0

_TEXT = {
    "en": {
        "downloading": "Downloading {name}",
        "extracting": "Extracting {name}",
        "registering": "Registering {name}",
        "cancelled": "Cancelled",
        "done": "{name} is ready: {count} instance(s) registered.",
        "doneUnregistered": "{name} is ready in {path}.",
        "failed": "{name} failed: {error}",
        "notRegistered": "The package was extracted but not registered: {error}",
        "noInstance": "No instance was found in the extracted package.",
    },
    "zh": {
        "downloading": "正在下载 {name}",
        "extracting": "正在解压 {name}",
        "registering": "正在注册 {name}",
        "cancelled": "已取消",
        "done": "{name} 已就绪：已注册 {count} 个实例。",
        "doneUnregistered": "{name} 已保存到 {path}。",
        "failed": "{name} 失败：{error}",
        "notRegistered": "整合包已解压，但未能注册：{error}",
        "noInstance": "解压后的整合包中未找到实例。",
    },
}


class Backend(Handler):
    """The portable downloader's backend."""

    def __init__(
        self,
        list_urls: Sequence[str] = LIST_URLS,
        fetch: Fetch | None = None,
        detect_gpu: Callable[[str], gpu.GpuInfo] = gpu.detect,
        sevenzip: SevenZip | None = None,
    ) -> None:
        """Builds the backend.

        Args:
            list_urls: The package list's mirrors, in order.
            fetch: Reads a URL's body (urllib by default).
            detect_gpu: Detects the local GPUs for a platform.
            sevenzip: Finds 7-Zip; by default this system's, downloaded into the data
                directory's ``tools``.
        """
        self._list_urls = tuple(list_urls)
        self._fetch = fetch
        self._detect_gpu = detect_gpu
        self._lock = threading.Lock()
        self._host: Host | None = None
        self._data_path: Path | None = None
        self._sevenzip = sevenzip or SevenZip(self._tools_dir)
        self._platform = "linux"
        self._instances_dir: str | None = None
        self._locale = "en"
        self._settings = Settings()
        self._gpu = gpu.GpuInfo()
        self._cache: CatalogCache | None = None
        self._catalog: Catalog | None = None
        self._catalog_status = "loading"
        self._catalog_error: str | None = None
        self._from_cache = False
        self._revision = 0
        self._refreshing = False
        self._progress_open: set[str] = set()
        self._announced: set[str] = set()
        self._throttle = Throttle(_PUSH_INTERVAL, self._publish)
        self._queue = JobQueue(JobRunner(self._register, self._sevenzip), self._throttle.poke)

    # --- Hooks -------------------------------------------------------------------------

    def activate(self, host: Host) -> None:
        """Reads the platform and settings, loads the cached list and starts fetching it."""
        self._host = host
        self._read_info(host)
        values = (host.call("settings.get") or {}).get("values")
        self._settings = Settings.from_values(values if isinstance(values, dict) else {})
        host.call("events.subscribe", {"topics": ["settings"]})
        self._data_path = _data_dir(host)
        self._cache = CatalogCache(self._data_path)
        cached = self._cache.load()
        if cached is not None:
            self._catalog, self._catalog_status, self._from_cache = cached, "ready", True
            self._revision += 1
        threading.Thread(target=self._prepare, name="prepare", daemon=True).start()

    def deactivate(self, host: Host) -> None:
        """Cancels the running download; the backend is stopping."""
        self._stop()

    def shutdown(self, host: Host) -> None:
        """Cancels the running download (when ``deactivate`` was not called)."""
        self._stop()

    def notification(self, host: Host, method: str, params: Any) -> None:
        """Follows the settings as the Extensions page writes them (on the loop's thread)."""
        if method != "event" or not isinstance(params, dict) or params.get("topic") != "settings":
            return
        data = params.get("data")
        values = data.get("values") if isinstance(data, dict) else None
        with self._lock:
            self._settings = Settings.from_values(values if isinstance(values, dict) else {})
        self._throttle.poke()

    # --- Its UI ------------------------------------------------------------------------

    def ui_state(self, host: Host, context: dict[str, Any]) -> Any:
        """The page's state: settings, GPU, the catalog's status and the jobs."""
        return self.state()

    def ui_call(self, host: Host, action: str, args: Any, context: dict[str, Any]) -> Any:
        """The page's actions, for a window that calls them through the UI service."""
        return self.dispatch(action, args)

    def frame_call(
        self, host: Host, frame: str, method: str, params: Any, context: dict[str, Any]
    ) -> Any:
        """The page's actions, as its frame client's ``call`` sends them."""
        return self.dispatch(method, params)

    def state(self) -> dict[str, Any]:
        """The whole state; cheap, since the host asks for it on every push."""
        with self._lock:
            settings = self._settings
            catalog = {
                "status": self._catalog_status,
                "updateTime": self._catalog.update_time if self._catalog else None,
                "fromCache": self._from_cache,
                "error": self._catalog_error,
                "revision": self._revision,
            }
        return {
            "platform": self._platform,
            "locale": self._locale,
            "instancesDir": self._instances_dir,
            "settings": settings.to_json(self._instances_dir),
            "gpu": self._gpu.to_json(),
            "catalog": catalog,
            "jobs": self._queue.snapshot(),
        }

    def dispatch(self, action: str, params: Any) -> Any:
        """Runs one of the page's actions.

        Raises:
            RpcError: ``INVALID_PARAMS`` for an unknown action or params that do not fit.
        """
        args = params if isinstance(params, dict) else {}
        if action == "packages":
            return self._packages(args)
        if action == "refresh":
            threading.Thread(target=self._refresh, name="refresh", daemon=True).start()
            return {}
        if action == "enqueue":
            return self._enqueue(args)
        if action == "cancel":
            return {"cancelled": self._queue.cancel(_required_text(args, "jobId"))}
        if action == "remove":
            return {"removed": self._queue.remove(_required_text(args, "jobId"))}
        if action == "clearFinished":
            removed = [job["id"] for job in self._queue.snapshot() if self._queue.remove(job["id"])]
            return {"removed": len(removed)}
        raise RpcError(INVALID_PARAMS, f"no action `{action}`")

    # --- Actions -----------------------------------------------------------------------

    def _packages(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            source = _choice(args, "source", SOURCES, self._settings.source)
            catalog, revision = self._catalog, self._revision
        packages = catalog.for_platform(source, self._platform) if catalog else ()
        return {
            "source": source,
            "platform": self._platform,
            "revision": revision,
            "packages": [package.to_json(self._gpu) for package in packages],
        }

    def _enqueue(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            settings, catalog = self._settings, self._catalog
        source = _choice(args, "source", SOURCES, settings.source)
        channel = _choice(args, "channel", CHANNELS, settings.channel)
        key, filename = _required_text(args, "key"), _required_text(args, "filename")
        folder = _folder(args.get("folder") or settings.default_folder or self._instances_dir)
        found = catalog.find(source, self._platform, key, channel, filename) if catalog else None
        if found is None:
            raise RpcError(INVALID_PARAMS, f"the package list has no {filename} for {key}")
        package, entry = found
        auto_extract = _flag(args, "autoExtract", settings.auto_extract)
        missing = (
            self._sevenzip.unavailable() if auto_extract and needs_sevenzip(filename) else None
        )
        if missing is not None:
            # Refused before a multi-GB download whose extraction would fail.
            raise RpcError(
                INVALID_PARAMS,
                f"{filename} is a 7z archive, which needs py7zr or 7-Zip to extract: "
                f"{missing}, or turn off extracting after download to download it anyway",
            )
        if any(
            job["filename"] == filename
            and job["folder"] == folder
            and job["state"] in ("queued", *ACTIVE)
            for job in self._queue.snapshot()
        ):
            raise RpcError(INVALID_PARAMS, f"{filename} is already in the queue for {folder}")
        job = Job(
            key=key,
            display_name=package.display_name,
            source=source,
            channel=channel,
            filename=filename,
            version=entry.version,
            build_date=entry.build_date,
            url=entry.url,
            folder=folder,
            tool=settings.download_tool,
            auto_extract=auto_extract,
            delete_archive=_flag(args, "deleteArchive", settings.delete_archive),
        )
        return self._queue.enqueue(job)

    # --- Background work ---------------------------------------------------------------

    def _read_info(self, host: Host) -> None:
        # Read again at each refresh: `instancesDir` follows the application's setting.
        info = host.call("host.info") or {}
        instances_dir = info.get("instancesDir")
        with self._lock:
            self._platform = str(info.get("platform") or self._platform)
            self._instances_dir = instances_dir if isinstance(instances_dir, str) else None
            self._locale = _locale(info.get("locale") or host.initialize_params.get("locale"))

    def _prepare(self) -> None:
        detected = self._detect_gpu(self._platform)
        with self._lock:
            self._gpu = detected
        self._throttle.poke()
        self._refresh()

    def _refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
            self._catalog_status = "loading"
        self._throttle.poke()
        try:
            if self._host is not None:
                self._read_info(self._host)
            document = fetch_document(self._list_urls, _LIST_TIMEOUT, self._fetch)
            catalog = parse_catalog(document)
            self._save_cache(document)
            with self._lock:
                self._catalog, self._from_cache, self._catalog_error = catalog, False, None
                self._revision += 1
        except (CatalogError, RpcError) as error:
            with self._lock:
                self._catalog_error = str(error)
        finally:
            with self._lock:
                self._refreshing = False
                self._catalog_status = "ready" if self._catalog else "failed"
            self._throttle.poke()

    def _save_cache(self, document: Any) -> None:
        if self._cache is None:
            return
        try:
            self._cache.save(document)
        except OSError as error:
            self._log("warn", f"could not cache the package list: {error}")

    def _tools_dir(self) -> Path:
        # Jobs run only after `activate`, which reads the data directory.
        assert self._data_path is not None
        return self._data_path / "tools"

    def _register(self, path: Path) -> Registration:
        host = self._host
        if host is None:
            return Registration()
        try:
            answer = host.call("instances.scan", {"path": str(path)}) or {}
        except RpcError as error:
            return Registration(warnings=[self._text("notRegistered", error=error.message)])
        attached = [item for item in answer.get("attached") or [] if isinstance(item, str)]
        warnings = [_warning(item) for item in answer.get("warnings") or []]
        if not attached and not warnings:
            warnings.append(self._text("noInstance"))
        instances = [
            {"id": instance, "name": self._instance_name(instance)} for instance in attached
        ]
        return Registration(instances=instances, warnings=[w for w in warnings if w])

    def _instance_name(self, instance_id: str) -> str:
        host = self._host
        try:
            answer = host.call("instances.get", {"id": instance_id}) if host else None
        except RpcError:
            return instance_id
        name = answer.get("name") if isinstance(answer, dict) else None
        return name if isinstance(name, str) and name else instance_id

    # --- Publishing --------------------------------------------------------------------

    def _publish(self) -> None:
        host = self._host
        if host is None:
            return
        state = self.state()
        try:
            host.emit_state(state)
        except OSError:
            return
        for job in state["jobs"]:
            self._report(host, job)

    def _report(self, host: Host, job: dict[str, Any]) -> None:
        job_id, name, state = job["id"], job["displayName"], job["state"]
        progress: dict[str, Any] | None = None
        if state in ACTIVE:
            self._progress_open.add(job_id)
            done, total = (
                (job["downloaded"], job["total"])
                if state == "downloading"
                else (job["extracted"], job["extractTotal"])
            )
            progress = {"title": self._text(state, name=name), "completed": done}
            if total:
                progress["total"] = total
        elif job_id in self._progress_open:
            self._progress_open.discard(job_id)
            progress = {"title": name, "done": True}
            if state != "done":
                progress["error"] = job["error"] or self._text("cancelled")
        if progress is not None:
            self._call(host, "ui.progress", {"id": f"job-{job_id}", **progress})
        if state in ("done", "failed") and job_id not in self._announced:
            self._announced.add(job_id)
            self._call(host, "ui.notify", self._notice(job))

    def _notice(self, job: dict[str, Any]) -> dict[str, Any]:
        name = job["displayName"]
        if job["state"] == "failed":
            return {
                "message": self._text("failed", name=name, error=job["error"]),
                "level": "error",
            }
        if job["instances"]:
            message = self._text("done", name=name, count=len(job["instances"]))
        else:
            message = self._text(
                "doneUnregistered", name=name, path=job["packagePath"] or job["archivePath"]
            )
        return {"message": message, "level": "warning" if job["warnings"] else "info"}

    def _call(self, host: Host, method: str, params: dict[str, Any]) -> None:
        try:
            host.call(method, params)
        except RpcError as error:
            self._log("warn", f"{method} failed: {error.message}")

    def _log(self, level: str, message: str) -> None:
        if self._host is not None:
            self._host.log(level, message)

    def _text(self, message: str, **values: Any) -> str:
        return _TEXT[self._locale][message].format(**values)

    def _stop(self) -> None:
        self._queue.stop()
        self._throttle.close()


def _data_dir(host: Host) -> Path:
    data_dir = host.initialize_params.get("dataDir") or os.environ.get("HANAFUBUKI_EXTENSION_DATA")
    if not isinstance(data_dir, str) or not data_dir:
        data_dir = (host.call("storage.path") or {}).get("path", "")
    return Path(data_dir)


def _locale(value: Any) -> str:
    if value == "auto" or not isinstance(value, str):
        value = os.environ.get("LANG", "")
    return "zh" if value.lower().startswith("zh") else "en"


def _folder(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, "choose a folder to download to")
    folder = Path(value.strip()).expanduser()
    if not folder.is_absolute():
        raise RpcError(INVALID_PARAMS, f"{value} is not an absolute path")
    if folder.exists() and not folder.is_dir():
        raise RpcError(INVALID_PARAMS, f"{value} is not a folder")
    return str(folder)


def _required_text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value:
        raise RpcError(INVALID_PARAMS, f"`{name}` is required")
    return value


def _choice(args: dict[str, Any], name: str, allowed: tuple[str, ...], default: str) -> str:
    value = args.get(name)
    if value is None:
        return default
    if value not in allowed:
        raise RpcError(INVALID_PARAMS, f"`{name}` is one of {', '.join(allowed)}")
    return value


def _flag(args: dict[str, Any], name: str, default: bool) -> bool:
    value = args.get(name)
    return value if isinstance(value, bool) else default


def _warning(item: Any) -> str:
    # The scan's warnings are its results other than `attached` ({kind, path, message, ...}).
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        message, path = item.get("message"), item.get("path")
        if isinstance(message, str) and message:
            return f"{path}: {message}" if isinstance(path, str) and path else message
    return ""
