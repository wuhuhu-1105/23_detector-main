from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ReportHeader:
    report_version: str
    generated_at: str
    source_path: str
    models_used: List[str]


@dataclass
class ReportConfigData:
    sampling_start_s: float
    sampling_end_s: float
    gap_allow_sampling_s: float
    people_grace_s: float
    unblocked_alarm_s: float
    gap_allow_unblocked_s: float
    enable_min_sampling_duration: bool
    sampling_min_s: float
    fps_assume: float


@dataclass
class PresenceSegment:
    state: str
    start_ts_s: float
    end_ts_s: float
    duration_s: float
    start_frame_idx: Optional[int] = None
    end_frame_idx: Optional[int] = None


@dataclass
class ObservationSegment:
    start_ts_s: float
    end_ts_s: float
    duration_s: float
    start_frame_idx: Optional[int] = None
    end_frame_idx: Optional[int] = None


@dataclass
class Session:
    session_id: int
    session_type: str
    start_ts_s: float
    end_ts_s: float
    duration_s: float
    start_frame_idx: Optional[int] = None
    end_frame_idx: Optional[int] = None


@dataclass
class CrewInterval:
    interval_id: int
    session_id: int
    deviation_type: str
    start_ts_s: float
    end_ts_s: float
    duration_s: float


@dataclass
class SessionCrewStats:
    session_id: int
    expected_people: int
    ok_duration_s: float
    under_duration_s: float
    over_duration_s: float
    violation_count: int


@dataclass
class PeopleCountSegment:
    start_ts_s: float
    end_ts_s: float
    duration_s: float
    people_count: int
    context_in_session: Optional[bool] = None


@dataclass
class PeopleCountChangeEvent:
    from_count: int
    to_count: int
    change_ts_s: float
    confirmed_ts_s: float
    context_in_session: Optional[bool] = None


@dataclass
class Alarm:
    alarm_id: int
    alarm_type: str
    start_ts_s: float
    end_ts_s: float
    trigger_ts_s: Optional[float] = None
    session_id: Optional[int] = None
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class Summary:
    overall_result: str
    alarm_counts: Dict[str, int]
    session_count: int
    min_people_count: Optional[int] = None
    max_people_count: Optional[int] = None
    people_change_count: int = 0


@dataclass
class Report:
    header: ReportHeader
    config: ReportConfigData
    presence_segments: List[PresenceSegment]
    open_no_sampling_segments: List[ObservationSegment]
    sessions: List[Session]
    crew_intervals: List[CrewInterval]
    session_crew_stats: List[SessionCrewStats]
    people_count_segments: List[PeopleCountSegment]
    people_count_change_events: List[PeopleCountChangeEvent]
    alarms: List[Alarm]
    summary: Summary
