from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import Callable, Optional

from src.core.contracts.config import RealtimeConfig
from src.core.contracts.events import RealtimeEvent
from src.core.contracts.state import normalize_state, to_state_cn
from src.core.types import FrameOutput


SERVICE_VERSION = "0.1"


class RealtimeService:
    _warned_cross_imports = False

    def __init__(self, *, run_id: Optional[str] = None) -> None:
        self._callbacks: list[Callable[[RealtimeEvent], None]] = []
        self._window = None
        self._worker = None
        self._source: Optional[str] = None
        self._run_id = run_id or uuid.uuid4().hex
        self._started = False

    def on_event(self, callback: Callable[[RealtimeEvent], None]) -> None:
        self._callbacks.append(callback)

    def start(self, source: str, config: Optional[RealtimeConfig] = None):
        self._assert_no_cross_imports()
        config = config or RealtimeConfig()
        args = self._build_args(source, config)
        self._source = source
        win = self._create_window(source, args, config)
        self._window = win
        self._worker = getattr(win, "_worker", None)
        self._started = True
        if self._worker is not None and hasattr(self._worker, "frame_ready"):
            self._worker.frame_ready.connect(self._on_frame)
        if self._worker is not None and hasattr(self._worker, "error"):
            self._worker.error.connect(self._on_error)
        if self._worker is not None and hasattr(self._worker, "finished"):
            self._worker.finished.connect(self._on_finished)
        return win

    def stop(self, *, timeout_s: float = 2.0) -> None:
        has_worker = self._worker is not None
        is_running = False
        if has_worker and hasattr(self._worker, "isRunning"):
            try:
                is_running = bool(self._worker.isRunning())
            except Exception:
                is_running = False
        print(
            "[RealtimeService] stop requested "
            f"run_id={self._run_id} has_worker={has_worker} is_running={is_running}"
        )
        start_t = time.perf_counter()
        joined = False
        if has_worker and hasattr(self._worker, "requestInterruption"):
            self._worker.requestInterruption()
            if hasattr(self._worker, "wait"):
                print(f"[RealtimeService] joining worker... timeout_sec={timeout_s:.2f}")
                joined = bool(self._worker.wait(int(timeout_s * 1000)))
        if has_worker:
            if is_running and not joined and (time.perf_counter() - start_t) >= timeout_s:
                print(
                    "[RealtimeService] stop timeout "
                    f"run_id={self._run_id} joined=false action=suggest_restart"
                )
            else:
                print(f"[RealtimeService] stop ok run_id={self._run_id} joined={str(joined).lower()}")
        elif not self._started:
            print(f"[RealtimeService] stop ok (not started) run_id={self._run_id}")
        if self._window is not None and hasattr(self._window, "close"):
            self._window.close()
        self._worker = None
        self._window = None
        print(f"[RealtimeService] resources released run_id={self._run_id}")

    def _emit(self, event: RealtimeEvent) -> None:
        for callback in list(self._callbacks):
            callback(event)

    @staticmethod
    def run_headless(args, cfg, source: str, *, event_cb=None) -> None:
        from src.services.realtime_impl.runner import run_headless

        run_headless(args, cfg, source, event_cb=event_cb)

    def _on_frame(self, _frame_bgr, output: FrameOutput) -> None:
        event = self.event_from_output(output, source=self._source, run_id=self._run_id)
        self._emit(event)

    def _on_error(self, message: str) -> None:
        event = RealtimeEvent(event_type="error", message=message, source=self._source, run_id=self._run_id)
        self._emit(event)

    def _on_finished(self) -> None:
        event = RealtimeEvent(event_type="finished", source=self._source, run_id=self._run_id)
        self._emit(event)

    @staticmethod
    def _build_args(source: str, config: RealtimeConfig) -> argparse.Namespace:
        from src.runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--source", source])
        config.apply_to_args(args)
        return args

    @staticmethod
    def _create_window(source: str, args: argparse.Namespace, config: RealtimeConfig):
        from src.core.config import AppConfig, OffMode
        from src.runtime.config_overrides import apply_cli_overrides
        from src.runtime.network_guard import enforce_no_network
        from src.runtime.source_utils import validate_source, write_last_source
        from src.ui_qt.main_window import MainWindow
        from src.services.realtime_impl.worker import VideoWorker

        if config.device:
            args.device = config.device
        if args.device is None:
            args.device = "cpu"
        args.source = source

        cfg = AppConfig()
        apply_cli_overrides(cfg, args)
        enforce_no_network(cfg, allow_network=getattr(args, "allow_network", False))

        if cfg.off_mode_b == OffMode.REPLAY or cfg.off_mode_c == OffMode.REPLAY or cfg.off_mode_d == OffMode.REPLAY:
            raise NotImplementedError("REPLAY is not enabled yet.")

        validate_source(source)
        write_last_source(source)

        worker = VideoWorker(args, cfg=cfg)
        win = MainWindow(
            debug=args.debug,
            worker=worker,
            display_fps=getattr(args, "display_fps", 15.0),
            rt_smooth=getattr(args, "rt_smooth", 0.2),
            target_ratio=getattr(args, "target_ratio", 1.0),
            no_overlay=getattr(args, "no_overlay", False),
        )
        win.resize(1280, 720)
        worker.frame_ready.connect(win.on_frame)
        worker.error.connect(win.on_worker_error)
        if hasattr(worker, "finished"):
            worker.finished.connect(win.notify_finished)
        worker.start()
        return win

    @staticmethod
    def event_from_output(
        output: FrameOutput,
        source: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> RealtimeEvent:
        metrics = output.metrics or {}
        tags_c = list(metrics.get("tags_c") or [])
        tags_d = list(metrics.get("tags_d") or [])
        people_ok = metrics.get("people_ok")
        people_count = metrics.get("people_count") or 0
        state_reason = metrics.get("state_reason")
        state_5class, _reason = normalize_state(
            output.state,
            output.state,
            state_reason,
            people_ok,
            people_count,
            set(tags_c),
            set(tags_d),
        )
        if not state_5class:
            state_5class = "-"
        ts_s = metrics.get("video_t_s")
        if ts_s is None:
            ts_s = (output.timestamp_ms / 1000.0) if output.timestamp_ms is not None else None
        return RealtimeEvent(
            event_type="frame",
            ts_s=ts_s,
            source=source,
            run_id=run_id,
            frame_index=output.frame_index,
            fps=output.fps,
            state_raw=output.state,
            state_5class=state_5class,
            state_cn=to_state_cn(state_5class),
            duration_s=output.state_duration_sec,
            people_count=people_count,
            people_ok=bool(people_ok) if people_ok is not None else None,
            tags_c=tags_c,
            tags_d=tags_d,
            metrics=metrics,
        )

    @classmethod
    def _assert_no_cross_imports(cls) -> None:
        if cls._warned_cross_imports:
            return
        for name in sys.modules.keys():
            if name.startswith("src.report"):
                print(
                    "[RealtimeService] warning: report modules are loaded; "
                    "realtime must not import report directly."
                )
                cls._warned_cross_imports = True
                break
