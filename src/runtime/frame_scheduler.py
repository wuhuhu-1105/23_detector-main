from __future__ import annotations

import time
from typing import List, Optional, Tuple


class FrameScheduler:
    def __init__(
        self,
        *,
        video_fps: float,
        warmup_frames: int = 5,
        target_ratio: float = 1.0,
        max_allowed_step: int = 10,
        min_step: int = 1,
        use_round: bool = True,
    ) -> None:
        self.video_fps = max(0.1, float(video_fps))
        self.warmup_frames = max(0, int(warmup_frames))
        self.target_ratio = max(0.01, float(target_ratio))
        self.max_allowed_step = max(1, int(max_allowed_step))
        self.min_step = max(1, int(min_step))
        self.use_round = True
        self.count = 0
        self._dt_window: List[float] = []

    def begin(self) -> float:
        return time.perf_counter()

    def end(self, t0: float) -> float:
        dt = max(0.0, time.perf_counter() - t0)
        self._dt_window.append(dt)
        if len(self._dt_window) > 3:
            self._dt_window.pop(0)
        return dt

    def next_index(
        self,
        cur_index: int,
        dt: float,
        total_frames: Optional[int] = None,
    ) -> Tuple[int, int, float, float, int]:
        warmup_active = self.count < self.warmup_frames
        if self.count == self.warmup_frames:
            self._dt_window.clear()
        dt_smooth = sum(self._dt_window) / len(self._dt_window) if self._dt_window else dt
        raw_step = dt * self.video_fps
        raw_step_smooth = dt_smooth * self.video_fps * self.target_ratio
        if warmup_active:
            step = 1
        else:
            step = round(raw_step_smooth)
        step = max(self.min_step, step)
        capped = 1 if step > self.max_allowed_step else 0
        step = min(step, self.max_allowed_step)
        step = max(step, 1)
        next_index = cur_index + step
        if total_frames is not None and total_frames > 0:
            next_index = min(next_index, total_frames - 1)
        self.count += 1
        return next_index, step, raw_step, raw_step_smooth, capped
