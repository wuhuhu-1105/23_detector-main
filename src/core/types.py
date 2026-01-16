from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Box:
    label: str
    conf: float
    xyxy: Tuple[float, float, float, float]
    track_id: Optional[int] = None


@dataclass
class PeopleRaw:
    active_ids: Set[int]
    count_raw: int
    boxes: List[Box] = field(default_factory=list)
    yolo_result: Optional[Any] = None


@dataclass
class TagsRaw:
    tags: Set[str]
    conf_by_tag: Dict[str, float] = field(default_factory=dict)
    boxes: List[Box] = field(default_factory=list)
    yolo_result: Optional[Any] = None


@dataclass
class PeopleStable:
    people_count_stable: int
    people_ok: bool


@dataclass
class TagsStable:
    tags: Set[str]


@dataclass
class StateResult:
    state_raw: str
    state_5class: str
    reason: str
    state_start_video_t: Optional[float] = None
    pause_video_t: Optional[float] = None


@dataclass
class FrameOutput:
    frame_index: int
    timestamp_ms: float
    frame_bgr: Any
    fps: Optional[float] = None
    detections: Dict[str, List[Box]] = field(default_factory=dict)
    state: str = "N/A"
    state_duration_sec: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
