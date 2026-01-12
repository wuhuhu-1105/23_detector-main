from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

import cv2
import numpy as np

from ..core.config import AppConfig
from ..core.types import PeopleStable, TagsStable


LABEL_VIEW_SPEC: Dict[Tuple[str, str], Dict[str, object]] = {
    ("B", "person"): {"color_bgr": (255, 255, 255), "thickness": 2, "prefix": "B"},
    ("C", "close"): {"color_bgr": (0, 0, 255), "thickness": 3, "prefix": "C"},
    ("C", "sampling"): {"color_bgr": (0, 255, 0), "thickness": 3, "prefix": "C"},
    ("D", "blocking"): {"color_bgr": (0, 170, 255), "thickness": 3, "prefix": "D"},
    ("D", "no_blocking"): {"color_bgr": (255, 255, 0), "thickness": 3, "prefix": "D"},
}


def _state_color(state: str) -> tuple[int, int, int]:
    if state == "OPEN_DANGER":
        return (30, 30, 220)
    if state == "OPEN_VIOLATION":
        return (0, 140, 255)
    if state in ("OPEN_NORMAL_SAMPLING", "OPEN_NORMAL_IDLE"):
        return (0, 200, 0)
    if state == "CLOSE":
        return (180, 180, 180)
    return (160, 160, 160)


def _label_color(label: str) -> tuple[int, int, int]:
    seed = sum(ord(ch) for ch in label) % 180
    return (50 + seed, 200 - seed, 100 + seed // 2)


def _label_view_spec(channel: Optional[str], label: str) -> Dict[str, object]:
    if channel is not None:
        spec = LABEL_VIEW_SPEC.get((channel, label))
        if spec is not None:
            return spec
    return {"color_bgr": _label_color(label), "thickness": 2, "prefix": channel or ""}


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "N/A"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds) // 60
    rem = int(seconds) % 60
    return f"{minutes:02d}:{rem:02d}"


def _draw_box(frame, box, channel: Optional[str] = None) -> None:
    x1, y1, x2, y2 = map(int, box.xyxy)
    spec = _label_view_spec(channel, box.label)
    color = spec["color_bgr"]
    thickness = int(spec["thickness"])
    prefix = str(spec["prefix"]) if spec["prefix"] else (channel or "")
    text_label = f"{prefix}:{box.label}" if prefix else box.label
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    label = f"{text_label} {box.conf:.2f}"
    if box.track_id is not None:
        label = f"{label}#{box.track_id}"
    cv2.putText(frame, label, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)


