"""The package list: reading the recorded list, filtering it, mirrors and the cache."""

from __future__ import annotations

import json

import pytest
from portable_downloader.catalog import (
    CatalogCache,
    CatalogError,
    fetch_document,
    parse_catalog,
)
from portable_downloader.gpu import GpuInfo
from support import HttpServer


def test_the_recorded_list_reads_by_source_and_platform(fixture_list: dict) -> None:
    catalog = parse_catalog(fixture_list)

    assert catalog.update_time == "2026-11-11T01:54:13Z"
    linux = catalog.for_platform("huggingface", "linux")
    assert [package.key for package in linux] == ["comfyui_cuda"]
    assert [package.key for package in catalog.for_platform("modelscope", "macos")] == [
        "comfyui_mps"
    ]
    assert len(catalog.for_platform("huggingface", "windows")) == 23
    assert catalog.for_platform("huggingface", "freebsd") == ()
    assert catalog.for_platform("nowhere", "linux") == ()


def test_entries_are_newest_first_and_keep_their_channel(fixture_list: dict) -> None:
    package = parse_catalog(fixture_list).for_platform("huggingface", "linux")[0]

    dates = [entry.build_date or "" for entry in package.nightly]
    assert dates == sorted(dates, reverse=True)
    assert package.stable == ()
    assert all(entry.channel == "nightly" for entry in package.nightly)
    assert package.nightly[0].filename.endswith(".tar.gz")


def test_the_page_never_sees_urls_and_gets_the_gpu(fixture_list: dict) -> None:
    catalog = parse_catalog(fixture_list)
    packages = [
        package.to_json(GpuInfo(True, frozenset({"nvidia"})))
        for package in catalog.for_platform("modelscope", "windows")
    ]

    text = json.dumps(packages, ensure_ascii=False)
    assert "http" not in text
    by_key = {package["key"]: package for package in packages}
    assert by_key["comfyui_cuda"]["gpu"] == "nvidia"
    assert by_key["comfyui_cuda"]["compatibility"] == "supported"
    assert by_key["comfyui_rocm"]["compatibility"] == "unsupported"
    # The largest platform's list stays far below the host's 256 KiB push bound.
    assert len(text.encode()) < 64 * 1024


def test_find_names_one_entry_of_one_channel(fixture_list: dict) -> None:
    catalog = parse_catalog(fixture_list)
    stable = catalog.for_platform("huggingface", "windows")
    fooocus = next(package for package in stable if package.key == "fooocus_cuda")
    filename = fooocus.stable[0].filename

    found = catalog.find("huggingface", "windows", "fooocus_cuda", "stable", filename)

    assert found is not None
    assert found[1].url.startswith("https://huggingface.co/")
    assert found[1].version == "3.8"
    assert catalog.find("huggingface", "windows", "fooocus_cuda", "nightly", filename) is None
    assert catalog.find("huggingface", "linux", "fooocus_cuda", "stable", filename) is None


def test_what_does_not_read_is_left_out() -> None:
    document = {
        "update_time": 7,
        "resources": {
            "huggingface": {
                "linux": {
                    "good": {
                        "nightly": [
                            {
                                "filename": "a.tar.gz",
                                "url": "https://x/a.tar.gz",
                                "build_date": "1",
                            },
                            {"filename": "", "url": "https://x/b"},
                            "not an entry",
                            {"filename": "c.tar.gz"},
                        ],
                        "stable": "not a list",
                        "extra": True,
                    },
                    "bad": [],
                },
                "macos": "not a table",
            },
            "modelscope": None,
        },
    }

    catalog = parse_catalog(document)

    assert catalog.update_time == ""
    (package,) = catalog.for_platform("huggingface", "linux")
    assert package.display_name == "good"
    assert [entry.filename for entry in package.nightly] == ["a.tar.gz"]
    assert package.stable == ()


@pytest.mark.parametrize("document", [None, [], {"resources": []}, {"update_time": "x"}])
def test_a_document_without_resources_is_refused(document: object) -> None:
    with pytest.raises(CatalogError):
        parse_catalog(document)


def test_mirrors_are_tried_in_order_until_one_answers_a_list(
    http_server: HttpServer, fixture_list: dict
) -> None:
    urls = [
        http_server.serve("/a.json", b"", status=500),
        http_server.url("/missing.json"),
        http_server.serve("/c.json", b"<html>not json</html>"),
        http_server.serve("/d.json", b'{"no": "resources"}'),
        http_server.serve("/e.json", json.dumps(fixture_list).encode()),
        http_server.serve("/f.json", json.dumps(fixture_list).encode()),
    ]

    document = fetch_document(urls, timeout=5)

    assert document["update_time"] == fixture_list["update_time"]
    assert http_server.routes["/a.json"].hits == 1
    assert http_server.routes["/e.json"].hits == 1
    assert http_server.routes["/f.json"].hits == 0


def test_every_mirror_failing_says_why_for_each(http_server: HttpServer) -> None:
    urls = [http_server.serve("/a.json", b"", status=503), http_server.url("/b.json")]

    with pytest.raises(CatalogError) as failure:
        fetch_document(urls, timeout=5)

    assert "/a.json" in str(failure.value)
    assert "/b.json" in str(failure.value)


def test_the_cache_keeps_the_last_list(tmp_path, fixture_list: dict) -> None:
    cache = CatalogCache(tmp_path / "data")
    assert cache.load() is None

    cache.save(fixture_list)

    assert cache.load() == parse_catalog(fixture_list)
    cache.path.write_text("{broken", encoding="utf-8")
    assert cache.load() is None
