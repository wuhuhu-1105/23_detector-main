from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from src.core.types import FrameOutput

from .config import ReportConfig
from .types import (
    Alarm,
    CrewInterval,
    ObservationSegment,
    PeopleCountChangeEvent,
    PeopleCountSegment,
    PresenceSegment,
    Report,
    ReportHeader,
    Session,
    SessionCrewStats,
    Summary,
)


@dataclass
class _FrameSignal:
    frame_idx: int
    ts_s: float
    people_count: int
    open_state: bool
    sampling_present: bool
    blocking_state: str


def _frame_to_signal(output: FrameOutput, fps_assume: float) -> _FrameSignal:
    metrics = output.metrics or {}
    video_t_s = metrics.get("video_t_s")
    if video_t_s is None:
        time_ms = metrics.get("time_ms", output.timestamp_ms)
        if time_ms is not None:
            ts_s = float(time_ms) / 1000.0
        else:
            ts_s = float(output.frame_index) / max(fps_assume, 1e-6)
    else:
        ts_s = float(video_t_s)

    tags_c = metrics.get("tags_c") or []
    tags_d = metrics.get("tags_d") or []
    people_count = metrics.get("people_count")
    if people_count is None:
        people_count = 0

    open_state = "close" not in tags_c
    sampling_present = "sampling" in tags_c
    if "blocking" in tags_d:
        blocking_state = "blocking"
    elif "no_blocking" in tags_d:
        blocking_state = "no_blocking"
    else:
        blocking_state = "unknown"

    return _FrameSignal(
        frame_idx=output.frame_index,
        ts_s=ts_s,
        people_count=int(people_count),
        open_state=open_state,
        sampling_present=sampling_present,
        blocking_state=blocking_state,
    )


def _iter_intervals(frames: List[_FrameSignal]):
    for idx in range(len(frames) - 1):
        start = frames[idx].ts_s
        end = frames[idx + 1].ts_s
        if end <= start:
            continue
        yield frames[idx], start, end


def _build_segments(frames: List[_FrameSignal], predicate):
    if not frames:
        return []
    segments = []
    prev_value = predicate(frames[0])
    start_ts = frames[0].ts_s
    start_frame = frames[0].frame_idx
    for frame in frames[1:]:
        value = predicate(frame)
        if value != prev_value:
            segments.append((prev_value, start_ts, frame.ts_s, start_frame, frame.frame_idx))
            prev_value = value
            start_ts = frame.ts_s
            start_frame = frame.frame_idx
    segments.append((prev_value, start_ts, frames[-1].ts_s, start_frame, frames[-1].frame_idx))
    return segments


def _session_type(frame: _FrameSignal) -> Optional[str]:
    if not frame.open_state or not frame.sampling_present:
        return None
    if frame.blocking_state == "blocking":
        return "BLOCKED_SAMPLING"
    if frame.blocking_state == "no_blocking":
        return "UNBLOCKED_SAMPLING"
    return None


