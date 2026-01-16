from __future__ import annotations

import argparse
import os
from typing import Optional, Tuple

import cv2

_LAST_SOURCE_PATH = ".last_source"


def resolve_source(args: argparse.Namespace) -> str:
    if args.source:
        return args.source
    if args.video:
        return args.video
    if os.path.isfile(_LAST_SOURCE_PATH):
        with open(_LAST_SOURCE_PATH, "r", encoding="utf-8") as f:
            last = f.read().strip()
            if last:
                return last
    raise ValueError("Video source is required (positional video or --source).")


def validate_source(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Video source not found: {path}")
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video (permissions/codec?): {path}")
    finally:
        cap.release()


def write_last_source(path: str) -> None:
    with open(_LAST_SOURCE_PATH, "w", encoding="utf-8") as f:
        f.write(path)


def parse_save_size(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if not value or value.lower() == "keep":
        return None
    sep = "," if "," in value else "x" if "x" in value.lower() else None
    if sep is None:
        raise ValueError("save_size must be in 'w,h' or 'WxH' format")
    parts = value.lower().split(sep)
    if len(parts) != 2:
        raise ValueError("save_size must be in 'w,h' or 'WxH' format")
    return int(parts[0]), int(parts[1])


def derive_time_ms(
    timestamp_ms: float,
    last_time_ms: Optional[float],
    fps_assume: float,
    frame_index: int,
) -> float:
    if last_time_ms is None:
        return timestamp_ms
    if timestamp_ms >= last_time_ms:
        return timestamp_ms
    fallback = (frame_index / max(fps_assume, 1e-3)) * 1000.0
    return max(last_time_ms, fallback)


def should_process_frame(time_ms: float, start_sec: Optional[float], end_sec: Optional[float]) -> bool:
    if start_sec is not None and time_ms < start_sec * 1000.0:
        return False
    if end_sec is not None and time_ms > end_sec * 1000.0:
        return False
    return True
