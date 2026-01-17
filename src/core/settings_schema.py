from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LauncherSettings:
    device_mode: str = "auto"
    offline_quality: str = "High"
    realtime_mode: str = "Balanced"
    version: int = 1
