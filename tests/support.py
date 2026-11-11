"""Test helpers: a local HTTP server, synthetic portable archives and a stand-in host.

The tests run with the SDK and sd_webui_all_in_one on PYTHONPATH (see README.md),
as the application runs the backend.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tarfile
import threading
import time
import zipfile
from collections.abc import Generator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from hanafubuki_extension import METHOD_NOT_FOUND, RpcError

FIXTURES = Path(__file__).parent / "fixtures"
TOP_DIR = "comfyui_cuda-licyk-linux-20261109"


@dataclass
class Route:
    """What the server answers for a path: a status, a body, and how slowly."""

    body: bytes = b""
    status: int = 200
    chunk: int = 64 * 1024
    delay: float = 0.0
    hits: int = 0


@dataclass
class HttpServer:
    """A local server whose routes the test sets."""

    base: str
    routes: dict[str, Route] = field(default_factory=dict)

    def url(self, path: str) -> str:
        return f"{self.base}{path}"

    def serve(self, path: str, body: bytes, **options: Any) -> str:
        self.routes[path] = Route(body=body, **options)
        return self.url(path)


@contextlib.contextmanager
def serve_http() -> Generator[HttpServer]:
    """Runs a local HTTP server for the duration of the block."""
    server_state = HttpServer(base="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _route(self) -> Route | None:
            route = server_state.routes.get(self.path.split("?")[0])
            if route is None:
                self.send_error(404)
            elif route.status != 200:
                route.hits += 1
                self.send_error(route.status)
                return None
            return route

        def do_HEAD(self) -> None:
            route = self._route()
            if route is None:
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(route.body)))
            self.end_headers()

        def do_GET(self) -> None:
            route = self._route()
            if route is None:
                return
            route.hits += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(route.body)))
            self.end_headers()
            try:
                for start in range(0, len(route.body), route.chunk):
                    self.wfile.write(route.body[start : start + route.chunk])
                    self.wfile.flush()
                    if route.delay:
                        time.sleep(route.delay)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server_state.base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server_state
    finally:
        server.shutdown()
        server.server_close()


def portable_files(top: str = TOP_DIR) -> dict[str, bytes]:
    """A portable package as the builds lay it out: one top directory, ``core`` and ``python``."""
    return {
        f"{top}/core/main.py": b"print('ComfyUI')\n",
        f"{top}/core/nodes.py": b"NODES = {}\n",
        f"{top}/core/comfy/__init__.py": b"",
        f"{top}/python/bin/python3": b"#!/bin/sh\n",
        f"{top}/launch.sh": b"#!/bin/sh\n" + b"x" * 200_000,
    }


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def make_tar_gz(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def make_7z(files: dict[str, bytes], workdir: Path) -> bytes:
    py7zr = pytest.importorskip("py7zr")
    path = workdir / "package.7z"
    with py7zr.SevenZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writef(io.BytesIO(data), name)
    return path.read_bytes()


# Stands in for 7-Zip's command line where none is installed: `-h` prints its banner,
# `x <archive> -o<dir> -y -bsp1 -bso0` extracts a zip, drawing its progress as 7-Zip
# does (backspaces, or carriage returns with FAKE_7Z_STYLE=cr), and fails a bad
# archive with 7-Zip's message. FAKE_7Z_DELAY sleeps after each file; FAKE_7Z_PID
# names a file it writes its PID to.
_FAKE_SEVENZIP = r"""
import os
import sys
import time
import zipfile

args = sys.argv[1:]
if not args or args[0] == "-h":
    print("7-Zip (a) 26.00 (fake) : Copyright (c) 1999-2026 Igor Pavlov")
    sys.exit(0)
if args[0] != "x" or not {"-y", "-bsp1", "-bso0"} <= set(args):
    sys.stderr.write("Command Line Error:\nUnsupported command: " + " ".join(args) + "\n")
    sys.exit(7)
if os.environ.get("FAKE_7Z_PID"):
    with open(os.environ["FAKE_7Z_PID"], "w") as pid:
        pid.write(str(os.getpid()))
archive = args[1]
out = next(arg[2:] for arg in args if arg.startswith("-o"))
try:
    package = zipfile.ZipFile(archive)
except zipfile.BadZipFile:
    sys.stderr.write("ERROR: " + archive + "\n" + archive + "\n")
    sys.stderr.write("Open ERROR: Can not open the file as [7z] archive\n\n")
    sys.stderr.write("ERRORS:\nIs not archive\n")
    sys.exit(2)
