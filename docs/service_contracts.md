# Service Contracts (Field List + Compatibility Mapping)

## v0.1 Contracts Freeze
- Field names and semantics are frozen.
- Only additive optional fields are allowed (backward compatible).
- Any breaking change requires a version bump and dual review.
Import boundary is enforced by CI via `tools/check_service_imports.py` (realtime/report must not import each other).

This document defines new service-layer DTOs and how they map to existing runtime fields.

Local smoke (guard + A/B): see `tools/smoke_local.md`.
Optional one-click runner: `python tools/smoke_local.py`

Implementation note (non-contract):
- Realtime lifecycle/dispatch lives under `D:\23_detector\src\services\realtime_impl\` (compat shells in `D:\23_detector\src\runtime\runner.py` and `D:\23_detector\src\ui_qt\worker.py`).
- Report export orchestration lives under `D:\23_detector\src\services\report_impl\` (compat shell in `D:\23_detector\src\report\export_core.py`).

## Event DTOs

### `core.contracts.events.RealtimeEvent`
Fields:
- `event_type`: `"frame" | "error" | "finished"`
- `run_id` (optional): per-run identifier
- `ts_s`: float, video time in seconds (from metrics or timestamp fallback)
- `source`: str, video path
- `frame_index`: int
- `fps`: float
- `state_raw`: str
- `state_5class`: str
- `state_cn`: str
- `duration_s`: float
- `people_count`: int
- `people_ok`: bool
- `tags_c`: list[str]
- `tags_d`: list[str]
- `metrics`: dict (raw metrics passthrough)
- `message`: str (only for `error`)

### `core.contracts.events.ReportProgressEvent`
Fields:
- `event_type`: `"progress"`
- `run_id` (optional): per-run identifier
- `source`: str
- `done_frames`: int
- `total_frames`: int
- `fps`: float
- `eta_s`: float
- `stage`: `"load" | "infer" | "write_json" | "write_jsonl" | "write_docx" | "write_pdf" | "write_video" | "video" | "pdf"`
- `percent`: float (derived)
- `done` / `total` (optional aliases)
- `message` (optional)

## Config DTOs

### `core.contracts.config.RealtimeConfig`
- `device`, `device_mode`, `display_fps`, `rt_smooth`, `target_ratio`, `no_overlay`
- `dynamic_skip`, `perf_log`, `max_fps`, `infer_every`
- `allow_network`, `debug`

### `core.contracts.config.ReportConfig`
- `outdir`, `outputs_root`, `reports_dir`, `report_dir`
- `format`, `export_video`, `video_out`, `no_boxes`
- `device`, `device_mode`, `half`, `allow_network`
- `use_tqdm` (optional): enable/disable progress bars
- `log_fn` (optional): log sink (e.g. print or file)
- `run_id` (optional): per-run identifier
- `overrides`: pass-through for ReportConfig CLI args

## Result DTOs

### `core.contracts.results.ReportExportResult`
- `outputs_root`, `reports_dir`, `report_dir`
- `report_json`, `run_jsonl`
- `docx_path`, `overlay_path`, `pdf_path`
- `run_id` (optional)
- `last_fps`

## Compatibility Mapping (Old -> New)

Realtime:
| Old Field | New Field |
| --- | --- |
| `FrameOutput.frame_index` | `RealtimeEvent.frame_index` |
| `FrameOutput.fps` | `RealtimeEvent.fps` |
| `FrameOutput.state` | `RealtimeEvent.state_raw` |
| `FrameOutput.state_duration_sec` | `RealtimeEvent.duration_s` |
| `FrameOutput.metrics["video_t_s"]` | `RealtimeEvent.ts_s` |
| `FrameOutput.timestamp_ms` | `RealtimeEvent.ts_s` (fallback) |
| `FrameOutput.metrics["people_count"]` | `RealtimeEvent.people_count` |
| `FrameOutput.metrics["people_ok"]` | `RealtimeEvent.people_ok` |
| `FrameOutput.metrics["tags_c"]` | `RealtimeEvent.tags_c` |
| `FrameOutput.metrics["tags_d"]` | `RealtimeEvent.tags_d` |
| `StatusDTO.state_5class` | `RealtimeEvent.state_5class` (derived) |
| `StatusDTO.state_cn` | `RealtimeEvent.state_cn` (derived) |
| `VideoWorker.error(str)` | `RealtimeEvent.event_type="error", message=str` |

Report progress:
| Old Field | New Field |
| --- | --- |
| `progress_cb(done, total, fps, eta, stage)` | `ReportProgressEvent(done_frames, total_frames, fps, eta_s, stage)` |
| `total > 0` | `ReportProgressEvent.percent = done/total*100` |

Report outputs:
| Old Field | New Field |
| --- | --- |
| `info["json"]` | `ReportExportResult.report_json` |
| `info["jsonl"]` | `ReportExportResult.run_jsonl` |
| `info["docx"]` | `ReportExportResult.docx_path` |
| `info["mp4"]` | `ReportExportResult.overlay_path` |
| `info["pdf"]` | `ReportExportResult.pdf_path` |
| `info["last_fps"]` | `ReportExportResult.last_fps` |
| `info["reports_dir"]` | `ReportExportResult.reports_dir` |
| `info["report_dir"]` | `ReportExportResult.report_dir` |

Settings:
| Old Field | New Field |
| --- | --- |
| `launcher_settings.LauncherSettings.device_mode` | `settings_schema.LauncherSettings.device_mode` |
| `launcher_settings.LauncherSettings.offline_quality` | `settings_schema.LauncherSettings.offline_quality` |
| `launcher_settings.LauncherSettings.realtime_mode` | `settings_schema.LauncherSettings.realtime_mode` |
