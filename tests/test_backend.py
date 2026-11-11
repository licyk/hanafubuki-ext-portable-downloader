"""The backend with a stand-in host: its state, its actions, and whole jobs through the
real ``download_file`` and ``extract_archive`` against a local HTTP server."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from hanafubuki_extension import INVALID_PARAMS, PERMISSION_DENIED, Host, RpcError
from portable_downloader.app import Backend
from portable_downloader.gpu import GpuInfo
from support import (
    TOP_DIR,
    FakeHost,
    HttpServer,
    entry,
    make_7z,
    make_tar_gz,
    make_zip,
    portable_files,
    portable_list,
    wait_for,
)

NIGHTLY = "comfyui_cuda-licyk-linux-20261109-nightly"
# The actions answer without the host: they never call it.
NO_HOST = cast(Host, None)


def _nvidia(_platform: str) -> GpuInfo:
    return GpuInfo(True, frozenset({"nvidia"}))


def _serve_package(server: HttpServer, tmp_path: Path, kind: str = "tar.gz", **route: Any) -> str:
    files = portable_files()
    if kind == "zip":
        data = make_zip(files)
    elif kind == "7z":
        data = make_7z(files, tmp_path)
    else:
        data = make_tar_gz(files)
    filename = f"{NIGHTLY}.{kind}"
    url = server.serve(f"/files/{filename}", data, **route)
    document = portable_list(
        {"nightly": [entry(filename, url), entry("older.tar.gz", url, build_date="20261101")]}
    )
    server.serve("/portable_list.json", json.dumps(document).encode())
    return filename


def _start(tmp_path: Path, server: HttpServer, **answers: Any) -> tuple[Backend, FakeHost]:
    backend = Backend(list_urls=[server.url("/portable_list.json")], detect_gpu=_nvidia)
    host = FakeHost(tmp_path / "data", **answers)
    backend.activate(cast(Host, host))
    wait_for(lambda: backend.state()["catalog"]["revision"] >= 1)
    wait_for(lambda: backend.state()["catalog"]["status"] == "ready")
    return backend, host


def _job(backend: Backend, job_id: str) -> dict[str, Any]:
    return next(job for job in backend.state()["jobs"] if job["id"] == job_id)


def _finished(backend: Backend, job_id: str) -> dict[str, Any] | None:
    job = _job(backend, job_id)
    return job if job["state"] in ("done", "failed", "cancelled") else None


def test_activation_reads_the_host_and_the_state_is_small(
    tmp_path: Path, http_server: HttpServer
) -> None:
    _serve_package(http_server, tmp_path)
    backend, host = _start(tmp_path, http_server)

    state = backend.state()
    assert state["platform"] == "linux"
    assert state["settings"] == {
        "source": "modelscope",
        "channel": "nightly",
        "downloadTool": "aria2",
        "autoExtract": True,
        "deleteArchive": False,
        "defaultFolder": str(tmp_path / "data" / "instances"),
    }
    assert state["gpu"] == {"detected": True, "vendors": ["nvidia"]}
    assert state["catalog"]["updateTime"] == "2026-11-11T01:54:13Z"
    assert state["catalog"]["fromCache"] is False
    assert host.called("events.subscribe") == [{"topics": ["settings"]}]
    assert (tmp_path / "data" / "portable_list.json").is_file()
    assert len(json.dumps(state)) < 4096
    wait_for(lambda: host.states)


def test_packages_are_this_platforms_without_urls(tmp_path: Path, http_server: HttpServer) -> None:
    _serve_package(http_server, tmp_path)
    backend, _ = _start(tmp_path, http_server)

    answer = backend.frame_call(NO_HOST, "downloader", "packages", {"source": "huggingface"}, {})

    assert answer["source"] == "huggingface"
    (package,) = answer["packages"]
    assert package["key"] == "comfyui_cuda"
    assert package["compatibility"] == "supported"
    assert [item["filename"] for item in package["nightly"]] == [
        f"{NIGHTLY}.tar.gz",
        "older.tar.gz",
    ]
    assert "http" not in json.dumps(answer)


def test_the_cache_answers_when_every_mirror_is_down(
    tmp_path: Path, http_server: HttpServer
) -> None:
    _serve_package(http_server, tmp_path)
    _start(tmp_path, http_server)
    http_server.routes["/portable_list.json"].status = 502

    backend, _ = _start(tmp_path, http_server)
    wait_for(lambda: backend.state()["catalog"]["error"])

    catalog = backend.state()["catalog"]
    assert catalog["status"] == "ready"
    assert catalog["fromCache"] is True
    assert "502" in catalog["error"]
    assert backend.dispatch("packages", {})["packages"]


def test_settings_events_change_what_the_page_sees(tmp_path: Path, http_server: HttpServer) -> None:
    _serve_package(http_server, tmp_path)
    backend, host = _start(tmp_path, http_server)

    backend.notification(
        cast(Host, host),
        "event",
        {
            "topic": "settings",
            "data": {
                "values": {
                    "source": "huggingface",
                    "defaultFolder": "/srv/ai",
                    "autoExtract": "yes",
                }
            },
        },
    )

    settings = backend.state()["settings"]
    assert settings["source"] == "huggingface"
    assert settings["defaultFolder"] == "/srv/ai"
    assert settings["autoExtract"] is True
    assert backend.dispatch("packages", {})["source"] == "huggingface"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"filename": "x"}, "`key` is required"),
        ({"key": "comfyui_cuda", "filename": "x", "folder": "relative/dir"}, "absolute"),
        (
            {"key": "comfyui_cuda", "filename": "nope.tar.gz", "folder": "/tmp"},
            "has no nope.tar.gz",
        ),
        ({"key": "comfyui_cuda", "filename": "x", "channel": "beta"}, "`channel` is one of"),
    ],
)
def test_enqueue_refuses_what_does_not_fit(
    tmp_path: Path, http_server: HttpServer, args: dict[str, Any], message: str
) -> None:
    _serve_package(http_server, tmp_path)
    backend, _ = _start(tmp_path, http_server)

    with pytest.raises(RpcError) as failure:
        backend.dispatch("enqueue", args)

    assert failure.value.code == INVALID_PARAMS
    assert message in failure.value.message


def test_an_unknown_action_is_invalid(tmp_path: Path, http_server: HttpServer) -> None:
    _serve_package(http_server, tmp_path)
    backend, _ = _start(tmp_path, http_server)

    with pytest.raises(RpcError) as failure:
        backend.ui_call(NO_HOST, "format-disk", {}, {})

    assert failure.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    ("kind", "tool"), [("tar.gz", "requests"), ("zip", "aria2"), ("7z", "requests")]
)
def test_a_job_downloads_extracts_and_registers(
    tmp_path: Path, http_server: HttpServer, kind: str, tool: str
) -> None:
    if tool == "aria2" and shutil.which("aria2c") is None:
        pytest.skip("aria2c is not installed")
    filename = _serve_package(http_server, tmp_path, kind)
    backend, host = _start(
        tmp_path, http_server, **{"settings.get": {"values": {"downloadTool": tool}}}
    )
    folder = tmp_path / "Portable Packages"

    job = backend.dispatch(
        "enqueue",
        {
            "key": "comfyui_cuda",
            "channel": "nightly",
            "filename": filename,
            "folder": str(folder),
            "deleteArchive": True,
        },
    )
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=60)

    assert done["state"] == "done", done["error"]
    package = folder / TOP_DIR
    assert done["packagePath"] == str(package)
    assert (package / "core" / "nodes.py").is_file()
    assert not (folder / filename).exists()
    assert sorted(path.name for path in folder.iterdir()) == [TOP_DIR]
    assert host.called("instances.scan") == [{"path": str(package)}]
    assert done["instances"] == [{"id": "inst-1", "name": "ComfyUI"}]
    total = sum(len(data) for data in portable_files().values())
    assert done["extracted"] == total == done["extractTotal"]
    wait_for(
        lambda: any(state["jobs"] and state["jobs"][-1]["state"] == "done" for state in host.states)
    )
    progress = wait_for(lambda: [p for p in host.called("ui.progress") if p.get("done")])
    assert progress[-1]["id"] == f"job-{job['id']}"
    assert "error" not in progress[-1]
    notices = wait_for(lambda: host.called("ui.notify"))
    assert notices[-1]["level"] == "info"


def test_without_auto_extract_the_archive_is_kept_and_nothing_registered(
    tmp_path: Path, http_server: HttpServer
) -> None:
    filename = _serve_package(http_server, tmp_path)
    backend, host = _start(
        tmp_path,
        http_server,
        **{"settings.get": {"values": {"autoExtract": False, "downloadTool": "requests"}}},
    )

    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=60)

    assert done["state"] == "done"
    assert done["archivePath"] == str(tmp_path / "out" / filename)
    assert (tmp_path / "out" / filename).is_file()
    assert host.called("instances.scan") == []


def test_a_refused_registration_leaves_the_package_with_a_warning(
    tmp_path: Path, http_server: HttpServer
) -> None:
    filename = _serve_package(http_server, tmp_path)
    backend, host = _start(
        tmp_path,
        http_server,
        **{
            "settings.get": {"values": {"downloadTool": "requests"}},
            "instances.scan": RpcError(PERMISSION_DENIED, "registerInstances is not granted"),
        },
    )

    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=60)

    assert done["state"] == "done"
    assert done["instances"] == []
    assert "registerInstances is not granted" in done["warnings"][0]
    assert (tmp_path / "out" / TOP_DIR / "core").is_dir()
    notice = wait_for(lambda: host.called("ui.notify"))[-1]
    assert notice["level"] == "warning"


def test_scan_warnings_are_read_tolerantly(tmp_path: Path, http_server: HttpServer) -> None:
    filename = _serve_package(http_server, tmp_path)
    scan = {
        "attached": [],
        "warnings": [
            {
                "kind": "alreadyManaged",
                "path": "/x/core",
                "message": "already managed",
                "instanceId": "i",
            },
            "plain text",
            42,
        ],
    }
    backend, _ = _start(
        tmp_path,
        http_server,
        **{"settings.get": {"values": {"downloadTool": "requests"}}, "instances.scan": scan},
    )

    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=60)

    assert done["warnings"] == ["/x/core: already managed", "plain text"]


def test_a_missing_file_fails_the_job(tmp_path: Path, http_server: HttpServer) -> None:
    filename = _serve_package(http_server, tmp_path)
    http_server.routes[f"/files/{filename}"].status = 404
    backend, host = _start(
        tmp_path, http_server, **{"settings.get": {"values": {"downloadTool": "requests"}}}
    )

    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=60)

    assert done["state"] == "failed"
    assert done["error"]
    notice = wait_for(lambda: host.called("ui.notify"))[-1]
    assert notice["level"] == "error"
    # A job that failed before a push showed it never opened a Task Center entry;
    # one that did closes it with the reason.
    reports = [p for p in host.called("ui.progress") if p["id"] == f"job-{job['id']}"]
    if reports:
        assert reports[-1]["done"] is True
        assert reports[-1]["error"] == done["error"]


@pytest.mark.parametrize("tool", ["requests", "aria2"])
def test_cancelling_a_download_stops_it(tmp_path: Path, http_server: HttpServer, tool: str) -> None:
    if tool == "aria2" and shutil.which("aria2c") is None:
        pytest.skip("aria2c is not installed")
    filename = "slow.tar.gz"
    url = http_server.serve(
        f"/files/{filename}", b"\0" * (4 * 1024 * 1024), chunk=16 * 1024, delay=0.02
    )
    http_server.serve(
        "/portable_list.json",
        json.dumps(portable_list({"nightly": [entry(filename, url)]})).encode(),
    )
    backend, _ = _start(
        tmp_path, http_server, **{"settings.get": {"values": {"downloadTool": tool}}}
    )

    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    wait_for(lambda: _job(backend, job["id"])["downloaded"] > 0, timeout=30)
    assert backend.dispatch("cancel", {"jobId": job["id"]}) == {"cancelled": True}
    done = wait_for(lambda: _finished(backend, job["id"]), timeout=30)

    assert done["state"] == "cancelled"
    assert backend.dispatch("remove", {"jobId": job["id"]}) == {"removed": True}
    assert backend.state()["jobs"] == []


def test_deactivate_cancels_the_running_job(tmp_path: Path, http_server: HttpServer) -> None:
    filename = "slow.tar.gz"
    url = http_server.serve(
        f"/files/{filename}", b"\0" * (4 * 1024 * 1024), chunk=16 * 1024, delay=0.02
    )
    http_server.serve(
        "/portable_list.json",
        json.dumps(portable_list({"nightly": [entry(filename, url)]})).encode(),
    )
    backend, host = _start(
        tmp_path, http_server, **{"settings.get": {"values": {"downloadTool": "requests"}}}
    )
    job = backend.dispatch(
        "enqueue", {"key": "comfyui_cuda", "filename": filename, "folder": str(tmp_path / "out")}
    )
    wait_for(lambda: _job(backend, job["id"])["downloaded"] > 0, timeout=30)

    backend.deactivate(cast(Host, host))

    assert wait_for(lambda: _finished(backend, job["id"]), timeout=30)["state"] == "cancelled"
