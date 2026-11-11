"""The extension's settings, read from what ``settings.get`` answers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SOURCES = ("modelscope", "huggingface")
CHANNELS = ("nightly", "stable")
TOOLS = ("aria2", "requests")


@dataclass(frozen=True)
class Settings:
    """The values the backend works with; unset fields are left out, so the defaults live here."""

    source: str = "modelscope"
    channel: str = "nightly"
    download_tool: str = "aria2"
    auto_extract: bool = True
    delete_archive: bool = False
    default_folder: str = ""

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> Settings:
        """Reads the stored values, keeping the default for a value that does not fit.

        Args:
            values: ``settings.get``'s ``values`` (or a ``settings`` event's).

        Returns:
            The settings.
        """
        defaults = cls()
        folder = values.get("defaultFolder")
        return cls(
            source=_choice(values.get("source"), SOURCES, defaults.source),
            channel=_choice(values.get("channel"), CHANNELS, defaults.channel),
            download_tool=_choice(values.get("downloadTool"), TOOLS, defaults.download_tool),
            auto_extract=_flag(values.get("autoExtract"), defaults.auto_extract),
            delete_archive=_flag(values.get("deleteArchive"), defaults.delete_archive),
            default_folder=folder if isinstance(folder, str) else "",
        )

    def to_json(self, instances_dir: str | None) -> dict[str, Any]:
        """The settings as the page reads them.

        Args:
            instances_dir: The application's instances directory, the folder when none is set.

        Returns:
            The JSON object.
        """
        return {
            "source": self.source,
            "channel": self.channel,
            "downloadTool": self.download_tool,
            "autoExtract": self.auto_extract,
            "deleteArchive": self.delete_archive,
            "defaultFolder": self.default_folder.strip() or instances_dir or "",
        }


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _flag(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default
