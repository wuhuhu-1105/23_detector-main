from __future__ import annotations

import os
import sys
import argparse
from dataclasses import asdict
from typing import Optional

import cv2

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.core.config import AppConfig
from src.runtime.frame_scheduler import FrameScheduler
from src.runtime.logger import get_logger, log_kv, setup_logging
from src.runtime.pipeline import PipelineRunner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to input video")
    parser.add_argument("--max_frames", type=int, default=None, help="Max processed frames")
    parser.add_argument("--min_step", type=int, default=1, help="Minimum step between frames")
    parser.add_argument("--use_round", action="store_true", help="Round raw_step instead of floor")
    parser.add_argument("--warmup_frames", type=int, default=5, help="Force step=1 for first N frames")
    parser.add_argument("--max_allowed_step", type=int, default=10, help="Hard cap for step")
    parser.add_argument("--target_ratio", type=float, default=1.0, help="Target real-time ratio (1.0 = real-time)")
    parser.add_argument("--save_dir", default=None, help="Optional directory to save sampled frames")
    return parser.parse_args()


def _read_video_fps(cap: cv2.VideoCapture) -> float:
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps is None or fps <= 0:
        return 25.0
    return float(fps)


def _read_total_frames(cap: cv2.VideoCapture) -> Optional[int]:
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if total is None or total <= 0:
        return None
    return int(total)


def main() -> None:
    setup_logging()
    logger = get_logger()
    args = _parse_args()
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {args.video}")

    video_fps = _read_video_fps(cap)
    total_frames = _read_total_frames(cap)
    runner = PipelineRunner(AppConfig())
    scheduler = FrameScheduler(
        video_fps=video_fps,
        warmup_frames=args.warmup_frames,
        target_ratio=args.target_ratio,
        max_allowed_step=args.max_allowed_step,
        min_step=args.min_step,
        use_round=args.use_round,
    )

    if args.save_dir:
        os.makedirs(args.save_dir, exist_ok=True)

    frame_index = 0
    processed = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            t0 = scheduler.begin()
            frame_output = runner.process_frame(
                frame_bgr,
                frame_index=frame_index,
                timestamp_ms=cap.get(cv2.CAP_PROP_POS_MSEC),
                video_t_s=(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0),
            )
            _ = asdict(frame_output)
            dt = scheduler.end(t0)

            next_idx, step, raw_step, raw_step_smooth, capped = scheduler.next_index(
                frame_index,
                dt,
                total_frames=total_frames,
            )

            throughput_fps = 1.0 / dt if dt > 0 else 0.0

            dt_smooth_ms = (raw_step_smooth / video_fps) * 1000.0 if video_fps > 0 else 0.0
            log_kv(
                "FRAME",
                logger=logger,
                frame=frame_index,
                dt_ms=dt * 1000.0,
                dt_smooth_ms=dt_smooth_ms,
                throughput_fps=throughput_fps,
                video_fps=video_fps,
                raw_step=raw_step,
                raw_step_smooth=raw_step_smooth,
                step=step,
                capped=capped,
                next_idx=next_idx,
            )

            if args.save_dir:
                out_path = os.path.join(args.save_dir, f"frame_{frame_index:06d}.jpg")
                cv2.imwrite(out_path, frame_bgr)

            processed += 1
            if args.max_frames is not None and processed >= args.max_frames:
                break

            frame_index = next_idx
            if total_frames is not None and frame_index >= total_frames - 1:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    finally:
        cap.release()


if __name__ == "__main__":
    main()
