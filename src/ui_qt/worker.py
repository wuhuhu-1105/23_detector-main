from __future__ import annotations

import time
from typing import List, Optional, Set, Tuple

import cv2
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from src.core.config import AppConfig
from src.io.video_writer import VideoWriterManager
from src.runtime.frame_scheduler import FrameScheduler
from src.runtime.qt_adapter import frame_output_to_view
from src.runtime.pipeline_runner import PipelineRunner
from src.runtime.runner import iter_frame_outputs
from src.runtime.source_utils import parse_save_size
from src.runtime.work_log import WorkLogWriter


class VideoWorker(QThread):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, args, cfg: Optional[AppConfig] = None) -> None:
        super().__init__()
        self._args = args
        self._cfg = cfg or AppConfig()
        self._paused = False
        self._last_frame: Optional[QImage] = None
        self._last_status = None
        self._writer_mgr: Optional[VideoWriterManager] = None
        self._work_log_records: List[Tuple[float, Optional[Set[str]], Optional[int]]] = []

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self._last_frame is not None and self._last_status is not None:
            status = self._last_status
            status.run_state_cn = "Paused" if paused else "Running"
            self.frame_ready.emit(self._last_frame, status)

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

    def _record_work_log(self, status) -> None:
        duration_s = status.duration_s
        if duration_s is None:
            return
        self._work_log_records.append((float(duration_s), status.tags_d_set, status.people_count))

    def export_report(self) -> None:
        if not self._work_log_records:
            return
        writer = WorkLogWriter(self._args.out)
        try:
            for duration_s, tags_d, people_count in self._work_log_records:
                writer.update(duration_s, tags_d, people_count)
        finally:
            writer.close()

    def run(self) -> None:
        self._init_writer()
        try:
            source = self._args.source or self._args.video
            if self._args.dynamic_skip:
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
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
                processed = 0
                cur_index = 0
                try:
                    while not self.isInterruptionRequested():
                        if self._paused:
                            self.msleep(30)
                            continue
                        t_read_start = time.perf_counter()
                        ok, frame_bgr = cap.read()
                        t_read_end = time.perf_counter()
                        if not ok:
                            break
                        timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                        video_t_s = timestamp_ms / 1000.0 if timestamp_ms and timestamp_ms > 0 else None
                        t0 = scheduler.begin()
                        infer_index = cur_index
                        output = runner.process_frame(
                            frame_bgr,
                            frame_index=infer_index,
                            timestamp_ms=timestamp_ms,
                            video_t_s=video_t_s,
                        )
                        t1 = time.perf_counter()
                        dt = scheduler.end(t0)
                        next_idx, step, _, _, capped = scheduler.next_index(infer_index, dt)

                        t_drop_start = time.perf_counter()
                        dropped_ok = True
                        dropped = 0
                        for _ in range(max(0, step - 1)):
                            ok, _ = cap.read()
                            if not ok:
                                dropped_ok = False
                                break
                            dropped += 1
                        t_drop_end = time.perf_counter()

                        qimg, status = frame_output_to_view(output, no_overlay=self._args.no_overlay)
                        self._last_frame = qimg
                        self._last_status = status
                        t_emit_start = time.perf_counter()
                        self.frame_ready.emit(qimg, status)
                        t_emit_end = time.perf_counter()
                        self._record_work_log(status)

                        if self._writer_mgr is not None:
                            self._writer_mgr.write(output.frame_bgr)

                        if self._args.max_fps > 0:
                            frame_interval = 1.0 / self._args.max_fps
                            self.msleep(int(frame_interval * 1000.0))
                        else:
                            self.msleep(1)

                        if self._args.perf_log and processed % 30 == 0:
                            t_read_ms = (t_read_end - t_read_start) * 1000.0
                            t_drop_ms = (t_drop_end - t_drop_start) * 1000.0
                            t_infer_ms = (t1 - t0) * 1000.0
                            t_emit_ms = (t_emit_end - t_emit_start) * 1000.0
                            fps_est = 1000.0 / t_infer_ms if t_infer_ms > 0 else 0.0
                            print(
                                "PERF"
                                f" idx={infer_index} step={step} capped={capped} next_idx={next_idx} dropped={dropped}"
                                f" t_read_ms={t_read_ms:.2f}"
                                f" t_drop_ms={t_drop_ms:.2f}"
                                f" t_infer_ms={t_infer_ms:.2f}"
                                f" t_emit_ms={t_emit_ms:.2f}"
                                f" fps_est={fps_est:.2f}"
                            )

                        processed += 1
                        cur_index = infer_index + 1 + dropped
                        if not dropped_ok:
                            break
                finally:
                    cap.release()
            else:
                for output in iter_frame_outputs(self._args, self._cfg, source):
                    if self.isInterruptionRequested():
                        break
                    if self._paused:
                        self.msleep(30)
                        continue

                    qimg, status = frame_output_to_view(output, no_overlay=self._args.no_overlay)
                    self._last_frame = qimg
                    self._last_status = status
                    self.frame_ready.emit(qimg, status)
                    self._record_work_log(status)

                    if self._writer_mgr is not None:
                        self._writer_mgr.write(output.frame_bgr)

                    if self._args.max_fps > 0:
                        frame_interval = 1.0 / self._args.max_fps
                        self.msleep(int(frame_interval * 1000.0))
                    else:
                        self.msleep(1)
        finally:
            if self._writer_mgr is not None:
                message = self._writer_mgr.close()
                if message:
                    print(message)
