from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, Tuple

from src.core.paths import get_outputs_root


@dataclass
class LauncherSettings:
    device_mode: str = "auto"
    offline_quality: str = "High"
    realtime_mode: str = "Balanced"


def _settings_path(outputs_root: Optional[str] = None) -> str:
    root = outputs_root or get_outputs_root()
    return os.path.join(root, "launcher_settings.json")


def load_settings(outputs_root: Optional[str] = None) -> LauncherSettings:
    settings, _ = load_settings_with_meta(outputs_root)
    return settings


def load_settings_with_meta(outputs_root: Optional[str] = None) -> Tuple[LauncherSettings, bool]:
    path = _settings_path(outputs_root)
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return LauncherSettings(), False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        settings = LauncherSettings(
            device_mode=str(data.get("device_mode", "auto")),
            offline_quality=str(data.get("offline_quality", "High")),
            realtime_mode=str(data.get("realtime_mode", "Balanced")),
        )
        downgraded = False
        if settings.offline_quality.lower() == "ultra":
            settings.offline_quality = "High"
            downgraded = True
        return settings, downgraded
    except Exception:
        return LauncherSettings(), False


def save_settings(settings: LauncherSettings, outputs_root: Optional[str] = None) -> str:
    path = _settings_path(outputs_root)
    tmp_path = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path
