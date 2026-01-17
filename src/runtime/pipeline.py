from __future__ import annotations

import json
import time
from typing import Iterator, Optional, Set

import torch

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
from src.runtime.source_utils import derive_time_ms, should_process_frame


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


def _boxes_from_raw(raw) -> list[Box]:
    if raw is None:
        return []
    return list(raw.boxes)


class PipelineRunner:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._people_detector = PeopleTrackerRaw(cfg.people_detector) if cfg.enable_b else None
        self._sampling_detector = SamplingCloseRaw(cfg.sampling_close)
        self._blocking_detector = BlockingRaw(cfg.blocking_detector)
        self._people_smoother = PeopleSmoother(cfg.people_smoother) if cfg.enable_b else None
        self._sampling_smoother = SamplingCloseSmoother(cfg.tags_c_smoother)
        self._blocking_smoother = BlockingSmoother(cfg.tags_d_smoother)
        self._engine = StateEngine5(cfg.state_engine)
        self._last_people: Optional[PeopleStable] = None
        self._last_tags_c: Optional[TagsStable] = None
        self._last_tags_d: Optional[TagsStable] = None
        self._last_state: Optional[str] = None
        self._state_start_video_t: Optional[float] = None
        self._state_start_perf: Optional[float] = None
        self._last_tick = time.perf_counter()
        self._fps_ema: Optional[float] = None

    def process_frame(
        self,
        frame_bgr,
        frame_index: int,
        timestamp_ms: float,
        video_t_s: Optional[float],
    ) -> FrameOutput:
        if self._cfg.enable_b and self._people_detector is not None and self._people_smoother is not None:
            raw_people = self._people_detector.process(frame_bgr)
            people = self._people_smoother.update(raw_people)
        else:
            people = _off_people(self._cfg, self._last_people)
            raw_people = None
        self._last_people = people

        if self._cfg.enable_c:
            raw_tags_c = self._sampling_detector.process(frame_bgr)
            tags_c = self._sampling_smoother.update(raw_tags_c)
        else:
            tags_c = _off_tags(self._cfg, self._last_tags_c, self._cfg.inject_tags_c, self._cfg.off_mode_c)
            raw_tags_c = None
        self._last_tags_c = tags_c

        if self._cfg.enable_d:
            raw_tags_d = self._blocking_detector.process(frame_bgr)
            tags_d = self._blocking_smoother.update(raw_tags_d)
        else:
            tags_d = _off_tags(self._cfg, self._last_tags_d, self._cfg.inject_tags_d, self._cfg.off_mode_d)
            raw_tags_d = None
        self._last_tags_d = tags_d

        state = None
        if self._cfg.enable_e:
            tags = set()
            tags.update(tags_c.tags)
            tags.update(tags_d.tags)
            state = self._engine.compute(tags)

        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now
        if dt > 0:
            fps = 1.0 / dt
            self._fps_ema = fps if self._fps_ema is None else self._fps_ema * 0.9 + fps * 0.1
        else:
            self._fps_ema = self._fps_ema or 0.0

        current_state = state.state_5class if state is not None else "N/A"
        if current_state != self._last_state:
            self._last_state = current_state
            self._state_start_video_t = video_t_s
            self._state_start_perf = now if video_t_s is None else None

        state_duration = None
        if self._state_start_video_t is not None and video_t_s is not None:
            state_duration = max(0.0, video_t_s - self._state_start_video_t)
        elif self._state_start_perf is not None:
            state_duration = max(0.0, now - self._state_start_perf)

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
        }

        return FrameOutput(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            frame_bgr=frame_bgr,
            fps=self._fps_ema,
            detections=detections,
            state=current_state,
            state_duration_sec=state_duration,
            metrics=metrics,
        )


def iter_frame_outputs(args, cfg: AppConfig, source: str, *, start_frame: int = 0) -> Iterator[FrameOutput]:
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

    def _device_str(model) -> str:
        dev = getattr(model, "device", None)
        if dev is None and getattr(model, "model", None) is not None:
            try:
                dev = next(model.model.parameters()).device
            except StopIteration:
                dev = None
        return str(dev) if dev is not None else "unknown"

    def _half_flag(model) -> Optional[bool]:
        if getattr(model, "model", None) is None:
            return None
        try:
            dtype = next(model.model.parameters()).dtype
        except StopIteration:
            return None
        return dtype == torch.float16

    def _print_info(tag: str, detector, imgsz: Optional[int]) -> None:
        model = detector.model
        model_path = getattr(detector.cfg, "model_path", "unknown")
        model_name = model_path.split("\\")[-1]
        print(
            json.dumps(
                {
                    "model_tag": tag,
                    "model_name": model_name,
                    "model_path": model_path,
                    "device": _device_str(model),
                    "half": _half_flag(model),
                    "imgsz": imgsz,
                },
                ensure_ascii=True,
            )
        )

    infer_every = max(1, int(getattr(args, "infer_every", 1)))

    video_iter = iter(VideoSource(source, start_frame=start_frame))
    while True:
        read_start = time.perf_counter()
        try:
            frame_index, timestamp_ms, video_t_s, frame_bgr = next(video_iter)
        except StopIteration:
            break
        read_end = time.perf_counter()
        read_ms = (read_end - read_start) * 1000.0

        time_ms = derive_time_ms(timestamp_ms, last_timestamp_ms, args.fps_assume, frame_index)
        if not should_process_frame(time_ms, args.start_sec, args.end_sec):
            last_timestamp_ms = time_ms
            if args.end_sec is not None and time_ms > args.end_sec * 1000.0:
                break
            continue
        last_timestamp_ms = time_ms

        infer_start = time.perf_counter()
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
        infer_end = time.perf_counter()
        infer_ms = (infer_end - infer_start) * 1000.0

        if not getattr(args, "_model_info_printed", False):
            _print_info("people", people_detector, cfg.people_detector.imgsz if cfg.enable_b else None)
            _print_info("sampling_close", sampling_detector, cfg.sampling_close.imgsz if cfg.enable_c else None)
            _print_info("blocking", blocking_detector, cfg.blocking_detector.imgsz if cfg.enable_d else None)
            setattr(args, "_model_info_printed", True)

        post_start = time.perf_counter()
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
            "stage_ms": {
                "read_ms": read_ms,
                "infer_ms": infer_ms,
                "post_ms": (time.perf_counter() - post_start) * 1000.0,
            },
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