def _build_sessions(frames: List[_FrameSignal], cfg: ReportConfig) -> List[Session]:
    sessions: List[Session] = []
    candidate_type: Optional[str] = None
    candidate_start_ts: Optional[float] = None
    candidate_start_frame: Optional[int] = None
    candidate_accum = 0.0
    candidate_gap = 0.0

    current_session = None
    session_gap = 0.0
    effective_gap_end = max(cfg.sampling_end_s, cfg.gap_allow_sampling_s)

    for frame, start, end in _iter_intervals(frames):
        dt = end - start
        interval_type = _session_type(frame)

        if current_session is None:
            if interval_type is None:
                if candidate_type is not None:
                    candidate_gap += dt
                    if candidate_gap > cfg.gap_allow_sampling_s:
                        candidate_type = None
                        candidate_start_ts = None
                        candidate_start_frame = None
                        candidate_accum = 0.0
                        candidate_gap = 0.0
                continue

            if interval_type != candidate_type:
                candidate_type = interval_type
                candidate_start_ts = start
                candidate_start_frame = frame.frame_idx
                candidate_accum = 0.0
                candidate_gap = 0.0

            candidate_accum += dt
            candidate_gap = 0.0
            if candidate_accum >= cfg.sampling_start_s:
                current_session = {
                    "type": candidate_type,
                    "start_ts": candidate_start_ts,
                    "start_frame": candidate_start_frame,
                    "end_ts": end,
                    "end_frame": frame.frame_idx,
                }
                session_gap = 0.0
                candidate_type = None
                candidate_start_ts = None
                candidate_start_frame = None
                candidate_accum = 0.0
                candidate_gap = 0.0
            continue

        if interval_type == current_session["type"]:
            session_gap = 0.0
            current_session["end_ts"] = end
            current_session["end_frame"] = frame.frame_idx
        else:
            session_gap += dt
            if session_gap <= cfg.gap_allow_sampling_s:
                current_session["end_ts"] = end
                current_session["end_frame"] = frame.frame_idx
                continue

            if session_gap >= effective_gap_end:
                excess = session_gap - effective_gap_end
                end_ts = end - excess
                if end_ts < current_session["start_ts"]:
                    end_ts = current_session["start_ts"]
                current_session["end_ts"] = end_ts
                current_session["end_frame"] = frame.frame_idx
                sessions.append(
                    Session(
                        session_id=len(sessions) + 1,
                        session_type=current_session["type"],
                        start_ts_s=float(current_session["start_ts"]),
                        end_ts_s=float(current_session["end_ts"]),
                        duration_s=max(0.0, float(current_session["end_ts"]) - float(current_session["start_ts"])),
                        start_frame_idx=current_session["start_frame"],
                        end_frame_idx=current_session["end_frame"],
                    )
                )
                current_session = None
                session_gap = 0.0
                candidate_type = None
                candidate_start_ts = None
                candidate_start_frame = None
                candidate_accum = 0.0
                candidate_gap = 0.0

                if interval_type is not None:
                    candidate_type = interval_type
                    candidate_start_ts = start
                    candidate_start_frame = frame.frame_idx
                    candidate_accum = dt
                    candidate_gap = 0.0

    if current_session is not None:
        end_ts = current_session["end_ts"]
        sessions.append(
            Session(
                session_id=len(sessions) + 1,
                session_type=current_session["type"],
                start_ts_s=float(current_session["start_ts"]),
                end_ts_s=float(end_ts),
                duration_s=max(0.0, float(end_ts) - float(current_session["start_ts"])),
                start_frame_idx=current_session["start_frame"],
                end_frame_idx=current_session["end_frame"],
            )
        )

    return sessions


def _iter_session_intervals(frames: List[_FrameSignal], start_ts: float, end_ts: float):
    for frame, start, end in _iter_intervals(frames):
        if end <= start_ts:
            continue
        if start >= end_ts:
            break
        overlap_start = max(start, start_ts)
        overlap_end = min(end, end_ts)
        if overlap_end <= overlap_start:
            continue
        yield frame, overlap_start, overlap_end


def _build_crew_for_session(
    frames: List[_FrameSignal],
    session: Session,
    cfg: ReportConfig,
) -> tuple[List[CrewInterval], SessionCrewStats]:
    intervals: List[CrewInterval] = []
    expected_people = 2
    ok_duration = 0.0
    under_duration = 0.0
    over_duration = 0.0

    deviation_active = False
    deviation_type = None
    deviation_start = None
    deviation_end = None
    deviation_duration = 0.0

    for frame, start, end in _iter_session_intervals(frames, session.start_ts_s, session.end_ts_s):
        dt = end - start
        people = frame.people_count
        if people == expected_people:
            ok_duration += dt
            if deviation_active:
                if deviation_duration > cfg.people_grace_s and deviation_start is not None and deviation_end is not None:
                    intervals.append(
                        CrewInterval(
                            interval_id=len(intervals) + 1,
                            session_id=session.session_id,
                            deviation_type=deviation_type or "UNKNOWN",
                            start_ts_s=deviation_start,
                            end_ts_s=deviation_end,
                            duration_s=max(0.0, deviation_end - deviation_start),
                        )
                    )
                deviation_active = False
                deviation_type = None
                deviation_start = None
                deviation_end = None
                deviation_duration = 0.0
            continue

        if people < expected_people:
            under_duration += dt
            next_type = "UNDER"
        else:
            over_duration += dt
            next_type = "OVER"

        if not deviation_active or deviation_type != next_type:
            if deviation_active and deviation_duration > cfg.people_grace_s and deviation_start is not None:
                intervals.append(
                    CrewInterval(
                        interval_id=len(intervals) + 1,
                        session_id=session.session_id,
                        deviation_type=deviation_type or "UNKNOWN",
                        start_ts_s=deviation_start,
                        end_ts_s=deviation_end or start,
                        duration_s=max(0.0, (deviation_end or start) - deviation_start),
                    )
                )
            deviation_active = True
            deviation_type = next_type
            deviation_start = start
            deviation_end = end
            deviation_duration = dt
        else:
            deviation_duration += dt
            deviation_end = end

    if deviation_active and deviation_duration > cfg.people_grace_s and deviation_start is not None and deviation_end is not None:
        intervals.append(
            CrewInterval(
                interval_id=len(intervals) + 1,
                session_id=session.session_id,
                deviation_type=deviation_type or "UNKNOWN",
                start_ts_s=deviation_start,
                end_ts_s=deviation_end,
                duration_s=max(0.0, deviation_end - deviation_start),
            )
        )

    stats = SessionCrewStats(
        session_id=session.session_id,
        expected_people=expected_people,
        ok_duration_s=ok_duration,
        under_duration_s=under_duration,
        over_duration_s=over_duration,
        violation_count=len(intervals),
    )
    return intervals, stats


