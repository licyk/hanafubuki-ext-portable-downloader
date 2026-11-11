"""7-Zip for a ``.7z`` where py7zr is not installed: finding it, downloading it once,
and extracting with it (progress, failures, cancellation).

No 7-Zip is installed where these run, so a stand-in script (``support``) plays its
command line; a real one on PATH is exercised too when there is one.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from portable_downloader import sevenzip
from portable_downloader.archive import (
    ExtractCancelled,
    ExtractError,
    extract_package,
    needs_sevenzip,
)
from portable_downloader.sevenzip import Download, SevenZip, SevenZipError
from support import (
    TOP_DIR,
    HttpServer,
    fake_sevenzip_script,
    install_fake_sevenzip,
    make_zip,
    portable_files,
    wait_for,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a POSIX script")


def _zip_as_7z(tmp_path: Path) -> Path:
    folder = tmp_path / "downloads"
    folder.mkdir()
    archive = folder / "pkg-nightly.7z"
    archive.write_bytes(make_zip(portable_files()))
    return archive


def _finder(tmp_path: Path, download: Download | None = None, path: str = "") -> SevenZip:
    return SevenZip(lambda: tmp_path / "tools", download, environ={"PATH": path}, windows=False)


def _serve_fake(server: HttpServer, body: bytes | None = None, **fields: object) -> Download:
    body = fake_sevenzip_script() if body is None else body
    url = server.serve("/7za", body)
    values: dict = {
        "url": url,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "filename": "7za",
    }
    values.update(fields)
    return Download(**values)


# --- Which extractor -----------------------------------------------------------------


@pytest.mark.usefixtures("no_py7zr")
def test_without_py7zr_only_a_7z_needs_sevenzip() -> None:
    assert needs_sevenzip("fooocus_cuda-licyk-windows-v3.8.7Z")
    assert not needs_sevenzip("comfyui_cuda-licyk-linux-20261109-nightly.tar.gz")
    assert not needs_sevenzip("a.zip")


def test_with_py7zr_nothing_needs_sevenzip() -> None:
    pytest.importorskip("py7zr")
    assert not needs_sevenzip("a.7z")


# --- Finding it ----------------------------------------------------------------------


def test_7za_on_path_comes_first(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    for name in ("7zz", "7z", "7za"):
        install_fake_sevenzip(bin_dir, name)

    assert _finder(tmp_path, path=str(bin_dir)).installed() == bin_dir / "7za"
    (bin_dir / "7za").unlink()
    assert _finder(tmp_path, path=str(bin_dir)).installed() == bin_dir / "7z"
    (bin_dir / "7z").unlink()
    assert _finder(tmp_path, path=str(bin_dir)).installed() == bin_dir / "7zz"


def test_windows_looks_in_7zips_program_files_folder(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    (program_files / "7-Zip").mkdir(parents=True)
    (program_files / "7-Zip" / "7z.exe").write_bytes(b"MZ")
    environ = {"PATH": "", "ProgramFiles": str(program_files)}

    found = SevenZip(lambda: tmp_path, None, environ=environ, windows=True).installed()

    assert found == program_files / "7-Zip" / "7z.exe"
    assert SevenZip(lambda: tmp_path, None, environ=environ, windows=False).installed() is None


def test_without_7zip_or_a_download_it_says_what_to_install(tmp_path: Path) -> None:
    finder = _finder(tmp_path)

    reason = finder.unavailable()

    assert reason is not None
    assert "p7zip-full" in reason
    assert "PATH" in reason
    with pytest.raises(SevenZipError, match="p7zip-full"):
        finder.executable(threading.Event())
    assert not (tmp_path / "tools").exists()


@pytest.mark.parametrize(
    ("system", "machine", "url"),
    [
        ("win32", "AMD64", "/7za/windows/amd64/7za.exe"),
        ("win32", "ARM64", "/7za/windows/aarch64/7za.exe"),
        ("linux", "x86_64", None),
        ("darwin", "arm64", None),
    ],
)
def test_only_windows_downloads_7za(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, url: str | None
) -> None:
    monkeypatch.setattr(sevenzip.sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)

    download = sevenzip.platform_download()

    if url is None:
        assert download is None
    else:
        assert download is not None
        assert download.url.startswith("https://modelscope.cn/models/licyks/sd-webui-all-in-one/")
        assert download.url.endswith(url)
        assert len(download.sha256) == 64


# --- Downloading it once -------------------------------------------------------------


def test_7za_is_downloaded_once_and_then_reused(tmp_path: Path, http_server: HttpServer) -> None:
    download = _serve_fake(http_server)
    finder = _finder(tmp_path, download)
    assert finder.unavailable() is None

    first = finder.executable(threading.Event())
    second = _finder(tmp_path, download).executable(threading.Event())

    assert first == second == tmp_path / "tools" / "7za"
    assert os.access(first, os.X_OK)
    assert http_server.routes["/7za"].hits == 1
    assert sorted(path.name for path in (tmp_path / "tools").iterdir()) == ["7za"]


def test_7zip_on_path_is_used_without_downloading(tmp_path: Path, http_server: HttpServer) -> None:
    download = _serve_fake(http_server)
    installed = install_fake_sevenzip(tmp_path / "bin", "7z")

    found = _finder(tmp_path, download, path=str(tmp_path / "bin")).executable(threading.Event())

    assert found == installed
    assert http_server.routes["/7za"].hits == 0


def test_a_changed_cached_7za_is_downloaded_again(tmp_path: Path, http_server: HttpServer) -> None:
    download = _serve_fake(http_server)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "7za").write_bytes(b"#!/bin/sh\necho tampered\n")

    found = _finder(tmp_path, download).executable(threading.Event())

    assert found.read_bytes() == fake_sevenzip_script()
    assert http_server.routes["/7za"].hits == 1


@pytest.mark.parametrize(
    "fields",
    [{"sha256": "0" * 64}, {"size": 10}],
    ids=["checksum", "size"],
)
def test_a_download_that_is_not_the_pinned_file_is_refused(
    tmp_path: Path, http_server: HttpServer, fields: dict
) -> None:
    download = _serve_fake(http_server, **fields)

    with pytest.raises(SevenZipError, match="not the expected file"):
        _finder(tmp_path, download).executable(threading.Event())

    assert list((tmp_path / "tools").iterdir()) == []


def test_a_download_that_does_not_run_is_refused(tmp_path: Path, http_server: HttpServer) -> None:
    download = _serve_fake(http_server, b"#!/bin/sh\nexit 3\n")

    with pytest.raises(SevenZipError, match="does not run"):
        _finder(tmp_path, download).executable(threading.Event())

    assert list((tmp_path / "tools").iterdir()) == []


def test_a_failed_download_names_its_url(tmp_path: Path, http_server: HttpServer) -> None:
    download = Download(http_server.url("/missing"), 1, "0" * 64, "7za")

    with pytest.raises(SevenZipError, match=r"could not download 7-Zip from .*/missing"):
        _finder(tmp_path, download).executable(threading.Event())

    assert list((tmp_path / "tools").iterdir()) == []


def test_cancelling_the_download_leaves_nothing(tmp_path: Path, http_server: HttpServer) -> None:
    download = _serve_fake(http_server)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SevenZipError, match="cancelled"):
        _finder(tmp_path, download).executable(cancel)

    assert list((tmp_path / "tools").iterdir()) == []


# --- Extracting with it --------------------------------------------------------------


@pytest.mark.parametrize("style", ["backspace", "cr"])
def test_7zip_extracts_the_package_and_reports_its_percentages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, style: str
) -> None:
    monkeypatch.setenv("FAKE_7Z_STYLE", style)
    executable = install_fake_sevenzip(tmp_path / "bin")
    archive = _zip_as_7z(tmp_path)
    progress: list[tuple[int, int | None]] = []

    package = extract_package(
        archive,
        archive.parent,
        lambda done, total: progress.append((done, total)),
        threading.Event(),
        executable,
    )

    assert package == archive.parent / TOP_DIR
    assert (package / "core" / "main.py").read_bytes() == b"print('ComfyUI')\n"
    assert sorted(path.name for path in archive.parent.iterdir()) == sorted([archive.name, TOP_DIR])
    # One report per file (20, 40, ... 100), then the closing 100.
    percents = [done for done, _ in progress]
    assert percents == [20, 40, 60, 80, 100, 100]
    assert {total for _, total in progress} == {100}


def test_7zips_error_is_the_extractions_reason(tmp_path: Path) -> None:
    executable = install_fake_sevenzip(tmp_path / "bin")
    folder = tmp_path / "downloads"
    folder.mkdir()
    archive = folder / "broken.7z"
    archive.write_bytes(b"not a 7z archive at all")

    with pytest.raises(ExtractError) as failure:
        extract_package(archive, folder, lambda *_: None, threading.Event(), executable)

    assert "7-Zip (7za) exited with 2" in str(failure.value)
    assert "Can not open the file as [7z] archive" in str(failure.value)
    assert [path.name for path in folder.iterdir()] == ["broken.7z"]


def test_cancelling_kills_7zip_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "7za.pid"
    monkeypatch.setenv("FAKE_7Z_DELAY", "30")
    monkeypatch.setenv("FAKE_7Z_PID", str(pid_file))
    executable = install_fake_sevenzip(tmp_path / "bin")
    archive = _zip_as_7z(tmp_path)
    cancel = threading.Event()
    progress: list[int] = []
    errors: list[BaseException] = []

    def extract() -> None:
        try:
            extract_package(
                archive, archive.parent, lambda done, _: progress.append(done), cancel, executable
            )
        except BaseException as error:  # noqa: BLE001 - checked below
            errors.append(error)

    worker = threading.Thread(target=extract)
    started = time.monotonic()
    worker.start()
    wait_for(lambda: progress)
    cancel.set()
    worker.join(10)

    assert not worker.is_alive()
    assert time.monotonic() - started < 10
    assert len(errors) == 1
    assert isinstance(errors[0], ExtractCancelled)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    assert [path.name for path in archive.parent.iterdir()] == [archive.name]


def test_a_real_7zip_extracts_a_real_7z(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    found = next((shutil.which(name) for name in ("7za", "7z", "7zz") if shutil.which(name)), None)
    if found is None:
        pytest.skip("no 7-Zip is installed")
    archive = tmp_path / "downloads" / "pkg-nightly.7z"
    archive.parent.mkdir()
    with py7zr.SevenZipFile(archive, "w") as written:
        for name, data in portable_files().items():
            written.writestr(data, name)
    progress: list[tuple[int, int | None]] = []

    package = extract_package(
        archive,
        archive.parent,
        lambda done, total: progress.append((done, total)),
        threading.Event(),
        Path(found),
    )

    assert (package / "core" / "nodes.py").read_bytes() == b"NODES = {}\n"
    assert progress[-1] == (100, 100)
