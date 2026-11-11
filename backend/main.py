"""Entry point of the portable downloader's backend, run by Hanafubuki on its managed Python."""

from __future__ import annotations

import os
import sys


def _protocol_stream():
    """Keeps file descriptor 1 for the protocol and points everything else at stderr.

    The SDK only rebinds ``sys.stdout``; a logging handler made at import time or a
    child process (aria2c) writing to descriptor 1 would break a frame. So the
    protocol gets a duplicate of descriptor 1, and descriptor 1 becomes stderr's.
    """
    protocol = os.fdopen(os.dup(1), "wb")
    sys.stdout.flush()
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return protocol


def main() -> None:
    """Runs the backend until the application stops it."""
    protocol = _protocol_stream()

    from hanafubuki_extension import run
    from portable_downloader.app import Backend
    from portable_downloader.catalog import LIST_URLS

    # For development and tests only: the application starts the backend in a clean
    # environment, so this never reaches an installed extension.
    override = os.environ.get("PORTABLE_DOWNLOADER_LIST_URLS", "")
    urls = [url for url in override.split(",") if url] or list(LIST_URLS)
    run(Backend(list_urls=urls), sys.stdin.buffer, protocol)


if __name__ == "__main__":
    main()
