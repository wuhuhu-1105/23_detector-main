from __future__ import annotations

import argparse
import sys
from typing import Optional


def create_detector_window(
    video_path: str,
    args: Optional[argparse.Namespace] = None,
    *,
    device: Optional[str] = None,
):
    from src.runtime.cli import build_parser
    from src.core.config import AppConfig, OffMode
    from src.runtime.config_overrides import apply_cli_overrides
    from src.runtime.network_guard import enforce_no_network
    from src.runtime.source_utils import validate_source, write_last_source
    from src.ui_qt.main_window import MainWindow
    from src.ui_qt.worker import VideoWorker

    if args is None:
        parser = build_parser()
        args = parser.parse_args(["--source", video_path])

    if device:
        args.device = device
    if args.device is None:
        args.device = "cpu"
    args.source = video_path

    cfg = AppConfig()
    apply_cli_overrides(cfg, args)
    enforce_no_network(cfg, allow_network=getattr(args, "allow_network", False))

    if cfg.off_mode_b == OffMode.REPLAY or cfg.off_mode_c == OffMode.REPLAY or cfg.off_mode_d == OffMode.REPLAY:
        raise NotImplementedError("REPLAY is not enabled yet.")

    validate_source(video_path)
    write_last_source(video_path)

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


def main(args: Optional[argparse.Namespace] = None) -> None:
    from src.runtime.cli import build_parser, parse_args
    from src.runtime.file_dialog import pick_video_path
    from src.runtime.logger import setup_logging
    from src.runtime.source_utils import resolve_source

    if args is None:
        if len(sys.argv) == 1:
            selected = pick_video_path()
            if not selected:
                print("No video selected. Exiting.")
                return
            parser = build_parser()
            args = parser.parse_args(["--source", selected])
        else:
            args = parse_args()

    setup_logging()
    if args.headless:
        args.ui = "headless"

    source = resolve_source(args)
    args.source = source

    if args.ui == "headless":
        from src.core.config import AppConfig
        from src.runtime.config_overrides import apply_cli_overrides
        try:
            from src.runtime.runner import run_headless
        except ModuleNotFoundError as exc:
            if exc.name == "torch":
                print("Missing dependency: torch. Please run in detector_env or install torch.")
                return
            raise

        if args.device is None:
            args.device = "cpu"
        cfg = AppConfig()
        apply_cli_overrides(cfg, args)
        try:
            run_headless(args, cfg, source)
        except ModuleNotFoundError as exc:
            if exc.name == "torch":
                print("Missing dependency: torch. Please run in detector_env or install torch.")
                return
            raise
        return

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    try:
        win = create_detector_window(source, args=args)
    except ModuleNotFoundError as exc:
        if exc.name == "torch":
            print("Missing dependency: torch. Please run in detector_env or install torch.")
            return
        raise
    win.show()

    def on_exit() -> None:
        if hasattr(win, "_worker") and win._worker is not None:
            win._worker.requestInterruption()
            win._worker.wait(1000)

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
