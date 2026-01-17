from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class RealtimeConfig:
    device: Optional[str] = None
    device_mode: str = "auto"
    display_fps: float = 15.0
    rt_smooth: float = 0.2
    target_ratio: float = 1.0
    no_overlay: bool = False
    dynamic_skip: bool = False
    perf_log: bool = False
    max_fps: float = 0.0
    infer_every: int = 1
    allow_network: bool = False
    debug: bool = False

    def apply_to_args(self, args: Any) -> None:
        for key, value in self.__dict__.items():
            if hasattr(args, key):
                setattr(args, key, value)


@dataclass
class ReportConfig:
    outdir: Optional[str] = None
    outputs_root: Optional[str] = None
    reports_dir: Optional[str] = None
    report_dir: Optional[str] = None
    format: str = "all"
    export_video: bool = False
    video_out: Optional[str] = None
    no_boxes: bool = False
    device: Optional[str] = None
    device_mode: str = "auto"
    half: bool = False
    allow_network: bool = False
    use_tqdm: Optional[bool] = None
    log_fn: Optional[Callable[[str], None]] = None
    run_id: Optional[str] = None
    overrides: Dict[str, Any] = field(default_factory=dict)

    def apply_to_args(self, args: Any) -> None:
        args.outdir = self.outdir
        args.format = self.format
        args.export_video = self.export_video
        args.video_out = self.video_out
        args.no_boxes = self.no_boxes
        args.device = self.device
        args.device_mode = self.device_mode
        args.half = self.half
        args.allow_network = self.allow_network
        for key, value in self.overrides.items():
            setattr(args, key, value)
