from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple


def finalize_summary(
    segments: List[Tuple[str, float, float]],
    transitions: List[Tuple[str, str, float]],
    short_jitter_s: float,
    close_open_warn: int,
    close_open_fail: int,
    short_jitter_warn: int,
    short_jitter_fail: int,
    max_transitions_per_sec: int,
) -> Dict[str, Any]:
    state_counts = Counter()
    state_durations_ms = defaultdict(float)
    for state, start_ms, end_ms in segments:
        state_counts[state] += 1
        state_durations_ms[state] += max(0.0, end_ms - start_ms)

    transition_pairs = Counter()
    close_open_switches = 0
    for prev_state, next_state, _ in transitions:
        transition_pairs[(prev_state, next_state)] += 1
        if (prev_state == "CLOSE") != (next_state == "CLOSE"):
            close_open_switches += 1

    short_jitter_count = sum(
        1 for state, start_ms, end_ms in segments if (end_ms - start_ms) / 1000.0 < short_jitter_s
    )

    per_sec_switches = Counter()
    for _, _, t_ms in transitions:
        per_sec_switches[int(t_ms // 1000)] += 1
    max_switches_per_sec = max(per_sec_switches.values()) if per_sec_switches else 0

    status = "PASS"
    if (
        short_jitter_count > short_jitter_fail
        or close_open_switches > close_open_fail
        or max_switches_per_sec > max_transitions_per_sec
    ):
        status = "FAIL"
    elif short_jitter_count > short_jitter_warn or close_open_switches > close_open_warn:
        status = "WARN"

    top_pairs = [{"from": k[0], "to": k[1], "count": v} for k, v in transition_pairs.most_common(5)]

    anomalies = []
    for state, start_ms, end_ms in segments:
        if (end_ms - start_ms) / 1000.0 < short_jitter_s:
            anomalies.append({"start_ms": start_ms, "end_ms": end_ms, "reason": "short_state"})
    if max_switches_per_sec > max_transitions_per_sec:
        for sec, count in per_sec_switches.items():
            if count > max_transitions_per_sec:
                anomalies.append(
                    {
                        "start_ms": sec * 1000,
                        "end_ms": (sec + 1) * 1000,
                        "reason": "high_switch_rate",
                    }
                )

    return {
        "state_entries": dict(state_counts),
        "state_durations_ms": dict(state_durations_ms),
        "transition_count": sum(transition_pairs.values()),
        "top_transitions": top_pairs,
        "short_jitter_count": short_jitter_count,
        "close_open_switches": close_open_switches,
        "max_switches_per_sec": max_switches_per_sec,
        "status": status,
        "anomalies": anomalies[:10],
    }


def print_test_report(
    source: str,
    total_frames: int,
    duration_ms: float,
    summary: Dict[str, Any],
    state_durations_ms: Dict[str, float],
    short_jitter_s: float,
) -> None:
    durations_sorted = sorted(state_durations_ms.items(), key=lambda kv: kv[1], reverse=True)
    top3 = ", ".join([f"{k} {v/1000.0:.1f}s" for k, v in durations_sorted[:3]])
    print("TEST REPORT")
    print(f"Source: {source}")
    print(f"Frames: {total_frames} Duration: {duration_ms/1000.0:.1f}s")
    print(f"Transitions: {summary.get('transition_count', 0)}")
    print(f"Top states: {top3}")
    print(f"Short jitter (<{short_jitter_s:.1f}s): {summary.get('short_jitter_count', 0)}")
    print(f"Result: {summary.get('status', 'N/A')}")
