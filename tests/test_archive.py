"""Extracting through sd_webui_all_in_one's archive manager: layout, progress, cancellation."""

from __future__ import annotations

import io
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from portable_downloader import extract_child
from portable_downloader.archive import (
    ExtractCancelled,
    ExtractError,
    archive_stem,
    extract_package,
)
from support import TOP_DIR, make_7z, make_tar_gz, make_zip, portable_files

Maker = Callable[[dict[str, bytes], Path], tuple[str, bytes]]

FORMATS: dict[str, Maker] = {
    "zip": lambda files, _: ("pkg-nightly.zip", make_zip(files)),
    "tar.gz": lambda files, _: ("pkg-nightly.tar.gz", make_tar_gz(files)),
    "7z": lambda files, workdir: ("pkg-nightly.7z", make_7z(files, workdir)),
}


def _archive(tmp_path: Path, kind: str, files: dict[str, bytes]) -> Path:
    workdir = tmp_path / "build"
    workdir.mkdir(exist_ok=True)
    name, data = FORMATS[kind](files, workdir)
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    archive = folder / name
    archive.write_bytes(data)
    return archive


@pytest.mark.parametrize(
    ("filename", "stem"),
    [
        (
            "comfyui_cuda-licyk-linux-20261109-nightly.tar.gz",
            "comfyui_cuda-licyk-linux-20261109-nightly",
        ),
        ("fooocus_cuda-licyk-windows-v3.8.7z", "fooocus_cuda-licyk-windows-v3.8"),
        ("a.ZIP", "a"),
        ("plain", "plain"),
    ],
)
def test_the_stem_drops_the_archive_suffix(filename: str, stem: str) -> None:
    assert archive_stem(filename) == stem


@pytest.mark.parametrize("kind", list(FORMATS))
def test_a_wrapped_package_lands_as_its_top_directory(tmp_path: Path, kind: str) -> None:
    archive = _archive(tmp_path, kind, portable_files())
    progress: list[tuple[int, int | None]] = []

    package = extract_package(
        archive,
        archive.parent,
        lambda done, total: progress.append((done, total)),
        threading.Event(),
    )

    assert package == archive.parent / TOP_DIR
    assert (package / "core" / "main.py").read_bytes() == b"print('ComfyUI')\n"
    assert (package / "python" / "bin" / "python3").is_file()
    assert sorted(path.name for path in archive.parent.iterdir()) == sorted([archive.name, TOP_DIR])
    total = sum(len(data) for data in portable_files().values())
    assert progress[-1] == (total, total)


def test_an_unwrapped_archive_lands_under_its_stem(tmp_path: Path) -> None:
    archive = _archive(tmp_path, "zip", {"core/main.py": b"x", "python/bin/python3": b"y"})

    package = extract_package(archive, archive.parent, lambda *_: None, threading.Event())

    assert package == archive.parent / "pkg-nightly"
    assert (package / "core" / "main.py").is_file()
    assert not list(archive.parent.glob(".*"))


def test_an_existing_target_is_never_overwritten(tmp_path: Path) -> None:
    archive = _archive(tmp_path, "tar.gz", portable_files())
    existing = archive.parent / TOP_DIR
    existing.mkdir()
    (existing / "mine.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ExtractError, match="already exists"):
        extract_package(archive, archive.parent, lambda *_: None, threading.Event())

    assert (existing / "mine.txt").read_text(encoding="utf-8") == "keep"
    assert not (existing / "core").exists()
    assert not list(archive.parent.glob(".*"))


@pytest.mark.parametrize("kind", list(FORMATS))
def test_cancelling_kills_the_extraction_and_leaves_nothing(tmp_path: Path, kind: str) -> None:
    archive = _archive(tmp_path, kind, portable_files())
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(ExtractCancelled):
        extract_package(archive, archive.parent, lambda *_: None, cancel)

    assert [path.name for path in archive.parent.iterdir()] == [archive.name]


def test_an_archive_that_does_not_read_fails_with_the_library_reason(tmp_path: Path) -> None:
    folder = tmp_path / "downloads"
    folder.mkdir()
    archive = folder / "broken.7z"
    archive.write_bytes(b"not a 7z archive at all")

    with pytest.raises(ExtractError) as failure:
        extract_package(archive, folder, lambda *_: None, threading.Event())

    assert str(failure.value)
    assert [path.name for path in folder.iterdir()] == ["broken.7z"]


@pytest.mark.usefixtures("no_py7zr")
def test_a_7z_reaching_the_child_without_py7zr_fails_with_the_reason_and_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The parent runs 7-Zip for it; were the child asked anyway, the library would
    # pip-install py7zr into the application's interpreter: the child refuses first.
    reports = io.StringIO()
    monkeypatch.setattr(sys, "stdout", reports)
    archive = _archive(tmp_path, "zip", portable_files()).with_name("pkg-nightly.7z")
    target = tmp_path / "target"

    assert extract_child.main(["extract_child", str(archive), str(target)]) == 1

    error = json.loads(reports.getvalue().splitlines()[-1])["error"]
    assert "pkg-nightly.7z is a 7z archive" in error
    assert "py7zr" in error
    assert not target.exists()


def test_only_a_7z_needs_py7zr(tmp_path: Path) -> None:
    assert extract_child.missing_codec(tmp_path / "a.tar.gz") is None
    assert extract_child.missing_codec(tmp_path / "a.zip") is None
