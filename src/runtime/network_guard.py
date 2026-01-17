from __future__ import annotations

import os
from typing import List

from src.core.config import AppConfig


def _model_paths(cfg: AppConfig) -> List[str]:
    return [
        cfg.people_detector.model_path,
        cfg.sampling_close.model_path,
        cfg.blocking_detector.model_path,
    ]


def enforce_no_network(cfg: AppConfig, allow_network: bool) -> None:
    if allow_network:
        return
    missing = [p for p in _model_paths(cfg) if not os.path.exists(p)]
    if missing:
        joined = "\n".join(missing)
        raise FileNotFoundError(
            "Model weights not found and network download is disabled:\n" + joined
        )
