from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set, Tuple


@dataclass
class StatusDTO:
    state_raw: str
    state_5class: str
    state_cn: str
    color: tuple[int, int, int]
    color_rgb: tuple[int, int, int]
    duration_s: Optional[float]
    video_t_s: Optional[float] = None
    tags_c_set: Optional[Set[str]] = None
    tags_d_set: Optional[Set[str]] = None
    people_count: int = 0
    people_ok: bool = True
    people_alarm: bool = False
    run_state_cn: str = "\u8fd0\u884c\u4e2d"
    frame_index: Optional[int] = None
    fps: Optional[float] = None
    target_ratio: Optional[float] = None

FIVE_STATES: tuple[str, ...] = (
    "CLOSE",
    "OPEN_DANGER",
    "OPEN_VIOLATION",
    "OPEN_NORMAL_SAMPLING",
    "OPEN_NORMAL_IDLE",
)

STATE_CN_MAP: dict[str, str] = {
    "CLOSE": "\u5173\u95ed",
    "OPEN_DANGER": "\u5f00\u542f-\u5371\u9669",
    "OPEN_VIOLATION": "\u5f00\u542f-\u8fdd\u89c4",
    "OPEN_NORMAL_SAMPLING": "\u5f00\u542f-\u6b63\u5e38\u91c7\u6837",
    "OPEN_NORMAL_IDLE": "\u5f00\u542f-\u6b63\u5e38\u7a7a\u95f2",
}

STATE_COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "CLOSE": (180, 180, 180),
    "OPEN_DANGER": (255, 0, 0),
    "OPEN_VIOLATION": (255, 140, 0),
    "OPEN_NORMAL_SAMPLING": (0, 200, 0),
    "OPEN_NORMAL_IDLE": (0, 200, 0),
}


def normalize_state(
    state_raw: Optional[str],
    state_5class: Optional[str],
    reason: Optional[str],
    people_ok: Optional[bool],
    people_count: Optional[int],
    tags_c: Optional[Set[str]],
    tags_d: Optional[Set[str]],
) -> Tuple[str, str]:
    _ = people_ok, people_count, tags_c, tags_d
    state = state_5class or state_raw or ""
    if state in ("N/A", ""):
        return "CLOSE", reason or ""
    if state in FIVE_STATES:
        return state, reason or ""
    if state == "OPEN_UNKNOWN" or state_raw == "OPEN_UNKNOWN":
        if reason and "open_missing_blocking" in reason:
            return "OPEN_DANGER", f"{reason}+missing_blocking"
        return "OPEN_DANGER", f"{reason}+unknown_fallback" if reason else "+unknown_fallback"
    return "OPEN_DANGER", f"{reason}+bad_state" if reason else "+bad_state"


def to_state_cn(state_5class: str) -> str:
    return STATE_CN_MAP.get(state_5class, "\u5f00\u542f-\u672a\u77e5")


def to_state_color_rgb(state_5class: str) -> tuple[int, int, int]:
    return STATE_COLOR_RGB.get(state_5class, (160, 160, 160))
