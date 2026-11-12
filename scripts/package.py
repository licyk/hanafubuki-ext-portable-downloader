"""Builds the installable archive: ``python scripts/package.py [--out DIR]``.

The archive holds the package's files at its root (the manifest, the backend,
the settings form, the locales, the built page in ``ui/``, the requirements, the
README and the license) and none of the development files (``web/``, ``tests/``, ``scripts/``,
caches). Build the page first (``npm run build`` in ``web/``).

``latest.json`` is written beside it: the update source the manifest's ``[update] url``
names, one entry for every system, whose ``download_url`` is the archive as the
release ``v<version>`` publishes it. Only the archive's path is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ("hanafubuki-extension.toml", "LICENSE", "requirements.txt", "README.md")
DIRECTORIES = ("backend", "schemas", "locales", "ui")
SKIPPED = ("__pycache__",)
# The newest release's asset, as the manifest's `[update] url` names it.
LATEST_ASSET = "/releases/latest/download/latest.json"


def package_files(root: Path = ROOT) -> Iterator[Path]:
    """The package's files, relative to ``root``, in a stable order."""
    for name in FILES:
        yield Path(name)
    for directory in DIRECTORIES:
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root)
            if path.is_file() and not any(part in SKIPPED for part in relative.parts):
                yield relative


def version(root: Path = ROOT) -> str:
    """The manifest's version."""
    text = (root / "hanafubuki-extension.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("the manifest has no version")
    return match.group(1)


def update_url(root: Path = ROOT) -> str:
    """The manifest's ``[update] url``."""
    text = (root / "hanafubuki-extension.toml").read_text(encoding="utf-8")
    match = re.search(r'^\[update\]\s*\nurl\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("the manifest has no [update] url")
    return match.group(1)


def build(out: Path, root: Path = ROOT) -> Path:
    """Writes ``io.github.licyk.portable-downloader-<version>.zip`` and ``latest.json``."""
    if not (root / "ui" / "index.html").is_file():
        raise SystemExit("ui/index.html is missing: build the page first (npm run build in web/)")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"io.github.licyk.portable-downloader-{version(root)}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for relative in package_files(root):
            zipped.write(root / relative, relative.as_posix())
    entries = latest(archive, version(root), update_url(root))
    (out / "latest.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return archive


def latest(archive: Path, release: str, source: str) -> list[dict[str, str]]:
    """``latest.json`` for ``archive``: one entry for any system, from release ``v<release>``."""
    if not source.endswith(LATEST_ASSET):
        raise ValueError(f"[update] url is not a GitHub release's latest.json: {source}")
    releases = source.removesuffix(LATEST_ASSET)
    return [
        {
            "version": release,
            "download_url": f"{releases}/releases/download/v{release}/{archive.name}",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "platform": "any",
            "architecture": "any",
        }
    ]


def main(argv: list[str]) -> int:
    """Parses the arguments and builds the archive."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where to write it")
    print(build(parser.parse_args(argv).out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
