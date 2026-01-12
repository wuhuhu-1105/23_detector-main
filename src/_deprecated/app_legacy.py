from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

from src.core.config import AppConfig, OffMode
from src.core.types import FrameOutput, PeopleStable, TagsStable
from src.detectors.blocking_raw import BlockingRaw
from src.detectors.people_tracker_raw import PeopleTrackerRaw
from src.detectors.sampling_close_raw import SamplingCloseRaw
from src.engine.state_engine_5 import StateEngine5
from src.filters.blocking_smoother import BlockingSmoother
from src.filters.people_smoother import PeopleSmoother
from src.filters.sampling_close_smoother import SamplingCloseSmoother
from src.io.video_source import VideoSource
from src.io.video_writer import VideoWriterManager
from src._deprecated.ui.render import render_frame, close_windows

_LAST_SOURCE_PATH = ".last_source"


def _off_people(cfg: AppConfig, last: Optional[PeopleStable]) -> PeopleStable:
    if cfg.off_mode_b == OffMode.EMPTY:
        return PeopleStable(people_count_stable=0, people_ok=False)
    if cfg.off_mode_b == OffMode.HOLD_LAST and last is not None:
        return last
    if cfg.off_mode_b == OffMode.INJECT:
        return PeopleStable(
            people_count_stable=cfg.inject_people_count,
            people_ok=cfg.inject_people_count == cfg.people_smoother.expected_people,
        )
    return PeopleStable(people_count_stable=0, people_ok=False)


def _off_tags(cfg: AppConfig, last: Optional[TagsStable], inject: Set[str], off_mode: OffMode) -> TagsStable:
    if off_mode == OffMode.EMPTY:
        return TagsStable(tags=set())
    if off_mode == OffMode.HOLD_LAST and last is not None:
        return last
    if off_mode == OffMode.INJECT:
        return TagsStable(tags=set(inject))
    return TagsStable(tags=set())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?", help="Path to input video")
    parser.add_argument("--source", help="Video source path (test mode)")
    parser.add_argument("--view", action="store_true", help="Show real-time visualization")
    parser.add_argument("--debug", action="store_true", help="Show debug info")
    parser.add_argument("--test", action="store_true", help="Enable test mode logging")
    parser.add_argument("--start-sec", type=float, default=None)
    parser.add_argument("--end-sec", type=float, default=None)
    parser.add_argument("--out", default="out")
    parser.add_argument("--no-view", action="store_true", help="Disable any windows in test mode")
    parser.add_argument("--fps-assume", type=float, default=25.0)
    parser.add_argument("--save-video", help="Save demo video to path")
    parser.add_argument("--save-fps", type=float, default=None)
    parser.add_argument("--save-size", default=None)
    parser.add_argument("--draw-boxes", dest="draw_boxes", action="store_true", help="Draw detection boxes")
    parser.add_argument("--no-draw-boxes", dest="draw_boxes", action="store_false", help="Disable detection boxes")
    parser.set_defaults(draw_boxes=True)
    parser.add_argument("--enable-b", dest="enable_b", action="store_true")
    parser.add_argument("--disable-b", dest="enable_b", action="store_false")
    parser.add_argument("--enable-c", dest="enable_c", action="store_true")
    parser.add_argument("--disable-c", dest="enable_c", action="store_false")
    parser.add_argument("--enable-d", dest="enable_d", action="store_true")
    parser.add_argument("--disable-d", dest="enable_d", action="store_false")
    parser.add_argument("--enable-e", dest="enable_e", action="store_true")
    parser.add_argument("--disable-e", dest="enable_e", action="store_false")
    parser.add_argument("--off-mode-b", choices=[m.value for m in OffMode])
    parser.add_argument("--off-mode-c", choices=[m.value for m in OffMode])
    parser.add_argument("--off-mode-d", choices=[m.value for m in OffMode])
    parser.add_argument("--inject-people-count", type=int)
    parser.add_argument("--inject-tags-c", default="")
    parser.add_argument("--inject-tags-d", default="")
    parser.add_argument("--c-imgsz", type=int)
    parser.add_argument("--c-iou", type=float)
    parser.add_argument("--c-conf-close", type=float)
    parser.add_argument("--c-conf-sampling", type=float)
    parser.add_argument("--c-max-det", type=int)
    parser.set_defaults(enable_b=None, enable_c=None, enable_d=None, enable_e=None)
    return parser.parse_args()


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


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
    if label == "person":
        return (255, 255, 255)
    if label == "sampling":
        return (0, 255, 0)
    if label == "close":
        return (0, 0, 255)
    if label == "blocking":
        return (0, 170, 255)
    if label == "no_blocking":
        return (255, 255, 0)
    seed = sum(ord(ch) for ch in label) % 180
    return (50 + seed, 200 - seed, 100 + seed // 2)


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "N/A"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds) // 60
    rem = int(seconds) % 60
    return f"{minutes:02d}:{rem:02d}"


