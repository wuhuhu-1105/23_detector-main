from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class BaseEvent:
    event_type: str
    run_id: Optional[str] = None
    ts_s: Optional[float] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RealtimeEvent(BaseEvent):
    frame_index: Optional[int] = None
    fps: Optional[float] = None
    state_raw: Optional[str] = None
    state_5class: Optional[str] = None
    state_cn: Optional[str] = None
    duration_s: Optional[float] = None
    people_count: Optional[int] = None
    people_ok: Optional[bool] = None
    tags_c: Optional[list[str]] = None
    tags_d: Optional[list[str]] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None


@dataclass
class ReportProgressEvent(BaseEvent):
    done_frames: int = 0
    total_frames: int = 0
    fps: float = 0.0
    eta_s: Optional[float] = None
    stage: str = "video"
    percent: Optional[float] = None
    done: Optional[int] = None
    total: Optional[int] = None
    message: Optional[str] = None
