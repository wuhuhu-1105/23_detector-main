from __future__ import annotations

import os
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_outputs_root() -> str:
    base_dir = get_base_dir()
    if getattr(sys, "frozen", False):
        return str(base_dir / "outputs")
    return os.path.join(str(base_dir), "outputs")


def get_best_dir() -> str:
    return str(get_base_dir() / "best")
