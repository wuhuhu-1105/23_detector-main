from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import cv2

from src.core.config import AppConfig, OffMode
from src.core.types import Box, FrameOutput, PeopleStable, TagsStable
from src.detectors.blocking_raw import BlockingRaw
from src.detectors.people_tracker_raw import PeopleTrackerRaw
from src.detectors.sampling_close_raw import SamplingCloseRaw
from src.engine.state_engine_5 import StateEngine5
from src.filters.blocking_smoother import BlockingSmoother
from src.filters.people_smoother import PeopleSmoother
from src.filters.sampling_close_smoother import SamplingCloseSmoother
from src.io.video_source import VideoSource
from src.io.video_writer import VideoWriterManager
from src.runtime.serialization import to_jsonable
from src.runtime.source_utils import derive_time_ms, parse_save_size, should_process_frame
from src.runtime.summary import finalize_summary, print_test_report
from src.runtime.work_log import WorkLogWriter


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


def _boxes_from_raw(raw) -> List[Box]:
    if raw is None:
        return []
    return list(raw.boxes)


def iter_frame_outputs(args, cfg: AppConfig, source: str) -> Iterator[FrameOutput]:
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
    last_raw_people = None
    last_raw_tags_c = None
    last_raw_tags_d = None

    last_state: Optional[str] = None
    state_start_video_t: Optional[float] = None
    state_start_perf: Optional[float] = None
    last_timestamp_ms: Optional[float] = None
    last_tick = time.perf_counter()
    fps_ema: Optional[float] = None

    infer_every = max(1, int(getattr(args, "infer_every", 1)))

    for frame_index, timestamp_ms, video_t_s, frame_bgr in VideoSource(source):
        tick_start = time.perf_counter()
        time_ms = derive_time_ms(timestamp_ms, last_timestamp_ms, args.fps_assume, frame_index)
        if not should_process_frame(time_ms, args.start_sec, args.end_sec):
            last_timestamp_ms = time_ms
            if args.end_sec is not None and time_ms > args.end_sec * 1000.0:
                break
            continue
        last_timestamp_ms = time_ms

        should_infer = (frame_index % infer_every) == 0 or last_people is None
        if should_infer:
            if cfg.enable_b and people_detector is not None and people_smoother is not None:
                raw_people = people_detector.process(frame_bgr)
                people = people_smoother.update(raw_people)
            else:
                people = _off_people(cfg, last_people)
                raw_people = None
            if cfg.enable_c:
                raw_tags_c = sampling_detector.process(frame_bgr)
                tags_c = sampling_smoother.update(raw_tags_c)
            else:
                tags_c = _off_tags(cfg, last_tags_c, cfg.inject_tags_c, cfg.off_mode_c)
                raw_tags_c = None
            if cfg.enable_d:
                raw_tags_d = blocking_detector.process(frame_bgr)
                tags_d = blocking_smoother.update(raw_tags_d)
            else:
                tags_d = _off_tags(cfg, last_tags_d, cfg.inject_tags_d, cfg.off_mode_d)
                raw_tags_d = None
            state = None
            if cfg.enable_e:
                tags = set()
                tags.update(tags_c.tags)
                tags.update(tags_d.tags)
                state = engine.compute(tags)
            last_people = people
            last_tags_c = tags_c
            last_tags_d = tags_d
            last_raw_people = raw_people
            last_raw_tags_c = raw_tags_c
            last_raw_tags_d = raw_tags_d
        else:
            people = last_people
            tags_c = last_tags_c
            tags_d = last_tags_d
            raw_people = last_raw_people
            raw_tags_c = last_raw_tags_c
            raw_tags_d = last_raw_tags_d
            state = None
            if cfg.enable_e and tags_c is not None and tags_d is not None:
                tags = set()
                tags.update(tags_c.tags)
                tags.update(tags_d.tags)
                state = engine.compute(tags)

        now = time.perf_counter()
        dt = now - last_tick
        last_tick = now
        if dt > 0:
            fps = 1.0 / dt
            fps_ema = fps if fps_ema is None else fps_ema * 0.9 + fps * 0.1
        else:
            fps_ema = fps_ema or 0.0

        current_state = state.state_5class if state is not None else "N/A"
        if current_state != last_state:
            last_state = current_state
            state_start_video_t = video_t_s
            state_start_perf = now if video_t_s is None else None

        state_duration = None
        if state_start_video_t is not None and video_t_s is not None:
            state_duration = max(0.0, video_t_s - state_start_video_t)
        elif state_start_perf is not None:
            state_duration = max(0.0, now - state_start_perf)

        detections = {
            "people": _boxes_from_raw(raw_people),
            "sampling_close": _boxes_from_raw(raw_tags_c),
            "blocking": _boxes_from_raw(raw_tags_d),
        }
        metrics = {
            "people_count": people.people_count_stable if people is not None else None,
            "people_ok": people.people_ok if people is not None else None,
            "tags_c": sorted(tags_c.tags) if tags_c is not None else [],
            "tags_d": sorted(tags_d.tags) if tags_d is not None else [],
            "state_reason": state.reason if state is not None else None,
            "video_t_s": video_t_s,
            "time_ms": time_ms,
        }

        yield FrameOutput(
            frame_index=frame_index,
            timestamp_ms=time_ms,
            frame_bgr=frame_bgr,
            fps=fps_ema,
            detections=detections,
            state=current_state,
            state_duration_sec=state_duration,
            metrics=metrics,
        )


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
    if args.save_video:
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
    work_log = None
    summary_path = None
    if args.test:
        os.makedirs(args.out, exist_ok=True)
        run_stamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(args.out, f"run_{run_stamp}.jsonl")
        summary_path = os.path.join(args.out, "summary.json")
        log_file = open(log_path, "w", encoding="utf-8")
    if work_log is None:
        work_log = WorkLogWriter(args.out)

    segments: List[Tuple[str, float, float]] = []
    transitions: List[Tuple[str, str, float]] = []
    current_segment_state: Optional[str] = None
    current_segment_start: Optional[float] = None
    total_frames = 0
    test_end_ms: Optional[float] = None

    for output in iter_frame_outputs(args, cfg, source):
        payload: Dict[str, Any] = to_jsonable(_payload_from_output(output))
        print(json.dumps(payload, ensure_ascii=True))

        if args.save_video:
            writer_mgr.write(output.frame_bgr)

        if work_log is not None:
            video_t_s = output.metrics.get("video_t_s")
            if video_t_s is None:
                time_ms = output.metrics.get("time_ms", output.timestamp_ms)
                video_t_s = (time_ms / 1000.0) if time_ms is not None else None
            tags_d = set(output.metrics.get("tags_d") or [])
            people_count = output.metrics.get("people_count")
            work_log.update(video_t_s, tags_d, people_count)

        if args.test and log_file is not None:
            total_frames += 1
            record = {
                "frame_index": output.frame_index,
                "timestamp_ms": output.timestamp_ms,
                "state_5class": output.state,
                "state_reason": output.metrics.get("state_reason"),
                "current_state_duration_ms": None
                if output.state_duration_sec is None
                else output.state_duration_sec * 1000.0,
                "fps": output.fps or 0.0,
            }
            log_file.write(json.dumps(record, ensure_ascii=True) + "\n")

            time_ms = output.metrics.get("time_ms", output.timestamp_ms)
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
    if work_log is not None:
        work_log.close()
