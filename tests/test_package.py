"""The package as the application reads it: a development link, the manifest's files,
the built page under the frame's policy, and the archive ``scripts/package.py`` writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # the backend runs on 3.10 too; its tests read TOML with tomli there
    tomllib = pytest.importorskip("tomli")

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = tomllib.loads((ROOT / "hanafubuki-extension.toml").read_text(encoding="utf-8"))
RELEASES = "https://github.com/licyk/hanafubuki-ext-portable-downloader/releases"


def test_a_development_link_finds_no_symlink() -> None:
    # The application walks the whole linked folder (`.git` and `web/node_modules`
    # included) and refuses it at the first entry that is neither a file nor a directory.
    links = []
    for directory, subdirectories, files in os.walk(ROOT):
        for name in subdirectories + files:
            path = Path(directory, name)
            if path.is_symlink():
                links.append(str(path.relative_to(ROOT)))
    assert links == [], "a development link would be refused; see web/.npmrc"


def test_every_file_the_manifest_names_exists() -> None:
    backend, contributes = MANIFEST["backend"], MANIFEST["contributes"]
    named = [backend["python"], backend["requirements"], contributes["settings"]]
    named += [entry["entry"] for entry in contributes["ui"]]
    named += [contributes["locales"].replace("{locale}", locale) for locale in ("en", "zh")]
    assert [name for name in named if not (ROOT / name).is_file()] == []
    assert MANIFEST["id"] == "io.github.licyk.portable-downloader"
    assert backend["sdWebuiAllInOne"] is True
    assert MANIFEST["permissions"] == {"instances": "read", "registerInstances": True}
    assert MANIFEST["engines"] == {"hanafubuki": ">=0.3.34, <0.4", "api": 1}
    assert MANIFEST["update"] == {"url": f"{RELEASES}/latest/download/latest.json"}


def test_every_settings_message_key_has_both_locales() -> None:
    import json

    prefix = "ext.io.github.licyk.portable-downloader."
    keys = set(
        re.findall(
            r'"key": "' + re.escape(prefix) + r'([^"]+)"',
            (ROOT / "schemas/settings.json").read_text(),
        )
    )
    for locale in ("en", "zh"):
        strings = json.loads((ROOT / f"locales/{locale}.json").read_text(encoding="utf-8"))
        for key in keys:
            value: object = strings
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            assert isinstance(value, str) and value, f"{locale}: {key}"


def _page_files() -> list[Path]:
    return sorted(path for path in (ROOT / "ui").iterdir() if path.is_file())


def test_the_built_page_has_no_inline_script_or_handler() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL):
        assert tag.strip() == "", "an inline script: the frame's script-src refuses it"
    assert not re.search(r"\son[a-z]+\s*=", html), "an inline event handler"
    urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    # The application's UI kit and its components' styles, which the host serves
    # at the package root, come before the page's own stylesheet; everything else
    # is the page's own file.
    assert urls[:2] == ["../__hanafubuki/ui.css", "../__hanafubuki/ui-components.css"]
    for url in urls[2:]:
        assert url.startswith("./"), f"{url} is not relative to the page"
        assert (ROOT / "ui" / url).is_file()


def _resolve(importer: str, specifier: str) -> str:
    """A relative module specifier resolved against the module that imports it."""
    resolved = PurePosixPath(importer).parent / specifier
    return os.path.normpath(str(resolved)).replace(os.sep, "/")


def test_the_host_modules_resolve_to_the_package_root() -> None:
    # The host serves the frame client, the component bundle and Vue at
    # `<package root>/__hanafubuki/`. The page imports Vue at the very URL the
    # bundle does (`./vue.js` beside `ui.js`), so the two share one runtime, and
    # carries no Vue of its own: a bare `vue` specifier would not even load.
    shared_vue = _resolve("__hanafubuki/ui.js", "./vue.js")
    imports = []
    for path in _page_files():
        if path.suffix == ".js":
            text = path.read_text(encoding="utf-8")
            for specifier in re.findall(r'(?:\bfrom|\bimport)\s*\(?\s*"([^"]+)"', text):
                assert specifier.startswith(("./", "../")), f"{path.name} imports {specifier}"
                imports.append(_resolve(f"ui/{path.name}", specifier))
            assert "__v_isRef" not in text, f"{path.name} bundles a copy of Vue"
    host = {name for name in imports if name.startswith("__hanafubuki/")}
    assert host == {"__hanafubuki/frame.js", "__hanafubuki/ui.js", shared_vue}


def test_the_built_page_neither_fetches_nor_stores() -> None:
    for path in _page_files():
        if path.suffix == ".js":
            text = path.read_text(encoding="utf-8")
            for forbidden in (
                "fetch(",
                "localStorage",
                "sessionStorage",
                "XMLHttpRequest",
                "history.pushState",
                "new Function",
            ):
                assert forbidden not in text, f"{path.name} uses {forbidden}"


def test_the_archive_holds_the_package_and_no_development_files(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package.py"), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    archive = Path(completed.stdout.strip())

    assert archive.name == f"io.github.licyk.portable-downloader-{MANIFEST['version']}.zip"
    names = zipfile.ZipFile(archive).namelist()
    assert "hanafubuki-extension.toml" in names
    assert "backend/main.py" in names
    assert "backend/portable_downloader/extract_child.py" in names
    assert "ui/index.html" in names
    assert "requirements.txt" in names
    assert {"locales/en.json", "locales/zh.json", "schemas/settings.json"} <= set(names)
    for name in names:
        assert not name.startswith(("web/", "tests/", "scripts/", ".")), name
        assert "__pycache__" not in name


def test_latest_json_offers_the_archive_as_its_release_publishes_it(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package.py"), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    archive = Path(completed.stdout.strip())
    version = MANIFEST["version"]

    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8")) == [
        {
            "version": version,
            "download_url": f"{RELEASES}/download/v{version}/{archive.name}",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "platform": "any",
            "architecture": "any",
        }
    ]
