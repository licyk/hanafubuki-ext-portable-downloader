"""The backend as the application runs it: ``backend/main.py`` over stdin and stdout.

The test plays the application: it answers the backend's host calls, and checks that
every byte on stdout is a protocol frame, through a real download, extraction (in
the child process) and registration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO, cast

from hanafubuki_extension.protocol import read_frame, write_frame
from support import (
    TOP_DIR,
    HttpServer,
    entry,
    make_tar_gz,
    portable_files,
    portable_list,
    wait_for,
)

ROOT = Path(__file__).resolve().parent.parent


class Application:
    """The application's side of one backend process."""

    def __init__(self, process: subprocess.Popen[bytes], answers: dict[str, Any]) -> None:
        self.process = process
        self.answers = answers
        self.requests: list[tuple[str, Any]] = []
        self.notifications: list[tuple[str, Any]] = []
        self.responses: dict[int, dict[str, Any]] = {}
        self.failure: Exception | None = None
        self.lock = threading.Lock()
        self.next_id = 1
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while (message := read_frame(cast(BinaryIO, self.process.stdout))) is not None:
                if "method" not in message:
                    with self.lock:
                        self.responses[message["id"]] = message
                    continue
                method, params = message["method"], message.get("params")
                if "id" not in message:
                    with self.lock:
                        self.notifications.append((method, params))
                    continue
                with self.lock:
                    self.requests.append((method, params))
                answer = self.answers.get(method, {})
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": answer(params) if callable(answer) else answer,
                    }
                )
        except Exception as error:  # noqa: BLE001 - the test asserts there is none
            self.failure = error

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        with self.lock:
            write_frame(cast(BinaryIO, self.process.stdin), message)

    def call(self, method: str, params: Any = None, timeout: float = 15) -> Any:
        with self.lock:
            call_id = self.next_id
            self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": call_id, "method": method, "params": params or {}})
        response = wait_for(lambda: self.responses.get(call_id), timeout=timeout)
        assert "error" not in response, response
        return response["result"]

    def pushed(self) -> list[Any]:
        with self.lock:
            return [params["state"] for method, params in self.notifications if method == "ui.emit"]

    def requested(self, method: str) -> list[Any]:
        with self.lock:
            return [params for name, params in self.requests if name == method]


def test_the_backend_speaks_the_protocol_through_a_whole_job(
    tmp_path: Path, http_server: HttpServer
) -> None:
    filename = "comfyui_cuda-licyk-linux-20261109-nightly.tar.gz"
    url = http_server.serve(f"/files/{filename}", make_tar_gz(portable_files()))
    list_url = http_server.serve(
        "/portable_list.json",
        json.dumps(portable_list({"nightly": [entry(filename, url)]})).encode(),
    )
    data_dir, folder = tmp_path / "data", tmp_path / "packages"
    tool = "aria2" if shutil.which("aria2c") else "requests"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HANAFUBUKI_EXTENSION_ID": "io.github.licyk.portable-downloader",
        "HANAFUBUKI_EXTENSION_DATA": str(data_dir),
        "PORTABLE_DOWNLOADER_LIST_URLS": list_url,
    }
    stderr = (tmp_path / "backend.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "main.py")],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
    )
    app = Application(
        process,
        {
            "host.info": {
                "version": "0.3.29",
                "protocolVersion": 1,
                "locale": "zh",
                "platform": "linux",
                "instancesDir": str(folder),
            },
            "settings.get": {"values": {"downloadTool": tool}},
            "events.subscribe": {"topics": ["settings"]},
            "instances.scan": {"attached": ["comfyui-1"], "warnings": []},
            "instances.get": {"id": "comfyui-1", "name": "ComfyUI 1"},
        },
    )
    try:
        initialized = app.call(
            "initialize",
            {
                "protocolVersion": 1,
                "extension": {"id": "io.github.licyk.portable-downloader", "version": "0.1.0"},
                "permissions": {"instances": "read", "registerInstances": True},
                "host": {"version": "0.3.29"},
                "dataDir": str(data_dir),
                "locale": "zh",
            },
        )
        assert initialized["protocolVersion"] == 1
        assert {"activate", "deactivate", "ui"} <= set(initialized["hooks"])
        app.call("activate")
        assert app.call("ping") == {}
        state = wait_for(
            lambda: (
                (s := app.call("ui.state", {"context": {}}))["catalog"]["status"] == "ready" and s
            )
        )
        assert state["locale"] == "zh"
        assert state["settings"]["defaultFolder"] == str(folder)

        job = app.call(
            "ui.frame.call",
            {
                "frame": "downloader",
                "method": "enqueue",
                "params": {"key": "comfyui_cuda", "filename": filename},
                "context": {},
            },
        )
        done = wait_for(
            lambda: next(
                (
                    j
                    for s in app.pushed()
                    for j in s["jobs"]
                    if j["id"] == job["id"] and j["state"] in ("done", "failed")
                ),
                None,
            ),
            timeout=60,
        )

        assert done["state"] == "done", done["error"]
        assert done["instances"] == [{"id": "comfyui-1", "name": "ComfyUI 1"}]
        assert app.requested("instances.scan") == [{"path": str(folder / TOP_DIR)}]
        assert wait_for(lambda: app.requested("ui.notify"))[-1]["message"].startswith("ComfyUI")
        app.call("deactivate")
        assert app.call("shutdown") == {}
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        app.reader.join(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
        stderr.close()

    assert app.failure is None, f"stdout carried something that is not a frame: {app.failure}"
    log = (tmp_path / "backend.log").read_text(encoding="utf-8", errors="replace")
    assert filename in log  # the library's own log lines went to stderr, not the protocol