names = package.namelist()
shown = ""
for index, name in enumerate(names, 1):
    package.extract(name, out)
    text = "%3d%% %d - %s" % (index * 100 // len(names), index, name)
    if os.environ.get("FAKE_7Z_STYLE") == "cr":
        sys.stdout.write("\r" + text)
    else:
        erase = "\b" * len(shown)
        sys.stdout.write(erase + " " * len(shown) + erase + text)
    sys.stdout.flush()
    shown = text
    time.sleep(float(os.environ.get("FAKE_7Z_DELAY", "0")))
sys.stdout.write("\b" * len(shown) + " " * len(shown) + "\b" * len(shown))
"""


def fake_sevenzip_script() -> bytes:
    """The stand-in 7-Zip as an executable script for this interpreter (POSIX only)."""
    return f"#!{sys.executable}\n{_FAKE_SEVENZIP}".encode()


def install_fake_sevenzip(directory: Path, name: str = "7za") -> Path:
    """Writes the stand-in 7-Zip into ``directory`` as ``name``, executable."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(fake_sevenzip_script())
    path.chmod(0o755)
    return path


def portable_list(entries: dict[str, list[dict[str, Any]]], platform: str = "linux") -> dict:
    """A ``portable_list.json`` with ``comfyui_cuda`` for ``platform`` in both sources."""
    package = {
        "display_name": "ComfyUI (NVIDIA)",
        "description": "ComfyUI 的 NVIDIA 显卡整合包",
        "stable": entries.get("stable", []),
        "nightly": entries.get("nightly", []),
    }
    return {
        "update_time": "2026-11-11T01:54:13Z",
        "resources": {
            source: {platform: {"comfyui_cuda": package}}
            for source in ("huggingface", "modelscope")
        },
    }


def entry(filename: str, url: str, channel: str = "nightly", build_date: str = "20261109") -> dict:
    return {
        "filename": filename,
        "url": url,
        "path": f"portable/{channel}/comfyui_cuda/{filename}",
        "version": None,
        "build_date": build_date,
        "channel": channel,
        "signature": "licyk",
        "platform": "linux",
        "extension": filename.split(".", 1)[1],
    }


class FakeHost:
    """A stand-in for the SDK's ``Host``: answers the host calls the backend makes, records them."""

    def __init__(self, data_dir: Path, **answers: Any) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.states: list[Any] = []
        self.lock = threading.Lock()
        self.initialize_params: dict[str, Any] = {"dataDir": str(data_dir), "locale": "en"}
        self.answers: dict[str, Any] = {
            "host.info": {
                "version": "0.3.29",
                "protocolVersion": 1,
                "locale": "en",
                "platform": "linux",
                "instancesDir": str(data_dir / "instances"),
            },
            "settings.get": {"values": {}},
            "events.subscribe": {"topics": ["settings"]},
            "instances.scan": {"attached": ["inst-1"], "warnings": []},
            "instances.get": {"id": "inst-1", "name": "ComfyUI"},
            "ui.progress": {},
            "ui.notify": {},
        }
        self.answers.update(answers)

    def call(self, method: str, params: Any = None) -> Any:
        with self.lock:
            self.calls.append((method, params))
        answer = self.answers.get(method, RpcError(METHOD_NOT_FOUND, f"no method {method}"))
        if isinstance(answer, Exception):
            raise answer
        return answer(params) if callable(answer) else answer

    def notify(self, method: str, params: Any = None) -> None:
        with self.lock:
            self.calls.append((method, params))

    def emit_state(self, state: Any) -> None:
        with self.lock:
            self.states.append(json.loads(json.dumps(state)))

    def emit_frame(self, frame: str, event: str, payload: Any = None) -> None:
        self.notify("ui.frame.emit", {"frame": frame, "event": event, "payload": payload})

    def log(self, level: str, message: str) -> None:
        self.notify("log.write", {"level": level, "message": message})

    def called(self, method: str) -> list[Any]:
        with self.lock:
            return [params for name, params in self.calls if name == method]


def wait_for(predicate: Any, timeout: float = 20.0, interval: float = 0.05) -> Any:
    """Polls ``predicate`` until it answers something truthy, which it returns."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {predicate}")


def recorded_list() -> dict:
    """The recorded ``portable_list.json`` (fetched 2026-11-11)."""
    return json.loads((FIXTURES / "portable_list.json").read_text(encoding="utf-8"))
