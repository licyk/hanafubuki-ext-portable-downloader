"""Builds the installable archive: ``python scripts/package.py [--out DIR]``.

The archive holds the package's files at its root (the manifest, the backend,
the settings form, the locales, the built page in ``ui/``, the requirements, the
README) and none of the development files (``web/``, ``tests/``, ``scripts/``,
caches). Build the page first (``npm run build`` in ``web/``).
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ("hanafubuki-extension.toml", "requirements.txt", "README.md")
DIRECTORIES = ("backend", "schemas", "locales", "ui")
SKIPPED = ("__pycache__",)


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


def build(out: Path, root: Path = ROOT) -> Path:
    """Writes ``io.github.licyk.portable-downloader-<version>.zip`` into ``out``."""
    if not (root / "ui" / "index.html").is_file():
        raise SystemExit("ui/index.html is missing: build the page first (npm run build in web/)")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"io.github.licyk.portable-downloader-{version(root)}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for relative in package_files(root):
            zipped.write(root / relative, relative.as_posix())
    return archive


def main(argv: list[str]) -> int:
    """Parses the arguments and builds the archive."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where to write it")
    print(build(parser.parse_args(argv).out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