def _build_unblocked_alarm(frames: List[_FrameSignal], cfg: ReportConfig) -> Optional[Alarm]:
    accum = 0.0
    gap = 0.0
    start_ts: Optional[float] = None
    for frame, start, end in _iter_intervals(frames):
        dt = end - start
        cond = frame.open_state and frame.sampling_present and frame.blocking_state == "no_blocking"
        if cond:
            if start_ts is None:
                start_ts = start
            accum += dt
            gap = 0.0
            if accum >= cfg.unblocked_alarm_s:
                trigger_ts = end - (accum - cfg.unblocked_alarm_s)
                return Alarm(
                    alarm_id=0,
                    alarm_type="UNBLOCKED_INSERTION",
                    start_ts_s=start_ts,
                    end_ts_s=trigger_ts,
                    trigger_ts_s=trigger_ts,
                )
        else:
            gap += dt
            if gap > cfg.gap_allow_unblocked_s:
                accum = 0.0
                gap = 0.0
                start_ts = None
    return None


def _in_session(ts_s: float, sessions: List[Session]) -> bool:
    for session in sessions:
        if session.start_ts_s <= ts_s <= session.end_ts_s:
            return True
    return False


def _build_people_count_segments(
    frames: List[_FrameSignal],
    sessions: List[Session],
    stable_s: float,
) -> tuple[List[PeopleCountSegment], List[PeopleCountChangeEvent]]:
    if not frames:
        return [], []
    segments: List[PeopleCountSegment] = []
    events: List[PeopleCountChangeEvent] = []

    current_count = frames[0].people_count
    segment_start = frames[0].ts_s
    pending_count = None
    pending_start = None
    pending_duration = 0.0

    for frame, start, end in _iter_intervals(frames):
        dt = end - start
        count = frame.people_count
        if count == current_count:
            pending_count = None
            pending_start = None
            pending_duration = 0.0
            continue

        if pending_count != count:
            pending_count = count
            pending_start = start
            pending_duration = 0.0

        pending_before = pending_duration
        pending_duration += dt
        if pending_duration >= stable_s and pending_start is not None:
            confirm_offset = stable_s - pending_before
            confirmed_ts = start + max(0.0, confirm_offset)
            change_ts = pending_start
            segments.append(
                PeopleCountSegment(
                    start_ts_s=segment_start,
                    end_ts_s=change_ts,
                    duration_s=max(0.0, change_ts - segment_start),
                    people_count=current_count,
                    context_in_session=_in_session(change_ts, sessions),
                )
            )
            events.append(
                PeopleCountChangeEvent(
                    from_count=current_count,
                    to_count=pending_count,
                    change_ts_s=change_ts,
                    confirmed_ts_s=confirmed_ts,
                    context_in_session=_in_session(change_ts, sessions),
                )
            )
            current_count = pending_count
            segment_start = change_ts
            pending_count = None
            pending_start = None
            pending_duration = 0.0

    last_ts = frames[-1].ts_s
    segments.append(
        PeopleCountSegment(
            start_ts_s=segment_start,
            end_ts_s=last_ts,
            duration_s=max(0.0, last_ts - segment_start),
            people_count=current_count,
            context_in_session=None,
        )
    )

    split_segments: List[PeopleCountSegment] = []
    for segment in segments:
        boundaries = [segment.start_ts_s, segment.end_ts_s]
        for session in sessions:
            if session.end_ts_s <= segment.start_ts_s or session.start_ts_s >= segment.end_ts_s:
                continue
            boundaries.extend([session.start_ts_s, session.end_ts_s])
        boundaries = sorted({b for b in boundaries if segment.start_ts_s <= b <= segment.end_ts_s})
        for idx in range(len(boundaries) - 1):
            start = boundaries[idx]
            end = boundaries[idx + 1]
            if end <= start:
                continue
            in_session = _in_session((start + end) / 2.0, sessions)
            split_segments.append(
                PeopleCountSegment(
                    start_ts_s=start,
                    end_ts_s=end,
                    duration_s=max(0.0, end - start),
                    people_count=segment.people_count,
                    context_in_session=in_session,
                )
            )

    return split_segments, events


