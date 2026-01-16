from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import cv2

from src.core.config import AppConfig
from src.core.types import FrameOutput
from src.io.video_writer import VideoWriterManager
from src.runtime.pipeline import iter_frame_outputs
from src.runtime.serialization import to_jsonable
from src.runtime.source_utils import parse_save_size
from src.runtime.summary import finalize_summary, print_test_report


def _payload_from_output(output: FrameOutput) -> Dict[str, Any]:
    det_payload = {}
    for key, boxes in output.detections.items():
        det_payload[key] = [asdict(box) for box in boxes]
    return {
        "frame_index": output.frame_index,
        "timestamp_ms": output.timestamp_ms,
        "fps": output.fps,
        "state": output.state,
        "state_duration_sec": output.state_duration_sec,
        "detections": det_payload,
        "metrics": output.metrics,
    }


def run_headless(args, cfg: AppConfig, source: str) -> None:
    cap_meta = None
    source_fps = None
    source_size = None
    if args.save_video or args.test:
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

    save_size = parse_save_size(args.save_size)
    writer_mgr = VideoWriterManager(
        args.save_video,
        args.save_fps,
        save_size,
        args.fps_assume,
        source_fps,
        source_size,
    )

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
    video_fps = source_fps or args.fps_assume
    target_fps = args.max_fps if args.max_fps and args.max_fps > 0 else video_fps
    last_emit_t: Optional[float] = None
    display_tick_count = 0
    start_wall = time.perf_counter()

    while True:
        iterator = iter_frame_outputs(args, cfg, source)
        while True:
            loop_t0 = time.perf_counter()
            try:
                output = next(iterator)
            except StopIteration:
                break

            emit_start = time.perf_counter()
            payload: Dict[str, Any] = to_jsonable(_payload_from_output(output))
            print(json.dumps(payload, ensure_ascii=True))

            if args.save_video:
                writer_mgr.write(output.frame_bgr)

            emit_end = time.perf_counter()

            if args.test and log_file is not None:
                total_frames += 1
                now = time.perf_counter()
                if last_emit_t is None:
                    last_emit_t = now
                display_tick_count += 1
                elapsed = max(1e-9, now - last_emit_t)
                display_fps = display_tick_count / elapsed
                processing_fps = output.fps or display_fps
                rt_ratio = None
                if processing_fps is not None and video_fps > 0:
                    rt_ratio = processing_fps / video_fps
                target_ratio = None
                if processing_fps is not None and target_fps > 0:
                    target_ratio = processing_fps / target_fps

                time_ms = output.metrics.get("time_ms", output.timestamp_ms)
                warmup_s = float(getattr(args, "warmup_s", 0.5))
                if time_ms is not None and time_ms < warmup_s * 1000.0:
                    last_emit_t = now
                    display_tick_count = 0
                else:
                    perf_ms = (time.perf_counter() - loop_t0) * 1000.0
                    emit_ms = (emit_end - emit_start) * 1000.0
                    stage_from_output = output.metrics.get("stage_ms") or {}
                    stage_ms = {
                        "read_ms": stage_from_output.get("read_ms"),
                        "infer_ms": stage_from_output.get("infer_ms"),
                        "post_ms": stage_from_output.get("post_ms"),
                        "emit_ms": emit_ms,
                    }
                    record = {
                        "frame_index": output.frame_index,
                        "timestamp_ms": output.timestamp_ms,
                        "state_5class": output.state,
                        "state_reason": output.metrics.get("state_reason"),
                        "current_state_duration_ms": None
                        if output.state_duration_sec is None
                        else output.state_duration_sec * 1000.0,
                        "fps": output.fps or 0.0,
                        "display_fps": display_fps,
                        "rt_ratio": rt_ratio,
                        "target_ratio": target_ratio,
                        "perf_ms": perf_ms,
                        "stage_ms": stage_ms,
                    }
                    log_file.write(json.dumps(record, ensure_ascii=True) + "\n")

                if current_segment_state is None:
                    current_segment_state = output.state
                    current_segment_start = time_ms
                if output.state != current_segment_state:
                    if current_segment_start is not None:
                        segments.append((current_segment_state, current_segment_start, time_ms))
                    transitions.append((current_segment_state, output.state, time_ms))
                    current_segment_state = output.state
                    current_segment_start = time_ms
                test_end_ms = time_ms

        if args.min_duration_s is None:
            break
        if (time.perf_counter() - start_wall) >= args.min_duration_s:
            break

    if args.test and log_file is not None:
        if current_segment_state is not None and current_segment_start is not None and test_end_ms is not None:
            segments.append((current_segment_state, current_segment_start, test_end_ms))
        log_file.close()
        summary = finalize_summary(
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
        print_test_report(
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
