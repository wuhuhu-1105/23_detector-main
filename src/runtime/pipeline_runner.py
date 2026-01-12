from __future__ import annotations

import time
from typing import Optional

from src.core.config import AppConfig, OffMode
from src.core.types import Box, FrameOutput, PeopleStable, TagsStable
from src.detectors.blocking_raw import BlockingRaw
from src.detectors.people_tracker_raw import PeopleTrackerRaw
from src.detectors.sampling_close_raw import SamplingCloseRaw
from src.engine.state_engine_5 import StateEngine5
from src.filters.blocking_smoother import BlockingSmoother
from src.filters.people_smoother import PeopleSmoother
from src.filters.sampling_close_smoother import SamplingCloseSmoother


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

    def _off_people(self, last: Optional[PeopleStable]) -> PeopleStable:
        if self._cfg.off_mode_b == OffMode.EMPTY:
            return PeopleStable(people_count_stable=0, people_ok=False)
        if self._cfg.off_mode_b == OffMode.HOLD_LAST and last is not None:
            return last
        if self._cfg.off_mode_b == OffMode.INJECT:
            return PeopleStable(
                people_count_stable=self._cfg.inject_people_count,
                people_ok=self._cfg.inject_people_count == self._cfg.people_smoother.expected_people,
            )
        return PeopleStable(people_count_stable=0, people_ok=False)

    def _off_tags(self, last: Optional[TagsStable], inject, off_mode: OffMode) -> TagsStable:
        if off_mode == OffMode.EMPTY:
            return TagsStable(tags=set())
        if off_mode == OffMode.HOLD_LAST and last is not None:
            return last
        if off_mode == OffMode.INJECT:
            return TagsStable(tags=set(inject))
        return TagsStable(tags=set())

    def _boxes_from_raw(self, raw) -> list[Box]:
        if raw is None:
            return []
        return list(raw.boxes)

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
            people = self._off_people(self._last_people)
            raw_people = None
        self._last_people = people

        if self._cfg.enable_c:
            raw_tags_c = self._sampling_detector.process(frame_bgr)
            tags_c = self._sampling_smoother.update(raw_tags_c)
        else:
            tags_c = self._off_tags(self._last_tags_c, self._cfg.inject_tags_c, self._cfg.off_mode_c)
            raw_tags_c = None
        self._last_tags_c = tags_c

        if self._cfg.enable_d:
            raw_tags_d = self._blocking_detector.process(frame_bgr)
            tags_d = self._blocking_smoother.update(raw_tags_d)
        else:
            tags_d = self._off_tags(self._last_tags_d, self._cfg.inject_tags_d, self._cfg.off_mode_d)
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
            "people": self._boxes_from_raw(raw_people),
            "sampling_close": self._boxes_from_raw(raw_tags_c),
            "blocking": self._boxes_from_raw(raw_tags_d),
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