def build_report(
    frame_outputs: Iterable[FrameOutput],
    cfg: ReportConfig,
    source_path: str,
) -> Report:
    frames = [_frame_to_signal(output, cfg.fps_assume) for output in frame_outputs]

    presence_raw = _build_segments(frames, lambda f: f.people_count >= 1)
    presence_segments = [
        PresenceSegment(
            state="present" if state else "absent",
            start_ts_s=start,
            end_ts_s=end,
            duration_s=max(0.0, end - start),
            start_frame_idx=start_frame,
            end_frame_idx=end_frame,
        )
        for state, start, end, start_frame, end_frame in presence_raw
    ]

    observation_raw = _build_segments(frames, lambda f: f.open_state and not f.sampling_present)
    observation_segments = [
        ObservationSegment(
            start_ts_s=start,
            end_ts_s=end,
            duration_s=max(0.0, end - start),
            start_frame_idx=start_frame,
            end_frame_idx=end_frame,
        )
        for state, start, end, start_frame, end_frame in observation_raw
        if state is True
    ]

    sessions = _build_sessions(frames, cfg)

    crew_intervals: List[CrewInterval] = []
    session_crew_stats: List[SessionCrewStats] = []
    alarms: List[Alarm] = []

    for session in sessions:
        if cfg.enable_min_sampling_duration and session.duration_s < cfg.sampling_min_s:
            alarms.append(
                Alarm(
                    alarm_id=0,
                    alarm_type="SAMPLING_TOO_SHORT",
                    start_ts_s=session.start_ts_s,
                    end_ts_s=session.end_ts_s,
                    session_id=session.session_id,
                )
            )

    unblocked_alarm = _build_unblocked_alarm(frames, cfg)
    if unblocked_alarm is not None:
        alarms.append(unblocked_alarm)

    alarm_counts = {}
    for alarm in alarms:
        alarm_counts[alarm.alarm_type] = alarm_counts.get(alarm.alarm_type, 0) + 1

    overall_result = "FAIL" if alarms else "PASS"

    for idx, alarm in enumerate(alarms, start=1):
        alarm.alarm_id = idx

    header = ReportHeader(
        report_version="v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_path=source_path,
        models_used=["B", "C", "D", "E"],
    )

    people_count_segments, people_count_change_events = _build_people_count_segments(
        frames,
        sessions,
        stable_s=2.0,
    )

    people_counts = [frame.people_count for frame in frames] if frames else []
    min_people = min(people_counts) if people_counts else None
    max_people = max(people_counts) if people_counts else None

    return Report(
        header=header,
        config=cfg.to_data(),
        presence_segments=presence_segments,
        open_no_sampling_segments=observation_segments,
        sessions=sessions,
        crew_intervals=crew_intervals,
        session_crew_stats=session_crew_stats,
        people_count_segments=people_count_segments,
        people_count_change_events=people_count_change_events,
        alarms=alarms,
        summary=Summary(
            overall_result=overall_result,
            alarm_counts=alarm_counts,
            session_count=len(sessions),
            min_people_count=min_people,
            max_people_count=max_people,
            people_change_count=len(people_count_change_events),
        ),
    )
