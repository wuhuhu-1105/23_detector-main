LOG_ORDER = (
    "event",
    "frame",
    "step",
    "capped",
    "next_idx",
    "dropped",
    "t_read_ms",
    "t_drop_ms",
    "t_infer_ms",
    "t_emit_ms",
    "fps_est",
    "dt_ms",
    "dt_smooth_ms",
    "throughput_fps",
    "video_fps",
    "raw_step",
    "raw_step_smooth",
    "target_ratio",
    "ratio",
)

PERF_FIELDS = (
    "frame_index",
    "t_read_ms",
    "t_drop_ms",
    "t_infer_ms",
    "t_emit_ms",
    "fps_est",
    "throughput_fps",
    "video_fps",
    "rt_ratio",
    "target_ratio",
    "perf_ms",
    "stage_ms",
)

EVENT_FIELDS = (
    "event_type",
    "ts_s",
    "source",
    "frame_index",
    "state_5class",
    "people_count",
)

EFFECTIVE_CONFIG_FIELDS = (
    "device",
    "imgsz",
    "c_imgsz",
    "people_grace_s",
    "unblocked_alarm_s",
    "sampling_min_s",
)
