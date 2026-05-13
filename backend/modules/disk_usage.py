"""Disk usage per mounted filesystem (psutil-backed).

Filters out pseudo / virtual filesystems and small mounts so the widget shows
only what's interesting (real data drives), and skips paths under known
container / package-manager directories to keep the list short.
"""

from __future__ import annotations

import asyncio
from typing import Any

import psutil

from .base import Module, register_module

# Pseudo filesystems that never carry user-visible storage.
SKIP_FSTYPES = {
    "tmpfs", "devtmpfs", "overlay", "overlayfs", "squashfs", "nsfs",
    "cgroup", "cgroup2", "proc", "sysfs", "autofs", "binfmt_misc", "bpf",
    "configfs", "debugfs", "fusectl", "hugetlbfs", "mqueue", "pstore",
    "ramfs", "rpc_pipefs", "securityfs", "selinuxfs", "tracefs",
    "fuse.gvfsd-fuse", "fuse.portal", "fuse.snapshotter",
}

# Mount-path prefixes that almost always carry transient / per-app mounts.
SKIP_MOUNT_PREFIXES = (
    "/snap", "/var/lib/docker", "/var/lib/containers", "/var/lib/flatpak",
    "/run", "/proc", "/sys", "/dev",
)


@register_module
class DiskUsageModule(Module):
    name = "disk_usage"
    default_interval = 30.0  # disk fill rarely shifts second-to-second

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.min_size_gb: float = float(config.get("min_size_gb", 1.0))
        # If set, only these mountpoints are reported; otherwise we apply the
        # generic skip filters above.
        allowlist = config.get("mounts") or []
        self.mountpoint_allowlist: list[str] = [str(m) for m in allowlist]

    async def poll(self) -> dict[str, Any]:
        rows = await asyncio.to_thread(self._collect)
        return {"disks": rows}

    def _collect(self) -> list[dict[str, Any]]:
        if self.mountpoint_allowlist:
            allowed = set(self.mountpoint_allowlist)
            partitions = [
                p for p in psutil.disk_partitions(all=True)
                if p.mountpoint in allowed
            ]
        else:
            partitions = [
                p for p in psutil.disk_partitions(all=False)
                if p.fstype not in SKIP_FSTYPES
                and not any(p.mountpoint.startswith(pfx) for pfx in SKIP_MOUNT_PREFIXES)
            ]

        rows: list[dict[str, Any]] = []
        seen_devices: set[str] = set()
        min_bytes = int(self.min_size_gb * 1024**3)
        for part in partitions:
            # Some mounts (bind mounts, btrfs subvols) report the same device
            # twice with different mountpoints — keep only the first hit.
            if part.device and part.device in seen_devices:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (OSError, PermissionError):
                continue
            if usage.total < min_bytes:
                continue
            seen_devices.add(part.device or part.mountpoint)
            rows.append({
                "mountpoint": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total": int(usage.total),
                "used": int(usage.used),
                "free": int(usage.free),
                "percent": float(usage.percent),
            })

        rows.sort(key=lambda r: r["percent"], reverse=True)
        return rows
