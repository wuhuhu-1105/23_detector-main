from __future__ import annotations

from typing import Optional, Set, Tuple

FIVE_STATES: tuple[str, ...] = (
    "CLOSE",
    "OPEN_DANGER",
    "OPEN_VIOLATION",
    "OPEN_NORMAL_SAMPLING",
    "OPEN_NORMAL_IDLE",
)

STATE_CN_MAP: dict[str, str] = {
    "CLOSE": "关闭",
    "OPEN_DANGER": "开启-危险",
    "OPEN_VIOLATION": "开启-违规",
    "OPEN_NORMAL_SAMPLING": "开启-正常采样",
    "OPEN_NORMAL_IDLE": "开启-正常空闲",
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
    return STATE_CN_MAP.get(state_5class, "开启-未知")
