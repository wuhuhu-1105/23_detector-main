from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set

from src.core.paths import get_best_dir

class OffMode(str, Enum):
    EMPTY = "EMPTY"
    HOLD_LAST = "HOLD_LAST"
    INJECT = "INJECT"
    REPLAY = "REPLAY"


@dataclass
class PeopleSmootherConfig:
    window_size: int = 10
    max_id_age: int = 20
    active_id_age: int = 8
    expected_people: int = 2
    min_stable: int = 3
    hold: int = 5
    min_track_hits: int = 3


@dataclass
class TagHysteresis:
    on_count: int
    off_count: int


@dataclass
class TagsSmootherConfig:
    thresholds: Dict[str, TagHysteresis]
    force_one_of: Optional[Set[str]] = None


@dataclass
class StateEngineConfig:
    debounce_k: int = 1


@dataclass
class DetectorConfig:
    model_path: str
    conf: float = 0.25
    iou: float = 0.5
    imgsz: int = 640
    max_det: int = 100
    device: Optional[str] = None
    half: bool = False


@dataclass
class SamplingCloseConfig:
    model_path: str
    imgsz: int = 640
    iou: float = 0.5
    conf_close: float = 0.40
    conf_sampling: float = 0.25
    max_det: int = 10
    device: Optional[str] = None
    half: bool = False


@dataclass
class ReplayConfig:
    pass


@dataclass
class TestConfig:
    short_jitter_s: float = 1.0
    short_jitter_warn: int = 5
    short_jitter_fail: int = 15
    close_open_warn: int = 3
    close_open_fail: int = 8
    max_transitions_per_sec: int = 3


@dataclass
class AppConfig:
    enable_b: bool = True
    enable_c: bool = True
    enable_d: bool = True
    enable_e: bool = True

    off_mode_b: OffMode = OffMode.HOLD_LAST
    off_mode_c: OffMode = OffMode.HOLD_LAST
    off_mode_d: OffMode = OffMode.HOLD_LAST

    inject_people_count: int = 2
    inject_tags_c: Set[str] = field(default_factory=set)
    inject_tags_d: Set[str] = field(default_factory=set)

    people_detector: DetectorConfig = field(
        default_factory=lambda: DetectorConfig(
            model_path=os.path.join(get_best_dir(), "3_11n", "yolo11n.pt"),
            conf=0.25,
            iou=0.45,
        )
    )
    sampling_close_detector: DetectorConfig = field(
        default_factory=lambda: DetectorConfig(
            model_path=os.path.join(get_best_dir(), "2_sampling_close", "best.pt"),
            conf=0.25,
            iou=0.45,
        )
    )
    sampling_close: SamplingCloseConfig = field(
        default_factory=lambda: SamplingCloseConfig(
            model_path=os.path.join(get_best_dir(), "2_sampling_close", "best.pt"),
            imgsz=640,
            iou=0.50,
            conf_close=0.40,
            conf_sampling=0.25,
            max_det=10,
        )
    )
    blocking_detector: DetectorConfig = field(
        default_factory=lambda: DetectorConfig(
            model_path=os.path.join(get_best_dir(), "1_blocking", "best.pt"),
            conf=0.25,
            iou=0.45,
        )
    )

    people_smoother: PeopleSmootherConfig = field(default_factory=PeopleSmootherConfig)
    tags_c_smoother: TagsSmootherConfig = field(
        default_factory=lambda: TagsSmootherConfig(
            thresholds={
                "close": TagHysteresis(on_count=12, off_count=18),
                "sampling": TagHysteresis(on_count=5, off_count=8),
            }
        )
    )
    tags_d_smoother: TagsSmootherConfig = field(
        default_factory=lambda: TagsSmootherConfig(
            thresholds={
                "blocking": TagHysteresis(on_count=6, off_count=3),
                "no_blocking": TagHysteresis(on_count=3, off_count=3),
            },
            force_one_of={"blocking", "no_blocking"},
        )
    )

    state_engine: StateEngineConfig = field(default_factory=lambda: StateEngineConfig(debounce_k=1))
    replay: ReplayConfig = field(default_factory=ReplayConfig)
    test: TestConfig = field(default_factory=TestConfig)