def _resolve_source(args: argparse.Namespace) -> str:
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


def _validate_source(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Video source not found: {path}")
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video (permissions/codec?): {path}")
    finally:
        cap.release()


def _write_last_source(path: str) -> None:
    with open(_LAST_SOURCE_PATH, "w", encoding="utf-8") as f:
        f.write(path)


def _parse_save_size(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError("save_size must be in 'w,h' format")
    return int(parts[0]), int(parts[1])


def _open_writer(path: str, fps: float, size: Tuple[int, int]) -> Tuple[cv2.VideoWriter, str]:
    fourcc_candidates = ["avc1", "H264", "mp4v"]
    for code in fourcc_candidates:
        fourcc = cv2.VideoWriter_fourcc(*code)
        writer = cv2.VideoWriter(path, fourcc, fps, size)
        if writer.isOpened():
            return writer, code
    raise RuntimeError("Failed to open VideoWriter with H264 or mp4v")


def _derive_time_ms(timestamp_ms: float, last_time_ms: Optional[float], fps_assume: float, frame_index: int) -> float:
    if last_time_ms is None:
        return timestamp_ms
    if timestamp_ms >= last_time_ms:
        return timestamp_ms
    fallback = (frame_index / max(fps_assume, 1e-3)) * 1000.0
    return max(last_time_ms, fallback)


def _should_process_frame(time_ms: float, start_sec: Optional[float], end_sec: Optional[float]) -> bool:
    if start_sec is not None and time_ms < start_sec * 1000.0:
        return False
    if end_sec is not None and time_ms > end_sec * 1000.0:
        return False
    return True


def _finalize_summary(
    segments: List[Tuple[str, float, float]],
    transitions: List[Tuple[str, str, float]],
    short_jitter_s: float,
    close_open_warn: int,
    close_open_fail: int,
    short_jitter_warn: int,
    short_jitter_fail: int,
    max_transitions_per_sec: int,
) -> Dict[str, Any]:
    state_counts = Counter()
    state_durations_ms = defaultdict(float)
    for state, start_ms, end_ms in segments:
        state_counts[state] += 1
        state_durations_ms[state] += max(0.0, end_ms - start_ms)

    transition_pairs = Counter()
    close_open_switches = 0
    for prev_state, next_state, _ in transitions:
        transition_pairs[(prev_state, next_state)] += 1
        if (prev_state == "CLOSE") != (next_state == "CLOSE"):
            close_open_switches += 1

    short_jitter_count = sum(1 for state, start_ms, end_ms in segments if (end_ms - start_ms) / 1000.0 < short_jitter_s)

    per_sec_switches = Counter()
    for _, _, t_ms in transitions:
        per_sec_switches[int(t_ms // 1000)] += 1
    max_switches_per_sec = max(per_sec_switches.values()) if per_sec_switches else 0

    status = "PASS"
    if short_jitter_count > short_jitter_fail or close_open_switches > close_open_fail or max_switches_per_sec > max_transitions_per_sec:
        status = "FAIL"
    elif short_jitter_count > short_jitter_warn or close_open_switches > close_open_warn:
        status = "WARN"

    top_pairs = [
        {"from": k[0], "to": k[1], "count": v}
        for k, v in transition_pairs.most_common(5)
    ]

    anomalies = []
    for state, start_ms, end_ms in segments:
        if (end_ms - start_ms) / 1000.0 < short_jitter_s:
            anomalies.append({"start_ms": start_ms, "end_ms": end_ms, "reason": "short_state"})
    if max_switches_per_sec > max_transitions_per_sec:
        for sec, count in per_sec_switches.items():
            if count > max_transitions_per_sec:
                anomalies.append(
                    {
                        "start_ms": sec * 1000,
                        "end_ms": (sec + 1) * 1000,
                        "reason": "high_switch_rate",
                    }
                )

    return {
        "state_entries": dict(state_counts),
        "state_durations_ms": dict(state_durations_ms),
        "transition_count": sum(transition_pairs.values()),
        "top_transitions": top_pairs,
        "short_jitter_count": short_jitter_count,
        "close_open_switches": close_open_switches,
        "max_switches_per_sec": max_switches_per_sec,
        "status": status,
        "anomalies": anomalies[:10],
    }


def _print_test_report(
    source: str,
    total_frames: int,
    duration_ms: float,
    summary: Dict[str, Any],
    state_durations_ms: Dict[str, float],
    short_jitter_s: float,
) -> None:
    durations_sorted = sorted(state_durations_ms.items(), key=lambda kv: kv[1], reverse=True)
    top3 = ", ".join([f"{k} {v/1000.0:.1f}s" for k, v in durations_sorted[:3]])
    print("TEST REPORT")
    print(f"Source: {source}")
    print(f"Frames: {total_frames} Duration: {duration_ms/1000.0:.1f}s")
    print(f"Transitions: {summary.get('transition_count', 0)}")
    print(f"Top states: {top3}")
    print(f"Short jitter (<{short_jitter_s:.1f}s): {summary.get('short_jitter_count', 0)}")
    print(f"Result: {summary.get('status', 'N/A')}")


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
    debug_text: Optional[str],
) -> None:
    h, w = frame.shape[:2]
    panel_x = 24
    panel_y = 24
    panel_w = max(320, min(520, w - 48))
    padding = 16
    line_h = 24

    title = "VIBE AI Monitor"
    date_text = time.strftime("%Y-%m-%d")
    source_text = f"Source: {source_name}"

    row_h = 26
    table_rows = 5
    header_h = line_h * 5 + 8
    table_h = line_h + row_h * table_rows + 8
    summary_lines = 3
    debug_lines = 2 if debug_text else 1
    summary_h = line_h * summary_lines + 8 + line_h * debug_lines
    panel_h = header_h + table_h + summary_h + padding * 2

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (panel_x, panel_y),
        (panel_x + panel_w, panel_y + panel_h),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

    cursor_y = panel_y + padding + line_h
    cv2.putText(frame, title, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2)
    cursor_y += line_h
    cv2.putText(frame, f"Date: {date_text}", (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    cursor_y += line_h - 6
    cv2.putText(frame, source_text, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

    cursor_y += 10
    current_color = _state_color(current_state)
    cv2.putText(
        frame,
        f"Current State: {current_state}",
        (panel_x + padding, cursor_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        current_color,
        2,
    )
    cursor_y += line_h
    cv2.putText(
        frame,
        f"Duration: {_format_duration(current_duration_s)}",
        (panel_x + padding, cursor_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )

    cursor_y += 14
    cv2.line(frame, (panel_x + padding, cursor_y), (panel_x + panel_w - padding, cursor_y), (60, 60, 60), 1)
    cursor_y += line_h

    col_no = panel_x + padding
    col_state = panel_x + padding + 50
    col_status = panel_x + panel_w - padding - 170
    col_ms = panel_x + panel_w - padding - 60
    cv2.putText(frame, "No", (col_no, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
    cv2.putText(frame, "State", (col_state, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
    cv2.putText(frame, "Status", (col_status, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
    cv2.putText(frame, "ms", (col_ms, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
    cursor_y += 10

    state_order = [
        "CLOSE",
        "OPEN_DANGER",
        "OPEN_VIOLATION",
        "OPEN_NORMAL_SAMPLING",
        "OPEN_NORMAL_IDLE",
    ]
    state_names = {
        "CLOSE": "Close",
        "OPEN_DANGER": "Open Danger",
        "OPEN_VIOLATION": "Open Violation",
        "OPEN_NORMAL_SAMPLING": "Open Normal Sampling",
        "OPEN_NORMAL_IDLE": "Open Normal Idle",
    }
    active_state = state.state_5class if state is not None else ""

    for idx, key in enumerate(state_order, start=1):
        row_y = cursor_y + row_h * idx
        if key == active_state:
            row_overlay = frame.copy()
            cv2.rectangle(
                row_overlay,
                (panel_x + padding, row_y - row_h + 6),
                (panel_x + panel_w - padding, row_y + 6),
                (255, 255, 255),
                -1,
            )
            cv2.addWeighted(row_overlay, 0.12, frame, 0.88, 0, frame)
            cv2.rectangle(
                frame,
                (panel_x + padding - 6, row_y - row_h + 6),
                (panel_x + padding - 2, row_y + 6),
                _state_color(key),
                -1,
            )

        text_color = _state_color(key)
        status_text = "ACTIVE" if key == active_state else "idle"
        status_color = text_color if key == active_state else (140, 140, 140)
        ms_text = f"{frame_ms:.1f}" if key == active_state else "-"

        cv2.putText(frame, str(idx), (col_no, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 210, 210), 1)
        if key == active_state:
            cv2.putText(frame, ">", (col_state - 14, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
        cv2.putText(frame, state_names[key], (col_state, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, text_color, 1)
        cv2.putText(frame, status_text, (col_status, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, status_color, 1)
        cv2.putText(frame, ms_text, (col_ms, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

    cursor_y += row_h * table_rows + 10
    cv2.line(frame, (panel_x + padding, cursor_y), (panel_x + panel_w - padding, cursor_y), (60, 60, 60), 1)
    cursor_y += line_h

    people_text = "People: N/A"
    people_color = (200, 200, 200)
    if people is not None:
        people_text = f"People: {people.people_count_stable}"
        people_color = (0, 200, 0) if people.people_ok else (30, 30, 220)
        people_text += "  OK" if people.people_ok else "  ALERT"
    cv2.putText(frame, people_text, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, people_color, 2)
    cursor_y += line_h

    perf_text = f"Perf: {frame_ms:.1f}ms / {fps:.1f}fps"
    cv2.putText(frame, perf_text, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)
    cursor_y += line_h

    reason_text = "Reason: N/A"
    if state is not None:
        reason_text = f"Reason: {state.reason}"
    cv2.putText(frame, reason_text, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (190, 190, 190), 1)
    cursor_y += line_h

    tags_c_text = f"tags_c: {sorted(tags_c.tags) if tags_c else []}"
    tags_d_text = f"tags_d: {sorted(tags_d.tags) if tags_d else []}"
    cv2.putText(frame, f"{tags_c_text} | {tags_d_text}", (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1)
    cursor_y += line_h
    if debug_text:
        cv2.putText(frame, debug_text, (panel_x + padding, cursor_y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1)

    if w - 80 > 0:
        status_color = (0, 200, 0)
        cv2.circle(frame, (w - 40, 40), 7, status_color, -1)
        cv2.putText(frame, "RUNNING", (w - 140, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)


def _draw_boxes(frame, boxes) -> None:
    for box in boxes:
        x1, y1, x2, y2 = [int(v) for v in box.xyxy]
        color = _label_color(box.label)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{box.label} {box.conf:.2f}"
        if box.track_id is not None:
            label += f" id:{box.track_id}"
        cv2.putText(frame, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def _draw_c_debug_window(
    tags_raw,
    tags_stable,
    debug_info: Optional[Dict[str, float]],
    open_flag: bool,
    open_sampling: bool,
    open_idle: bool,
) -> "np.ndarray":
    img = np.zeros((260, 520, 3), dtype=np.uint8)
    y = 26
    line = 22
    text_color = (220, 220, 220)
    subtle = (170, 170, 170)

    raw_tags = sorted(tags_raw.tags) if tags_raw else []
    stable_tags = sorted(tags_stable.tags) if tags_stable else []
    close_raw = "close" in raw_tags
    sampling_raw = "sampling" in raw_tags
    close_conf = tags_raw.conf_by_tag.get("close", 0.0) if tags_raw else 0.0
    sampling_conf = tags_raw.conf_by_tag.get("sampling", 0.0) if tags_raw else 0.0

    cv2.putText(img, "C Debug (sampling/close)", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    y += line
    cv2.putText(
        img,
        f"open_flag={int(open_flag)} open_sampling={int(open_sampling)} open_idle={int(open_idle)}",
        (12, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        text_color,
        1,
    )
    y += line
    cv2.putText(img, f"tags_raw={raw_tags}", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, subtle, 1)
    y += line
    cv2.putText(img, f"tags_stable={stable_tags}", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, subtle, 1)
    y += line
    cv2.putText(
        img,
        f"close_raw_present={int(close_raw)} sampling_raw_present={int(sampling_raw)}",
        (12, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        text_color,
        1,
    )
    y += line
    if debug_info:
        cv2.putText(
            img,
            f"close_on={int(debug_info.get('close_on', 0))} close_off={int(debug_info.get('close_off', 0))}",
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            text_color,
            1,
        )
        y += line
        cv2.putText(
            img,
            f"sampling_on={int(debug_info.get('sampling_on', 0))} sampling_off={int(debug_info.get('sampling_off', 0))}",
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            text_color,
            1,
        )
        y += line
    cv2.putText(
        img,
        f"close_conf_max={close_conf:.2f} sampling_conf_max={sampling_conf:.2f}",
        (12, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        text_color,
        1,
    )
    return img


def _draw_d_debug_window(
    tags_raw,
    tags_stable,
    debug_info: Optional[Dict[str, float]],
) -> "np.ndarray":
    img = np.zeros((240, 520, 3), dtype=np.uint8)
    y = 26
    line = 22
    text_color = (220, 220, 220)
    subtle = (170, 170, 170)

    raw_tags = sorted(tags_raw.tags) if tags_raw else []
    stable_tags = sorted(tags_stable.tags) if tags_stable else []
    blocking_raw = "blocking" in raw_tags
    no_blocking_raw = "no_blocking" in raw_tags
    blocking_conf = tags_raw.conf_by_tag.get("blocking", 0.0) if tags_raw else 0.0
    no_blocking_conf = tags_raw.conf_by_tag.get("no_blocking", 0.0) if tags_raw else 0.0

    cv2.putText(img, "D Debug (blocking/no_blocking)", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    y += line
    cv2.putText(img, "conflict_priority=no_blocking", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)
    y += line
    cv2.putText(img, f"tags_raw={raw_tags}", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, subtle, 1)
    y += line
    cv2.putText(img, f"tags_stable={stable_tags}", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, subtle, 1)
    y += line
    cv2.putText(
        img,
        f"blocking_raw_present={int(blocking_raw)} no_blocking_raw_present={int(no_blocking_raw)}",
        (12, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        text_color,
        1,
    )
    y += line
    if debug_info:
        cv2.putText(
            img,
            f"blk_on={int(debug_info.get('blocking_on', 0))} blk_off={int(debug_info.get('blocking_off', 0))}",
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            text_color,
            1,
        )
        y += line
        cv2.putText(
            img,
            f"nb_on={int(debug_info.get('no_blocking_on', 0))} nb_off={int(debug_info.get('no_blocking_off', 0))}",
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            text_color,
            1,
        )
        y += line
    cv2.putText(
        img,
        f"blocking_conf_max={blocking_conf:.2f} no_blocking_conf_max={no_blocking_conf:.2f}",
        (12, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        text_color,
        1,
    )
    return img


def _render_ui_debug(
    *,
    frame,
    args: argparse.Namespace,
    cfg: AppConfig,
    people: Optional[PeopleStable],
    state: Optional["StateResult"],
    tags_c: Optional[TagsStable],
    tags_d: Optional[TagsStable],
    raw_people,
    raw_tags_c,
    raw_tags_d,
    sampling_smoother: SamplingCloseSmoother,
    blocking_smoother: BlockingSmoother,
    people_smoother: Optional[PeopleSmoother],
    frame_ms: float,
    fps: float,
    state_age_s: Optional[float],
    current_state: str,
    current_duration_s: Optional[float],
    source_name: str,
) -> bool:
    show_windows = False
    if args.view or args.save_video:
        if args.draw_boxes:
            if raw_people is not None:
                _draw_boxes(frame, raw_people.boxes)
            if raw_tags_c is not None:
                _draw_boxes(frame, raw_tags_c.boxes)
            if raw_tags_d is not None:
                _draw_boxes(frame, raw_tags_d.boxes)

        debug_text = None
        if args.debug:
            debug_parts = []
            if cfg.enable_b:
                if people_smoother is not None:
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
            debug_text = " | ".join(debug_parts) if debug_parts else None

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
        )
        if args.view:
            show_windows = True

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


def main() -> None:
    args = parse_args()
    source = _resolve_source(args)
    if args.no_view:
        args.view = False
    cfg = AppConfig()
    if args.enable_b is not None:
        cfg.enable_b = args.enable_b
    if args.enable_c is not None:
        cfg.enable_c = args.enable_c
    if args.enable_d is not None:
        cfg.enable_d = args.enable_d
    if args.enable_e is not None:
        cfg.enable_e = args.enable_e

    if args.off_mode_b:
        cfg.off_mode_b = OffMode(args.off_mode_b)
    if args.off_mode_c:
        cfg.off_mode_c = OffMode(args.off_mode_c)
    if args.off_mode_d:
        cfg.off_mode_d = OffMode(args.off_mode_d)

    if args.inject_people_count is not None:
        cfg.inject_people_count = args.inject_people_count
    if args.inject_tags_c:
        cfg.inject_tags_c = {t.strip() for t in args.inject_tags_c.split(",") if t.strip()}
    if args.inject_tags_d:
        cfg.inject_tags_d = {t.strip() for t in args.inject_tags_d.split(",") if t.strip()}

    if args.c_imgsz is not None:
        cfg.sampling_close.imgsz = args.c_imgsz
    if args.c_iou is not None:
        cfg.sampling_close.iou = args.c_iou
    if args.c_conf_close is not None:
        cfg.sampling_close.conf_close = args.c_conf_close
    if args.c_conf_sampling is not None:
        cfg.sampling_close.conf_sampling = args.c_conf_sampling
    if args.c_max_det is not None:
        cfg.sampling_close.max_det = args.c_max_det

    if cfg.off_mode_b == OffMode.REPLAY or cfg.off_mode_c == OffMode.REPLAY or cfg.off_mode_d == OffMode.REPLAY:
        raise NotImplementedError("REPLAY is not enabled yet.")

    _validate_source(source)
    _write_last_source(source)

    cap_meta = None
    source_fps = None
    source_size = None
    if args.save_video or args.view:
        cap_meta = cv2.VideoCapture(source)
        if cap_meta.isOpened():
            fps_val = cap_meta.get(cv2.CAP_PROP_FPS)
            width = int(cap_meta.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap_meta.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if fps_val and fps_val > 0:
                source_fps = float(fps_val)
            if width > 0 and height > 0:
                source_size = (width, height)
        if cap_meta is not None:
            cap_meta.release()

    save_size = _parse_save_size(args.save_size)
    writer_mgr = VideoWriterManager(
        args.save_video,
        args.save_fps,
        save_size,
        args.fps_assume,
        source_fps,
        source_size,
    )

    people_detector = PeopleTrackerRaw(cfg.people_detector) if cfg.enable_b else None
    sampling_detector = SamplingCloseRaw(cfg.sampling_close)
    blocking_detector = BlockingRaw(cfg.blocking_detector)

    people_smoother = PeopleSmoother(cfg.people_smoother) if cfg.enable_b else None
    sampling_smoother = SamplingCloseSmoother(cfg.tags_c_smoother)
    blocking_smoother = BlockingSmoother(cfg.tags_d_smoother)

    engine = StateEngine5(cfg.state_engine)

    last_people: Optional[PeopleStable] = None
    last_tags_c: Optional[TagsStable] = None
    last_tags_d: Optional[TagsStable] = None

    last_state: Optional[str] = None
    state_start_video_t: Optional[float] = None
    last_timestamp_ms: Optional[float] = None
    last_state_duration_s: Optional[float] = None
    last_tick = time.perf_counter()
    fps_ema: Optional[float] = None
    source_name = os.path.basename(source)
    log_file = None
    summary_path = None
    if args.test:
        os.makedirs(args.out, exist_ok=True)
        run_stamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(args.out, f"run_{run_stamp}.jsonl")
        summary_path = os.path.join(args.out, "summary.json")
        log_file = open(log_path, "w", encoding="utf-8")

    segments: List[Tuple[str, float, float]] = []
    transitions: List[Tuple[str, str, float]] = []
    current_segment_state: Optional[str] = None
    current_segment_start: Optional[float] = None
    total_frames = 0
    test_end_ms: Optional[float] = None

    for frame_index, timestamp_ms, frame in VideoSource(source):
        tick_start = time.perf_counter()
        time_ms = _derive_time_ms(timestamp_ms, last_timestamp_ms, args.fps_assume, frame_index)
        if not _should_process_frame(time_ms, args.start_sec, args.end_sec):
            last_timestamp_ms = time_ms
            if args.end_sec is not None and time_ms > args.end_sec * 1000.0:
                break
            continue
        last_timestamp_ms = time_ms
        if cfg.enable_b and people_detector is not None and people_smoother is not None:
            raw_people = people_detector.process(frame)
            people = people_smoother.update(raw_people)
        else:
            people = _off_people(cfg, last_people)
            raw_people = None
        last_people = people

        if cfg.enable_c:
            raw_tags_c = sampling_detector.process(frame)
            tags_c = sampling_smoother.update(raw_tags_c)
        else:
            tags_c = _off_tags(cfg, last_tags_c, cfg.inject_tags_c, cfg.off_mode_c)
            raw_tags_c = None
        last_tags_c = tags_c

        if cfg.enable_d:
            raw_tags_d = blocking_detector.process(frame)
            tags_d = blocking_smoother.update(raw_tags_d)
        else:
            tags_d = _off_tags(cfg, last_tags_d, cfg.inject_tags_d, cfg.off_mode_d)
            raw_tags_d = None
        last_tags_d = tags_d

        state = None
        if cfg.enable_e:
            tags = set()
            tags.update(tags_c.tags)
            tags.update(tags_d.tags)
            state = engine.compute(tags)

        output = FrameOutput(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            people=people,
            tags_c=tags_c,
            tags_d=tags_d,
            state=state,
        )
        payload: Dict[str, Any] = _to_jsonable(asdict(output))
        print(json.dumps(payload, ensure_ascii=True))

        if args.debug and not args.view:
            debug_parts = []
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
            if debug_parts:
                print(f"DEBUG {frame_index}: {' | '.join(debug_parts)}")

        if args.view or args.test or args.save_video:
            now = time.perf_counter()
            frame_ms = (now - tick_start) * 1000.0
            dt = now - last_tick
            last_tick = now
            if dt > 0:
                fps = 1.0 / dt
                fps_ema = fps if fps_ema is None else fps_ema * 0.9 + fps * 0.1
            else:
                fps_ema = fps_ema or 0.0

            current_state = state.state_5class if state is not None else "N/A"
            video_t_s = timestamp_ms / 1000.0 if timestamp_ms is not None and timestamp_ms > 0 else None
            if current_state != last_state:
                last_state = current_state
                state_start_video_t = video_t_s
                last_state_duration_s = 0.0 if video_t_s is not None else None
            state_age_s = None
            if state_start_video_t is not None and video_t_s is not None:
                state_age_s = max(0.0, video_t_s - state_start_video_t)
                if last_state_duration_s is not None and state_age_s < last_state_duration_s:
                    state_age_s = last_state_duration_s
                last_state_duration_s = state_age_s

            if render_frame(
                frame,
                args,
                cfg,
                people,
                state,
                tags_c,
                tags_d,
                raw_people,
                raw_tags_c,
                raw_tags_d,
                sampling_smoother,
                blocking_smoother,
                people_smoother,
                frame_ms,
                fps_ema or 0.0,
                video_t_s,
                state_age_s,
                current_state,
                state_age_s,
                source_name,
            ):
                break

            if args.save_video:
                writer_mgr.write(frame)

            if args.test and log_file is not None:
                total_frames += 1
                record = {
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "tags_c_raw": sorted(raw_tags_c.tags) if raw_tags_c else [],
                    "tags_c_stable": sorted(tags_c.tags) if tags_c else [],
                    "tags_d_raw": sorted(raw_tags_d.tags) if raw_tags_d else [],
                    "tags_d_stable": sorted(tags_d.tags) if tags_d else [],
                    "state_5class": current_state,
                    "state_reason": state.reason if state is not None else None,
                    "current_state_duration_ms": None if state_age_s is None else state_age_s * 1000.0,
                    "c_debug": sampling_smoother.debug_info() if cfg.enable_c else {},
                    "d_debug": blocking_smoother.debug_info() if cfg.enable_d else {},
                    "perf_ms": frame_ms,
                    "fps": fps_ema or 0.0,
                }
                log_file.write(json.dumps(record, ensure_ascii=True) + "\n")

                if current_segment_state is None:
                    current_segment_state = current_state
                    current_segment_start = time_ms
                if current_state != current_segment_state:
                    if current_segment_start is not None:
                        segments.append((current_segment_state, current_segment_start, time_ms))
                    transitions.append((current_segment_state, current_state, time_ms))
                    current_segment_state = current_state
                    current_segment_start = time_ms
                test_end_ms = time_ms

    if args.test and log_file is not None:
        if current_segment_state is not None and current_segment_start is not None and test_end_ms is not None:
            segments.append((current_segment_state, current_segment_start, test_end_ms))
        log_file.close()
        summary = _finalize_summary(
            segments,
            transitions,
            short_jitter_s=cfg.test.short_jitter_s,
            close_open_warn=cfg.test.close_open_warn,
            close_open_fail=cfg.test.close_open_fail,
            short_jitter_warn=cfg.test.short_jitter_warn,
            short_jitter_fail=cfg.test.short_jitter_fail,
            max_transitions_per_sec=cfg.test.max_transitions_per_sec,
        )
        if summary_path:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=True, indent=2)
        duration_ms = 0.0
        if segments:
            duration_ms = segments[-1][2] - segments[0][1]
        _print_test_report(
            source,
            total_frames,
            duration_ms,
            summary,
            summary.get("state_durations_ms", {}),
            cfg.test.short_jitter_s,
        )

    message = writer_mgr.close()
    if message:
        print(message)

    close_windows(args)


if __name__ == "__main__":
    main()
