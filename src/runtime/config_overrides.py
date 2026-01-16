from __future__ import annotations

import argparse

from src.core.config import AppConfig, OffMode


def apply_cli_overrides(cfg: AppConfig, args: argparse.Namespace) -> None:
    if args.enable_b is not None:
        cfg.enable_b = args.enable_b
    if args.enable_c is not None:
        cfg.enable_c = args.enable_c
    if args.enable_d is not None:
        cfg.enable_d = args.enable_d
    if args.enable_e is not None:
        cfg.enable_e = args.enable_e

    if args.off_mode_b:
        cfg.off_mode_b = OffMode(args.off_mode_b)
    if args.off_mode_c:
        cfg.off_mode_c = OffMode(args.off_mode_c)
    if args.off_mode_d:
        cfg.off_mode_d = OffMode(args.off_mode_d)

    if args.inject_people_count is not None:
        cfg.inject_people_count = args.inject_people_count
    if args.inject_tags_c:
        cfg.inject_tags_c = {t.strip() for t in args.inject_tags_c.split(",") if t.strip()}
    if args.inject_tags_d:
        cfg.inject_tags_d = {t.strip() for t in args.inject_tags_d.split(",") if t.strip()}

    if args.device:
        cfg.people_detector.device = args.device
        cfg.sampling_close.device = args.device
        cfg.blocking_detector.device = args.device
    if getattr(args, "half", False):
        cfg.people_detector.half = True
        cfg.sampling_close.half = True
        cfg.blocking_detector.half = True
    if getattr(args, "imgsz", None) is not None:
        cfg.people_detector.imgsz = args.imgsz
        cfg.sampling_close.imgsz = args.imgsz
        cfg.blocking_detector.imgsz = args.imgsz

    if args.c_imgsz is not None:
        cfg.sampling_close.imgsz = args.c_imgsz
    if args.c_iou is not None:
        cfg.sampling_close.iou = args.c_iou
    if args.c_conf_close is not None:
        cfg.sampling_close.conf_close = args.c_conf_close
    if args.c_conf_sampling is not None:
        cfg.sampling_close.conf_sampling = args.c_conf_sampling
    if args.c_max_det is not None:
        cfg.sampling_close.max_det = args.c_max_det
