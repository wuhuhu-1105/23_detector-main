from __future__ import annotations

from datetime import timedelta


def format_ts(ts_s: float) -> str:
    if ts_s is None:
        return "-"
    total_sec = int(round(ts_s))
    if total_sec < 0:
        total_sec = 0
    sec = total_sec % 60
    total_min = total_sec // 60
    minute = total_min % 60
    hour = total_min // 60
    return f"{hour:02d}:{minute:02d}:{sec:02d}"


def parse_hhmmss(value: str) -> float:
    if not value:
        return 0.0
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Time must be HH:MM:SS.mmm")
    hour = int(parts[0])
    minute = int(parts[1])
    sec_parts = parts[2].split(".")
    sec = int(sec_parts[0])
    ms = int(sec_parts[1]) if len(sec_parts) > 1 else 0
    delta = timedelta(hours=hour, minutes=minute, seconds=sec, milliseconds=ms)
    return delta.total_seconds()
