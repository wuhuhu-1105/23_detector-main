from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Iterable, Optional

from .types import Report, Session
from .utils_time import format_ts


def _compute_ts_s(output, fps_assume: float) -> float:
    metrics = output.metrics or {}
    video_t_s = metrics.get("video_t_s")
    if video_t_s is not None:
        return float(video_t_s)
    time_ms = metrics.get("time_ms", output.timestamp_ms)
    if time_ms is not None:
        return float(time_ms) / 1000.0
    return float(output.frame_index) / max(fps_assume, 1e-6)


def write_frames_meta_jsonl(frame_outputs: Iterable, path: str, fps_assume: float) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for output in frame_outputs:
            ts_s = _compute_ts_s(output, fps_assume)
            record = {
                "frame_index": output.frame_index,
                "ts_s": ts_s,
                "people_count": (output.metrics or {}).get("people_count", 0),
                "tags_c": (output.metrics or {}).get("tags_c", []),
                "tags_d": (output.metrics or {}).get("tags_d", []),
                "detections": {k: [asdict(b) for b in v] for k, v in output.detections.items()},
            }
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return path


def _find_session(ts_s: float, sessions: list[Session]) -> Optional[Session]:
    for session in sessions:
        if session.start_ts_s <= ts_s <= session.end_ts_s:
            return session
    return None


def _in_observation(ts_s: float, report: Report) -> bool:
    for seg in report.open_no_sampling_segments:
        if seg.start_ts_s <= ts_s <= seg.end_ts_s:
            return True
    return False


def export_overlay_video(
    source: str,
    report: Report,
    meta_path: str,
    out_path: str,
    *,
    fps_assume: float,
    no_boxes: bool,
    progress=None,
    on_frame=None,
) -> str:
    try:
        import cv2
    except ImportError as exc:
        raise ImportError("opencv-python is required for video export") from exc

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video source: {source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or fps_assume
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Failed to open video writer: {out_path}")

    banner_until_s = -1.0
    banner_text = ""
    start_wall = time.perf_counter()

    with open(meta_path, "r", encoding="utf-8") as f:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            line = f.readline()
            if not line:
                break
            meta = json.loads(line)
            ts_s = meta.get("ts_s", 0.0)
            time_text = format_ts(ts_s)
            people_count = meta.get("people_count", 0)

            session = _find_session(ts_s, report.sessions)
            if session is None:
                session_text = "Out of session"
            else:
                session_text = f"Session: #{session.session_id} ({session.session_type})"

            observation = _in_observation(ts_s, report)

            for change in report.people_count_change_events:
                if int(round(change.change_ts_s)) == int(round(ts_s)):
                    banner_text = f"PEOPLE CHANGE: {change.from_count} -> {change.to_count}"
                    banner_until_s = ts_s + 1.5
                    break

            if not no_boxes:
                color_map = {
                    "people": (0, 255, 0),
                    "sampling_close": (0, 180, 255),
                    "blocking": (255, 180, 0),
                }
                for key, boxes in meta.get("detections", {}).items():
                    color = color_map.get(key, (200, 200, 200))
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.get("xyxy", [0, 0, 0, 0]))
                        conf = box.get("conf")
                        label = box.get("label", key)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        text = label if conf is None else f"{label} {conf:.2f}"
                        cv2.putText(
                            frame,
                            text,
                            (x1, max(0, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            color,
                            1,
                            cv2.LINE_AA,
                        )

            cv2.putText(
                frame,
                f"Time: {time_text}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                f"People: {people_count}",
                (width - 200, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                session_text,
                (width - 420, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            if observation:
                cv2.putText(
                    frame,
                    "OBSERVATION (OPEN w/o sampling)",
                    (10, height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

            if banner_text and ts_s <= banner_until_s:
                cv2.rectangle(frame, (0, 0), (width, 35), (0, 0, 0), -1)
                cv2.putText(
                    frame,
                    banner_text,
                    (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

            writer.write(frame)
            if progress is not None:
                progress.update(1)
            if on_frame is not None:
                on_frame()

    writer.release()
    cap.release()
    elapsed = time.perf_counter() - start_wall
    return out_path, elapsed
