from __future__ import annotations

import argparse
import sys
from typing import Optional
def main(args: Optional[argparse.Namespace] = None) -> None:
    from src.runtime.cli import parse_args
    if args is None:
        args = parse_args()

    from src.core.config import AppConfig, OffMode
    from src.runtime.config_overrides import apply_cli_overrides
    from src.runtime.runner import run_headless
    from src.runtime.source_utils import resolve_source, validate_source, write_last_source
    if args.headless:
        args.ui = "headless"
    source = resolve_source(args)
    args.source = source
    cfg = AppConfig()
    apply_cli_overrides(cfg, args)

    if cfg.off_mode_b == OffMode.REPLAY or cfg.off_mode_c == OffMode.REPLAY or cfg.off_mode_d == OffMode.REPLAY:
        raise NotImplementedError("REPLAY is not enabled yet.")

    validate_source(source)
    write_last_source(source)

    if args.ui == "headless":
        run_headless(args, cfg, source)
        return

    from PyQt6.QtWidgets import QApplication

    from src.ui_qt.main_window import MainWindow
    from src.ui_qt.worker import VideoWorker

    app = QApplication(sys.argv)
    worker = VideoWorker(args, cfg=cfg)
    win = MainWindow(
        debug=args.debug,
        worker=worker,
        display_fps=getattr(args, "display_fps", 15.0),
        rt_smooth=getattr(args, "rt_smooth", 0.2),
        target_ratio=getattr(args, "target_ratio", 1.0),
    )
    win.resize(1280, 720)
    win.show()

    worker.frame_ready.connect(win.on_frame)
    worker.start()

    def on_exit() -> None:
        worker.requestInterruption()
        worker.wait(1000)

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
