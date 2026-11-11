"""Which GPU a package is built for, and a best-effort guess at the local ones.

A package's key ends in its PyTorch backend (``comfyui_cuda``, ``sd_webui_forge_neo_xpu``),
as the portable builds name them. Detection never fails: what cannot be read
leaves the compatibility ``unknown``.
"""

from __future__ import annotations

import json
import platform as platform_module
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VENDOR_BY_BACKEND = {"cuda": "nvidia", "rocm": "amd", "xpu": "intel", "mps": "apple"}

# PCI vendor ids under /sys/class/drm/card*/device/vendor.
_PCI_VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}

_WINDOWS_QUERY = (
    "Get-CimInstance Win32_VideoController | "
    "Select-Object Name, AdapterCompatibility | ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class GpuInfo:
    """What detection found: whether it could look at all, and the vendors it saw."""

    detected: bool = False
    vendors: frozenset[str] = frozenset()

    def to_json(self) -> dict[str, Any]:
        """The info as the page reads it."""
        return {"detected": self.detected, "vendors": sorted(self.vendors)}


def package_vendor(key: str) -> str | None:
    """The GPU vendor a package key is built for, from its ``_<backend>`` suffix.

    Args:
        key: The package key (``comfyui_cuda``).

    Returns:
        ``nvidia``, ``amd``, ``intel`` or ``apple``; none for an unknown suffix.
    """
    _, _, backend = key.lower().rpartition("_")
    return VENDOR_BY_BACKEND.get(backend)


def compatibility(vendor: str | None, info: GpuInfo) -> str:
    """Whether a package for ``vendor`` suits this machine.

    Args:
        vendor: The package's vendor (``package_vendor``).
        info: What detection found.

    Returns:
        ``supported``, ``unsupported`` or ``unknown``.
    """
    if vendor is None or not info.detected:
        return "unknown"
    return "supported" if vendor in info.vendors else "unsupported"


def detect(
    host_platform: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    sysfs: Path = Path("/sys/class/drm"),
    machine: Callable[[], str] = platform_module.machine,
) -> GpuInfo:
    """Looks for the local GPUs; never raises.

    Args:
        host_platform: ``linux``, ``macos`` or ``windows`` (``host.info``'s platform).
        which: Finds a program on ``PATH``.
        sysfs: The DRM class directory on Linux.
        machine: The processor architecture.

    Returns:
        What was found.
    """
    try:
        if host_platform == "macos":
            return _detect_macos(machine())
        if host_platform == "windows":
            return _detect_windows(which)
        return _detect_linux(which, sysfs)
    except Exception:  # noqa: BLE001 - a hint only: anything unexpected is "unknown"
        return GpuInfo()


def vendors_from_windows_adapters(adapters: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """The vendors among ``Win32_VideoController`` rows, by the original downloader's rules.

    Args:
        adapters: Rows with ``Name`` and ``AdapterCompatibility``.

    Returns:
        The vendors whose compute GPUs are present.
    """
    vendors: set[str] = set()
    for adapter in adapters:
        name = str(adapter.get("Name") or "")
        vendor = str(adapter.get("AdapterCompatibility") or "")
        if not name.strip():
            continue
        if "NVIDIA" in vendor and name.startswith(("NVIDIA", "GeForce", "Tesla", "Quadro")):
            vendors.add("nvidia")
        if _is_amd_gpu(name, vendor):
            vendors.add("amd")
        if "Intel" in vendor and name.startswith(("Intel(R) Arc", "Intel(R) Core Ultra")):
            vendors.add("intel")
    return frozenset(vendors)


def _detect_macos(machine: str) -> GpuInfo:
    return GpuInfo(True, frozenset({"apple"}) if machine == "arm64" else frozenset())


def _detect_linux(which: Callable[[str], str | None], sysfs: Path) -> GpuInfo:
    vendors: set[str] = set()
    detected = False
    if sysfs.is_dir():
        detected = True
        for card in sysfs.glob("card*/device/vendor"):
            try:
                vendor = _PCI_VENDORS.get(card.read_text(encoding="ascii").strip().lower())
            except OSError:
                continue
            if vendor:
                vendors.add(vendor)
    if which("nvidia-smi"):
        detected = True
        vendors.add("nvidia")
    if which("rocminfo") or which("rocm-smi"):
        detected = True
        vendors.add("amd")
    return GpuInfo(detected, frozenset(vendors))


def _detect_windows(which: Callable[[str], str | None]) -> GpuInfo:
    shell = which("powershell") or which("pwsh")
    if shell:
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_QUERY],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0 and completed.stdout.strip():
            rows = json.loads(completed.stdout)
            rows = rows if isinstance(rows, list) else [rows]
            return GpuInfo(
                True, vendors_from_windows_adapters(r for r in rows if isinstance(r, dict))
            )
    if which("nvidia-smi"):
        return GpuInfo(True, frozenset({"nvidia"}))
    return GpuInfo()


def _is_amd_gpu(name: str, vendor: str) -> bool:
    lowered = vendor.lower()
    if not ("advanced micro devices" in lowered or "amd" in lowered or "ati" in lowered):
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return (
        "radeon" in normalized
        or "instinct" in normalized
        or bool(re.search(r"\bmi\d{3}", normalized))
    )
