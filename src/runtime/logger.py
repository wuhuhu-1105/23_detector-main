from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

_LOGGER_NAME = "detector"
_ORDER = [
    "event",
    "frame",
    "step",
    "capped",
    "next_idx",
    "dropped",
    "t_read_ms",
    "t_drop_ms",
    "t_infer_ms",
    "t_emit_ms",
    "fps_est",
    "dt_ms",
    "dt_smooth_ms",
    "throughput_fps",
    "video_fps",
    "raw_step",
    "raw_step_smooth",
    "target_ratio",
    "ratio",
]


def setup_logging(level: str = "INFO") -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return
    numeric_level = logging.getLevelName(level.upper())
    logger.setLevel(numeric_level if isinstance(numeric_level, int) else logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _ordered_items(fields: Dict[str, Any], order: Iterable[str]) -> Iterable[tuple[str, Any]]:
    seen = set()
    for key in order:
        if key in fields:
            seen.add(key)
            yield key, fields[key]
    for key in sorted(fields.keys()):
        if key not in seen:
            yield key, fields[key]


def log_kv(event: str, *, logger: Optional[logging.Logger] = None, **fields: Any) -> None:
    payload = {"event": event, **fields}
    parts = [f"{k}={_format_value(v)}" for k, v in _ordered_items(payload, _ORDER)]
    (logger or get_logger()).info(" ".join(parts))


def log_perf(*, logger: Optional[logging.Logger] = None, **fields: Any) -> None:
    log_kv("PERF", logger=logger, **fields)