def _draw_people_panel(
    frame,
    people: PeopleStable,
    y: int,
    padding: int,
    col_value: int,
    expected: int,
    active_ids: Optional[Set[int]],
) -> int:
    cv2.putText(frame, "People", (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
    y += 18
    stable_text = f"Stable: {people.people_count_stable}"
    cv2.putText(frame, stable_text, (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    y += 18
    ok_text = f"OK: {people.people_ok}"
    ok_color = (0, 200, 0) if people.people_ok else (0, 0, 200)
    cv2.putText(frame, ok_text, (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ok_color, 1)
    y += 18
    target_text = f"Target: {expected}"
    cv2.putText(frame, target_text, (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 18
    if active_ids is not None:
        ids_str = ",".join(map(str, sorted(active_ids)))
        cv2.putText(frame, f"IDs: {ids_str}", (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        y += 18
    return y


def _draw_tags_panel(frame, title: str, tags: TagsStable, y: int, padding: int, col_value: int) -> int:
    cv2.putText(frame, title, (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
    y += 18
    tag_text = ", ".join(sorted(tags.tags)) if tags.tags else "(none)"
    cv2.putText(frame, tag_text, (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
    y += 18
    return y


def _draw_state_panel(
    frame,
    state: Optional["StateResult"],
    y: int,
    padding: int,
    col_value: int,
    frame_ms: float,
    fps: float,
    state_age_s: Optional[float],
    current_state: str,
    current_duration_s: Optional[float],
    source_name: str,
) -> int:
    cv2.putText(frame, "State", (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
    y += 18
    current_color = _state_color(current_state)
    cv2.putText(
        frame,
        f"Current State: {current_state}",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        current_color,
        1,
    )
    y += 18
    if state is not None:
        reason_text = f"Reason: {state.reason}"
        cv2.putText(frame, reason_text, (col_value, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 18

    cv2.putText(
        frame,
        f"State Age: {_format_duration(state_age_s)}",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y += 18

    cv2.putText(
        frame,
        f"Duration: {_format_duration(current_duration_s)}",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y += 18

    cv2.putText(
        frame,
        f"Frame: {frame_ms:.1f}ms",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y += 18

    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y += 18

    cv2.putText(
        frame,
        f"Source: {source_name}",
        (col_value, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y += 18
    return y


def _draw_panel(
    frame,
    people: Optional[PeopleStable],
    state: Optional["StateResult"],
    tags_c: Optional[TagsStable],
    tags_d: Optional[TagsStable],
    frame_ms: float,
    fps: float,
    state_age_s: Optional[float],
    current_state: str,
    current_duration_s: Optional[float],
    source_name: str,
    debug_text: str,
    expected_people: int,
) -> None:
    h, w = frame.shape[:2]
    panel_w = 300
    panel_h = 280
    padding = 10
    panel_x = w - panel_w - 10
    panel_y = 10
    cv2.rectangle(frame, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (20, 20, 20), -1)
    col_value = panel_x + padding + 90
    y = panel_y + padding + 12

    if people is not None:
        y = _draw_people_panel(frame, people, y, panel_x + padding, col_value, expected_people, None)
    if tags_c is not None:
        y = _draw_tags_panel(frame, "Tags C", tags_c, y + 6, panel_x + padding, col_value)
    if tags_d is not None:
        y = _draw_tags_panel(frame, "Tags D", tags_d, y + 6, panel_x + padding, col_value)
    y = _draw_state_panel(
        frame,
        state,
        y + 6,
        panel_x + padding,
        col_value,
        frame_ms,
        fps,
        state_age_s,
        current_state,
        current_duration_s,
        source_name,
    )

    if debug_text:
        cv2.putText(
            frame,
            debug_text,
            (10, h - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
        )


def _draw_c_debug_window(
    raw_tags: Optional["TagsRaw"],
    tags: Optional[TagsStable],
    debug: Optional[Dict[str, float]],
    open_flag: bool,
    open_sampling: bool,
    open_idle: bool,
):
    w = 420
    h = 220
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    padding = 12
    y = padding + 10

    cv2.putText(frame, "C Debug", (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    y += 26
    raw_text = f"Raw: {sorted(raw_tags.tags) if raw_tags else []}"
    cv2.putText(frame, raw_text, (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 20
    stable_text = f"Stable: {sorted(tags.tags) if tags else []}"
    cv2.putText(frame, stable_text, (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 20

    if debug:
        cv2.putText(
            frame,
            f"close raw/on/off: {int(debug.get('close_raw', 0))}/{int(debug.get('close_on', 0))}/{int(debug.get('close_off', 0))}",
            (padding, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (160, 200, 255),
            1,
        )
        y += 18
        cv2.putText(
            frame,
            f"sampling raw/on/off: {int(debug.get('sampling_raw', 0))}/{int(debug.get('sampling_on', 0))}/{int(debug.get('sampling_off', 0))}",
            (padding, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (160, 200, 255),
            1,
        )
        y += 18
        cv2.putText(
            frame,
            f"close/sampling conf: {debug.get('close_conf', 0):.2f}/{debug.get('sampling_conf', 0):.2f}",
            (padding, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (160, 200, 255),
            1,
        )
        y += 18

    cv2.putText(
        frame,
        f"State: open={open_flag} sampling={open_sampling} idle={open_idle}",
        (padding, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    return frame


def _draw_d_debug_window(raw_tags: Optional["TagsRaw"], tags: Optional[TagsStable], debug: Dict[str, float]):
    w = 420
    h = 180
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    padding = 12
    y = padding + 10

    cv2.putText(frame, "D Debug", (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    y += 26
    raw_text = f"Raw: {sorted(raw_tags.tags) if raw_tags else []}"
    cv2.putText(frame, raw_text, (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 20
    stable_text = f"Stable: {sorted(tags.tags) if tags else []}"
    cv2.putText(frame, stable_text, (padding, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 20

    cv2.putText(
        frame,
        f"blocking raw/on/off: {int(debug.get('blocking_raw', 0))}/{int(debug.get('blocking_on', 0))}/{int(debug.get('blocking_off', 0))}",
        (padding, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (160, 200, 255),
        1,
    )
    y += 18
    cv2.putText(
        frame,
        f"no_blocking raw/on/off: {int(debug.get('no_blocking_raw', 0))}/{int(debug.get('no_blocking_on', 0))}/{int(debug.get('no_blocking_off', 0))}",
        (padding, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (160, 200, 255),
        1,
    )
    y += 18
    cv2.putText(
        frame,
        f"conf b/nb: {debug.get('blocking_conf', 0):.2f}/{debug.get('no_blocking_conf', 0):.2f}",
        (padding, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (160, 200, 255),
        1,
    )
    return frame


def render_frame(
    frame,
    args,
    cfg: AppConfig,
    people: Optional[PeopleStable],
    state: Optional["StateResult"],
    tags_c: Optional[TagsStable],
    tags_d: Optional[TagsStable],
    raw_people: Optional["PeopleRaw"],
    raw_tags_c: Optional["TagsRaw"],
    raw_tags_d: Optional["TagsRaw"],
    sampling_smoother,
    blocking_smoother,
    people_smoother,
    frame_ms: float,
    fps: float,
    state_age_s: Optional[float],
    current_state: str,
    current_duration_s: Optional[float],
    source_name: str,
) -> bool:
    debug_parts = []
    if args.debug:
        if cfg.enable_b and people_smoother is not None:
            debug_parts.append(f"B {people_smoother.debug_string()}")
        if cfg.enable_c:
            debug_parts.append(f"C {sampling_smoother.debug_string()}")
        if cfg.enable_d:
            d_debug = blocking_smoother.debug_info()
            debug_parts.append(
                "D raw(nb/blk)="
                f"{int(d_debug.get('no_blocking_raw', 0))}/{int(d_debug.get('blocking_raw', 0))} "
                f"on={int(d_debug.get('no_blocking_on', 0))}/{int(d_debug.get('blocking_on', 0))} "
                f"off={int(d_debug.get('no_blocking_off', 0))}/{int(d_debug.get('blocking_off', 0))}"
            )
        if state is not None:
            debug_parts.append(f"E reason={state.reason}")
    debug_text = " | ".join(debug_parts) if debug_parts else ""

    if args.view or args.save_video:
        if args.draw_boxes:
            if raw_people is not None:
                for box in raw_people.boxes:
                    _draw_box(frame, box, "B")
            if raw_tags_c is not None:
                for box in raw_tags_c.boxes:
                    _draw_box(frame, box, "C")
            if raw_tags_d is not None:
                for box in raw_tags_d.boxes:
                    _draw_box(frame, box, "D")

        expected_people = cfg.people_smoother.expected_people
        _draw_panel(
            frame,
            people,
            state,
            tags_c,
            tags_d,
            frame_ms,
            fps,
            state_age_s,
            current_state,
            current_duration_s,
            source_name,
            debug_text,
            expected_people,
        )
        if args.view:
            show_windows = True
        else:
            show_windows = False
    else:
        show_windows = False

    if args.debug:
        if cfg.enable_c:
            open_flag = False
            open_sampling = False
            open_idle = False
            if tags_c is not None:
                open_flag = "close" not in tags_c.tags
                open_sampling = open_flag and "sampling" in tags_c.tags
                open_idle = open_flag and "sampling" not in tags_c.tags

            c_debug = _draw_c_debug_window(
                raw_tags_c,
                tags_c,
                sampling_smoother.debug_info() if cfg.enable_c else None,
                open_flag,
                open_sampling,
                open_idle,
            )
            show_windows = True

        if cfg.enable_d:
            d_debug = _draw_d_debug_window(
                raw_tags_d,
                tags_d,
                blocking_smoother.debug_info(),
            )
            show_windows = True

    if show_windows:
        return False
    return False


def close_windows(args) -> None:
    _ = args
