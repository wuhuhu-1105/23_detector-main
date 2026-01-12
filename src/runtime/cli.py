from __future__ import annotations

import argparse

from src.core.config import OffMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?", help="Path to input video")
    parser.add_argument("--source", help="Video source path (test mode)")
    parser.add_argument("--ui", choices=["qt", "headless"], default="qt")
    parser.add_argument("--headless", action="store_true", help="Force headless pipeline")
    parser.add_argument("--debug", action="store_true", help="Show debug info")
    parser.add_argument("--test", action="store_true", help="Enable test mode logging")
    parser.add_argument("--start-sec", type=float, default=None)
    parser.add_argument("--end-sec", type=float, default=None)
    parser.add_argument("--out", default="out")
    parser.add_argument("--fps-assume", type=float, default=25.0)
    parser.add_argument("--save-video", help="Save demo video to path")
    parser.add_argument("--save-fps", type=float, default=None)
    parser.add_argument("--save-size", default=None)
    parser.add_argument("--infer-every", type=int, default=1, help="Run inference every N frames")
    parser.add_argument("--max-fps", type=float, default=0.0, help="Max UI FPS (0 = unlimited)")
    parser.add_argument("--no-overlay", action="store_true", help="Disable overlay drawing")
    parser.add_argument("--dynamic-skip", dest="dynamic_skip", action="store_true", help="Enable dynamic frame skipping")
    parser.add_argument("--realtime", dest="dynamic_skip", action="store_true", help="Alias for --dynamic-skip")
    parser.add_argument("--drop-frames", dest="dynamic_skip", action="store_true", help="Drop frames to keep UI real-time")
    parser.add_argument("--warmup-frames", dest="warmup_frames", type=int, default=5, help="Warm-up frames for dynamic skip")
    parser.add_argument("--warmup_frames", dest="warmup_frames", type=int, default=5, help="Alias for --warmup-frames")
    parser.add_argument("--ema", type=float, default=0.2, help="EMA smoothing for dynamic skip")
    parser.add_argument("--max-step", dest="max_allowed_step", type=int, default=10, help="Hard cap for dropped frames")
    parser.add_argument("--max-allowed-step", dest="max_allowed_step", type=int, default=10, help="Alias for --max-step")
    parser.add_argument("--max_allowed_step", dest="max_allowed_step", type=int, default=10, help="Alias for --max-step")
    parser.add_argument("--perf-log", action="store_true", help="Enable perf logs in VideoWorker")
    parser.add_argument("--display-fps", type=float, default=15.0, help="UI display refresh FPS (QTimer)")
    parser.add_argument("--rt-smooth", type=float, default=0.2, help="EMA smoothing for RealTime Ratio (0-1)")
    parser.add_argument("--target-ratio", type=float, default=1.0, help="Target real-time ratio for FrameScheduler")
    parser.add_argument("--enable-b", dest="enable_b", action="store_true")
    parser.add_argument("--disable-b", dest="enable_b", action="store_false")
    parser.add_argument("--enable-c", dest="enable_c", action="store_true")
    parser.add_argument("--disable-c", dest="enable_c", action="store_false")
    parser.add_argument("--enable-d", dest="enable_d", action="store_true")
    parser.add_argument("--disable-d", dest="enable_d", action="store_false")
    parser.add_argument("--enable-e", dest="enable_e", action="store_true")
    parser.add_argument("--disable-e", dest="enable_e", action="store_false")
    parser.add_argument("--off-mode-b", choices=[m.value for m in OffMode])
    parser.add_argument("--off-mode-c", choices=[m.value for m in OffMode])
    parser.add_argument("--off-mode-d", choices=[m.value for m in OffMode])
    parser.add_argument("--inject-people-count", type=int)
    parser.add_argument("--inject-tags-c", default="")
    parser.add_argument("--inject-tags-d", default="")
    parser.add_argument("--c-imgsz", type=int)
    parser.add_argument("--c-iou", type=float)
    parser.add_argument("--c-conf-close", type=float)
    parser.add_argument("--c-conf-sampling", type=float)
    parser.add_argument("--c-max-det", type=int)
    parser.set_defaults(enable_b=None, enable_c=None, enable_d=None, enable_e=None)
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args()
