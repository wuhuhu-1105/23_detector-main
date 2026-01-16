from __future__ import annotations

import queue
import threading
import time
from typing import Optional, Tuple

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

from src.core.config import AppConfig
from src.core.types import FrameOutput
from src.io.video_writer import VideoWriterManager
from src.runtime.frame_scheduler import FrameScheduler
from src.runtime.logger import get_logger, log_perf
from src.runtime.pipeline import PipelineRunner
from src.runtime.runner import iter_frame_outputs
from src.runtime.source_utils import parse_save_size


class VideoWorker(QThread):
    frame_ready = pyqtSignal(object, object)
    error = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, args, cfg: Optional[AppConfig] = None) -> None:
        super().__init__()
        self._args = args
        self._cfg = cfg or AppConfig()
        self._paused = False
        self._last_frame: Optional[object] = None
        self._last_meta: Optional[FrameOutput] = None
        self._writer_mgr: Optional[VideoWriterManager] = None
        self._logger = get_logger()
        self.setPriority(QThread.Priority.HighPriority)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def _init_writer(self) -> None:
        if not self._args.save_video or self._writer_mgr is not None:
            return
        save_size = parse_save_size(self._args.save_size)
        self._writer_mgr = VideoWriterManager(
            self._args.save_video,
            self._args.save_fps,
            save_size,
            self._args.fps_assume,
            None,
            None,
        )

    def _read_video_fps(self, cap: cv2.VideoCapture) -> float:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps is None or fps <= 0:
            return 25.0
        return float(fps)

    def _read_total_frames(self, cap: cv2.VideoCapture) -> Optional[int]:
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if total is None or total <= 0:
            return None
        return int(total)

    def run(self) -> None:
        self._init_writer()
        had_error = False
        try:
            source = self._args.source or self._args.video
            if self._args.dynamic_skip:
                cap = cv2.VideoCapture(source)
                reader_thread: Optional[threading.Thread] = None
                try:
                    if not cap.isOpened():
                        self.error.emit(f"Failed to open video source: {source}")
                        had_error = True
                        return
                    runner = PipelineRunner(self._cfg)
                    video_fps = self._read_video_fps(cap)
                    scheduler = FrameScheduler(
                        video_fps=video_fps,
                        warmup_frames=int(getattr(self._args, "warmup_frames", 5)),
                        target_ratio=float(getattr(self._args, "target_ratio", 1.0)),
                        max_allowed_step=int(getattr(self._args, "max_allowed_step", 10)),
                        min_step=1,
                        use_round=True,
                    )
                    auto_target = bool(getattr(self._args, "auto_target", False))
                    rt_smooth = float(getattr(self._args, "rt_smooth", 0.2))
                    rt_smooth = min(max(rt_smooth, 0.0), 1.0)
                    rt_last_wall: Optional[float] = None
                    rt_last_video: Optional[float] = None
                    rt_ratio_ema: Optional[float] = None
                    target_min = 0.5
                    target_max = 2.0
                    target_step = 0.05

                    queue_size = max(2, scheduler.max_allowed_step + 2)
                    frame_queue: queue.Queue[Tuple[int, object, float, Optional[float], float]] = queue.Queue(
                        maxsize=queue_size
                    )
                    reader_stop = threading.Event()
                    reader_done = threading.Event()
                    read_index = 0

                    def reader_loop() -> None:
                        nonlocal read_index
                        try:
                            while not reader_stop.is_set() and not self.isInterruptionRequested():
                                if self._paused:
                                    time.sleep(0.01)
                                    continue
                                t_read_start = time.perf_counter()
                                ok = cap.grab()
                                if not ok:
                                    if read_index == 0:
                                        self.error.emit(f"Failed to read first frame: {source}")
                                        had_error = True
                                    break
                                ok, frame_bgr = cap.retrieve()
                                t_read_end = time.perf_counter()
                                if not ok:
                                    if read_index == 0:
                                        self.error.emit(f"Failed to retrieve first frame: {source}")
                                        had_error = True
                                    break
                                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                                video_t_s = timestamp_ms / 1000.0 if timestamp_ms and timestamp_ms > 0 else None
                                read_ms = (t_read_end - t_read_start) * 1000.0
                                item = (read_index, frame_bgr, timestamp_ms, video_t_s, read_ms)
                                read_index += 1
                                try:
                                    frame_queue.put_nowait(item)
                                except queue.Full:
                                    try:
                                        frame_queue.get_nowait()
                                    except queue.Empty:
                                        pass
                                    try:
                                        frame_queue.put_nowait(item)
                                    except queue.Full:
                                        pass
                        finally:
                            reader_done.set()

                    reader_thread = threading.Thread(target=reader_loop, name="VideoReader", daemon=True)
                    reader_thread.start()

                    processed = 0
                    cur_index = 0
                    last_perf_t = time.perf_counter()
                    try:
                        while not self.isInterruptionRequested():
                            if self._paused:
                                self.msleep(30)
                                continue
                            try:
                                infer_index, frame_bgr, timestamp_ms, video_t_s, t_read_ms = frame_queue.get(
                                    timeout=0.5
                                )
                            except queue.Empty:
                                if reader_done.is_set():
                                    break
                                continue
                            t0 = scheduler.begin()
                            output = runner.process_frame(
                                frame_bgr,
                                frame_index=infer_index,
                                timestamp_ms=timestamp_ms,
                                video_t_s=video_t_s,
                            )
                            t1 = time.perf_counter()
                            dt = scheduler.end(t0)
                            next_idx, step, _, _, capped = scheduler.next_index(infer_index, dt)

                            dropped = 0
                            t_drop_ms = 0.0
                            for _ in range(max(0, step - 1)):
                                try:
                                    _, _, _, _, drop_ms = frame_queue.get_nowait()
                                except queue.Empty:
                                    break
                                dropped += 1
                                t_drop_ms += drop_ms

                            if auto_target:
                                video_out = None
                                if output.metrics:
                                    video_out = output.metrics.get("video_t_s")
                                if video_out is None and output.timestamp_ms and output.timestamp_ms > 0:
                                    video_out = output.timestamp_ms / 1000.0
                                if video_out is not None:
                                    wall_now = time.perf_counter()
                                    if rt_last_wall is not None and rt_last_video is not None:
                                        d_wall = wall_now - rt_last_wall
                                        d_video = video_out - rt_last_video
                                        if d_wall > 0.05 and d_video >= 0.0:
                                            ratio = d_video / d_wall
                                            if rt_ratio_ema is None:
                                                rt_ratio_ema = ratio
                                            else:
                                                rt_ratio_ema = rt_smooth * ratio + (1.0 - rt_smooth) * rt_ratio_ema
                                            if rt_ratio_ema < 0.9:
                                                scheduler.target_ratio = min(
                                                    target_max, scheduler.target_ratio + target_step
                                                )
                                            elif rt_ratio_ema > 1.1:
                                                scheduler.target_ratio = max(
                                                    target_min, scheduler.target_ratio - target_step
                                                )
                                    rt_last_wall = wall_now
                                    rt_last_video = video_out

                            if output.metrics is not None:
                                output.metrics["target_ratio"] = scheduler.target_ratio
                            self._last_frame = frame_bgr
                            self._last_meta = output
                            t_emit_start = time.perf_counter()
                            self.frame_ready.emit(frame_bgr.copy(), output)
                            t_emit_end = time.perf_counter()

                            if self._writer_mgr is not None:
                                self._writer_mgr.write(output.frame_bgr)

                            if self._args.max_fps > 0:
                                frame_interval = 1.0 / self._args.max_fps
                                self.msleep(int(frame_interval * 1000.0))
                            else:
                                self.msleep(1)

                            if self._args.perf_log and (time.perf_counter() - last_perf_t) >= 1.0:
                                last_perf_t = time.perf_counter()
                                t_infer_ms = (t1 - t0) * 1000.0
                                t_emit_ms = (t_emit_end - t_emit_start) * 1000.0
                                fps_est = 1000.0 / t_infer_ms if t_infer_ms > 0 else 0.0
                                log_perf(
                                    logger=self._logger,
                                    frame=infer_index,
                                    step=step,
                                    capped=capped,
                                    next_idx=next_idx,
                                    dropped=dropped,
                                    t_read_ms=t_read_ms,
                                    t_drop_ms=t_drop_ms,
                                    t_infer_ms=t_infer_ms,
                                    t_emit_ms=t_emit_ms,
                                    fps_est=fps_est,
                                )

                            processed += 1
                            cur_index = infer_index + 1 + dropped
                    finally:
                        reader_stop.set()
                        if reader_thread is not None:
                            reader_thread.join(timeout=2.0)
                finally:
                    cap.release()
            else:
                try:
                    for output in iter_frame_outputs(self._args, self._cfg, source):
                        if self.isInterruptionRequested():
                            break
                        if self._paused:
                            self.msleep(30)
                            continue

                        self._last_frame = output.frame_bgr
                        self._last_meta = output
                        self.frame_ready.emit(output.frame_bgr.copy(), output)

                        if self._writer_mgr is not None:
                            self._writer_mgr.write(output.frame_bgr)

                        if self._args.max_fps > 0:
                            frame_interval = 1.0 / self._args.max_fps
                            self.msleep(int(frame_interval * 1000.0))
                        else:
                            self.msleep(1)
                except Exception as exc:
                    self.error.emit(str(exc))
                    had_error = True
        finally:
            if self._writer_mgr is not None:
                message = self._writer_mgr.close()
                if message:
                    print(message)
            if not had_error and not self.isInterruptionRequested():
                self.finished.emit("eof")
