"""Which GPU a package is for, and the best-effort detection of the local ones."""

from __future__ import annotations

from pathlib import Path

import pytest
from portable_downloader.gpu import (
    GpuInfo,
    compatibility,
    detect,
    package_vendor,
    vendors_from_windows_adapters,
)


@pytest.mark.parametrize(
    ("key", "vendor"),
    [
        ("comfyui_cuda", "nvidia"),
        ("sd_webui_forge_neo_rocm", "amd"),
        ("sd_webui_forge_neo_xpu", "intel"),
        ("comfyui_mps", "apple"),
        ("COMFYUI_CUDA", "nvidia"),
        ("comfyui", None),
        ("comfyui_cpu", None),
    ],
)
def test_the_key_suffix_names_the_gpu(key: str, vendor: str | None) -> None:
    assert package_vendor(key) == vendor


def test_compatibility_is_unknown_without_detection_or_vendor() -> None:
    nvidia = GpuInfo(True, frozenset({"nvidia"}))

    assert compatibility("nvidia", nvidia) == "supported"
    assert compatibility("amd", nvidia) == "unsupported"
    assert compatibility(None, nvidia) == "unknown"
    assert compatibility("nvidia", GpuInfo()) == "unknown"


def test_windows_adapters_follow_the_original_rules() -> None:
    adapters = [
        {"Name": "NVIDIA GeForce RTX 4090", "AdapterCompatibility": "NVIDIA"},
        {"Name": "AMD Radeon RX 7900 XTX", "AdapterCompatibility": "Advanced Micro Devices, Inc."},
        {"Name": "Intel(R) UHD Graphics 770", "AdapterCompatibility": "Intel Corporation"},
        {
            "Name": "Microsoft Basic Display Adapter",
            "AdapterCompatibility": "(Standard display types)",
        },
        {"Name": "", "AdapterCompatibility": "NVIDIA"},
    ]

    assert vendors_from_windows_adapters(adapters) == {"nvidia", "amd"}
    assert vendors_from_windows_adapters(
        [{"Name": "Intel(R) Arc(TM) A770 Graphics", "AdapterCompatibility": "Intel Corporation"}]
    ) == {"intel"}


def _card(sysfs: Path, name: str, vendor: str) -> None:
    device = sysfs / name / "device"
    device.mkdir(parents=True)
    (device / "vendor").write_text(f"{vendor}\n", encoding="ascii")


def test_linux_reads_pci_vendors_and_tools(tmp_path: Path) -> None:
    sysfs = tmp_path / "drm"
    _card(sysfs, "card0", "0x10de")
    _card(sysfs, "card1", "0x8086")

    found = detect("linux", which=lambda name: None, sysfs=sysfs)
    assert found == GpuInfo(True, frozenset({"nvidia", "intel"}))

    tools = detect("linux", which=lambda name: f"/usr/bin/{name}", sysfs=tmp_path / "none")
    assert tools.vendors == {"nvidia", "amd"}
    assert detect("linux", which=lambda name: None, sysfs=tmp_path / "none") == GpuInfo()


def test_macos_is_apple_silicon_on_arm64_only() -> None:
    assert detect("macos", machine=lambda: "arm64").vendors == {"apple"}
    assert detect("macos", machine=lambda: "x86_64") == GpuInfo(True, frozenset())


def test_detection_never_fails() -> None:
    def broken(name: str) -> str | None:
        raise PermissionError(name)

    assert detect("linux", which=broken) == GpuInfo()
    assert detect("windows", which=broken) == GpuInfo()
