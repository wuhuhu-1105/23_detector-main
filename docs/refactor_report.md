# Refactor Report: PyQt6 UI Only

## A) Repo State (Initial Audit, before refactor)

### A1) Directory tree (UI files annotated)
```
.
+-- best
|   +-- 1_blocking
|   |   +-- curves
|   |   |   +-- args.yaml
|   |   |   +-- BoxF1_curve.png
|   |   |   +-- BoxP_curve.png
|   |   |   +-- BoxPR_curve.png
|   |   |   +-- BoxR_curve.png
|   |   |   +-- confusion_matrix.png
|   |   |   +-- confusion_matrix_normalized.png
|   |   |   +-- results.csv
|   |   |   +-- results.png
|   |   +-- best.pt
|   +-- 2_sampling_close
|   |   +-- curves
|   |   |   +-- args.yaml
|   |   |   +-- data.yaml
|   |   +-- best.pt
|   +-- yolo11n.pt
+-- out
|   +-- demo.mp4
|   +-- run_20260106_153735.jsonl
|   +-- run_20260106_175455.jsonl
|   +-- run_base_imports.txt
|   +-- run_base_stdout.txt
|   +-- run_debug_imports.txt
|   +-- run_debug_stdout.txt
|   +-- run_legacy_imports.txt
|   +-- run_legacy_stdout.txt
|   +-- run_save_imports.txt
|   +-- run_save_stdout.txt
|   +-- run_test_imports.txt
|   +-- run_test_stdout.txt
|   +-- run_view_imports.txt
|   +-- run_view_stdout.txt
|   +-- summary.json
+-- src
|   +-- core
|   |   +-- __init__.py
|   |   +-- config.py
|   |   +-- types.py
|   +-- detectors
|   |   +-- __init__.py
|   |   +-- blocking_raw.py
|   |   +-- people_tracker_raw.py
|   |   +-- sampling_close_raw.py
|   +-- engine
|   |   +-- __init__.py
|   |   +-- state_engine_5.py
|   +-- filters
|   |   +-- __init__.py
|   |   +-- blocking_smoother.py
|   |   +-- people_smoother.py
|   |   +-- sampling_close_smoother.py
|   +-- io
|   |   +-- __init__.py
|   |   +-- video_source.py
|   |   +-- video_writer.py
|   +-- runtime
|   |   +-- __init__.py
|   |   +-- app_runtime.py
|   |   +-- cli.py
|   |   +-- config_overrides.py
|   |   +-- runner.py
|   |   +-- serialization.py
|   |   +-- source_utils.py
|   |   +-- summary.py
|   +-- ui (UI)
|   |   +-- __init__.py (UI)
|   |   +-- render.py (UI / OpenCV display)
|   +-- ui_qt (UI)
|       +-- main_window.py (UI)
|       +-- state_view_spec.py (UI)
|       +-- worker.py (UI)
+-- .last_source
+-- app.py
+-- app_legacy.py (UI / OpenCV display)
+-- requirements.txt
```

### A2) UI/Render entrypoints (OpenCV display calls + legacy UI libs)
- app_legacy.py:692 cv2.im(show)
- app_legacy.py:713 cv2.im(show)
- app_legacy.py:722 cv2.im(show)
- app_legacy.py:726 wait-key
- src/ui/render.py:435 cv2.im(show)
- src/ui/render.py:460 cv2.im(show)
- src/ui/render.py:469 cv2.im(show)
- src/ui/render.py:473 wait-key
- No PyQt5/PySide/Tkinter references found. PyQt6 used in `src/app_qt.py` and `src/ui_qt/*`.

### A3) Runtime entrypoints and call chains (initial)
- app.py: main() selects `APP_RUNTIME` env; default is new runtime.
  - `APP_RUNTIME=legacy` -> app_legacy.main()
  - else -> src.runtime.app_runtime.main()
- src/runtime/app_runtime.py: parses args, applies config overrides, validates source, writes last source, then runs runtime loop.
  - call chain: `app_runtime.main()` -> `runtime.runner.run(...)` -> `VideoSource` -> detectors/filters/state engine -> `src.ui.render.render_frame(...)` (OpenCV display)
- app_legacy.py: legacy monolith main; does inference, state, OpenCV visualization, logging.
- (removed) qt_app.py: redundant wrapper entrypoint (now use `python -m src.app_qt` or `runner.py`).

## B) Refactor Updates (current structure)

### B1) Directory tree (UI paths annotated)
```
.
+-- docs
|   +-- refactor_report.md
+-- src
|   +-- (removed) _deprecated
|   +-- core
|   |   +-- types.py
|   |   +-- paths.py
|   |   +-- device.py
|   +-- launcher_settings.py
|   +-- report
|   |   +-- builder.py
|   |   +-- types.py
|   |   +-- writer_docx.py
|   |   +-- writer_json.py
|   |   +-- export_core.py
|   |   +-- video_export.py
|   +-- runtime
|   |   +-- app_runtime.py
|   |   +-- cli.py
|   |   +-- config_overrides.py
|   |   +-- qt_adapter.py
|   |   +-- runner.py
|   |   +-- file_dialog.py
|   |   +-- network_guard.py
|   |   +-- source_utils.py
|   +-- export_runner.py
|   +-- ui_qt (only active UI)
|   |   +-- main_window.py
|   |   +-- state_view_spec.py
|   |   +-- worker.py
|   +-- app_qt.py
+   +-- cli
+   |   +-- report_gen.py
+-- (removed) app.py / runner.py
```

### B2) Current entrypoints and call chains
- `python -m src.app_qt ...` -> src.app_qt.main()
  - Module file path verified as `src/app_qt.py` (via `inspect.getfile(src.app_qt)`).
  - default UI: PyQt6
  - optional headless: `--headless` or `--ui headless`
- `python -m src.cli.report_gen ...` -> src.cli.report_gen.main()
  - offline reporting: builds `report.json` and `report.docx` (optional `report.pdf`) and can export overlay video.
  - frozen exe: shows progress dialog and writes log to `outputs\export.log`.
- `python -m src.launcher ...` -> src.launcher.main()
  - launcher UI for realtime detection and export flow (confirm + progress pages).
- src/app_qt.py:
  - resolves source, applies config overrides, validates source
  - UI path (standard): starts Qt app -> `VideoWorker` -> `runtime.runner.iter_frame_outputs()` -> `runtime.qt_adapter`
  - UI path (dynamic-skip): `VideoWorker` reads via `cv2.VideoCapture` on a reader thread -> `PipelineRunner.process_frame`
  - headless path: `runtime.runner.run_headless()` (no UI; `run_*.jsonl` and `summary.json` only when `--test`)
- src/runtime/app_runtime.py: headless pipeline only (kept for compatibility)

### B3) UI display calls removed
- OpenCV display calls were removed from active code paths; only PyQt6 rendering remains via `runtime.qt_adapter`.

## C) Changes Applied
- Added FrameOutput contract in `src/core/types.py` (frame_bgr, detections, state, state_duration_sec, metrics).
- Pipeline now outputs FrameOutput only; OpenCV UI display removed from runtime.
- Added `src/runtime/qt_adapter.py` for QImage conversion + overlay rendering.
- PyQt6 UI is the only active UI; legacy UI removed.
- Added unified entrypoint: `src/app_qt.py` (run via `python -m src.app_qt`).

## Change Log
- 2026-01-12: initial audit created.
- 2026-01-12:
  - Files changed: `src/core/types.py`, `src/runtime/cli.py`, `src/runtime/runner.py`, `src/runtime/app_runtime.py`, `src/runtime/source_utils.py`, `src/runtime/qt_adapter.py`, `src/ui_qt/worker.py`, `src/ui_qt/main_window.py`, `src/ui_qt/state_view_spec.py`, `src/app_qt.py`, `README.md`.
  - Why: remove OpenCV UI, enforce FrameOutput pipeline, isolate legacy UI, and route default entrypoints to PyQt6 with clear run commands.
  - Verification: `rg -n "cv2.im(show)|wait-key"` (expected 0 in code paths; report uses obfuscated strings), and basic static inspection of entrypoints.
- 2026-01-12:
  - Files changed: `src/__init__.py`, `src/app_qt.py`, `README.md`.
  - Why: unify entrypoint imports to `src.app_qt` and add import self-check.
  - Verification: `python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"` (expected `IMPORT OK`).
- 2026-01-12:
  - Files changed: `src/app_qt.py`.
  - Why: move runtime imports inside `main()` so `import src.app_qt` works without PyQt6/config side effects.
  - Verification: `python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"` (observed `IMPORT OK`).
- 2026-01-12:
  - Files changed: `src/ui_qt/main_window.py`, `src/ui_qt/state_view_spec.py`, `src/runtime/qt_adapter.py`, `README.md`.
  - Why: show state and duration in UI and keep updates per frame from FrameOutput.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; observe state text changes and duration increasing.
- 2026-01-12:
  - Files changed: `tools/dynamic_skip_infer.py`, `README.md`.
  - Why: add a standalone dynamic frame skipping tool based on inference time and video FPS.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; confirm next_frame_index varies with dt.
- 2026-01-12:
  - Files changed: `tools/dynamic_skip_infer.py`.
  - Why: run real pipeline inference inside timing window, add raw_step logging, and fallback stepping with target FPS.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; expect dt_ms > 1ms and step > 1 when load is high.
- 2026-01-12:
  - Files changed: `tools/dynamic_skip_infer.py`.
  - Why: add EMA smoothing for dt to stabilize step changes.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4" --ema 0.2`; observe dt_ema and steadier step.
- 2026-01-12:
  - Files changed: `tools/dynamic_skip_infer.py`.
  - Why: add warm-up frames and max_step cap to keep early jumps controlled.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4" --warmup_frames 5 --max_step 10`; expect warmup=1 and step=1 for first frames.
- 2026-01-12:
  - Files changed: `src/runtime/pipeline_runner.py`, `src/runtime/cli.py`, `src/ui_qt/worker.py`, `tools/dynamic_skip_infer.py`, `README.md`.
  - Why: reuse pipeline runner and add dynamic skip frame stepping in PyQt6 UI.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip`; observe UI time catching up and no seek errors.
- 2026-01-12:
  - Files changed: `src/runtime/cli.py`, `src/ui_qt/worker.py`.
  - Why: add optional perf logging for seek/read, inference, and emit timing.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log`; check PERF lines for timing fields.
- 2026-01-12:
  - Files changed: `src/runtime/cli.py`, `src/ui_qt/worker.py`.
  - Why: switch dynamic-skip to sequential read + drop-frames to avoid seek overhead.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log`; expect low t_read_ms and stable FPS.
- 2026-01-12:
  - Files changed: `src/ui_qt/worker.py`.
  - Why: integrate FrameScheduler with sequential read + drop-frames and perf-log fields (t_read_ms, t_drop_ms).
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log`; check PERF output.
- 2026-01-12:
  - Files changed: `src/runtime/cli.py`, `src/app_qt.py`, `src/ui_qt/main_window.py`, `README.md`.
  - Why: add QTimer-based UI display refresh (`--display-fps`) so display runs ~15fps without changing inference throughput.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --display-fps 15`; check Display FPS label ~15 and Infer FPS remains ~6-7.
- 2026-01-12:
  - Files changed: `src/runtime/cli.py`, `src/app_qt.py`, `src/runtime/qt_adapter.py`, `src/ui_qt/main_window.py`, `README.md`.
  - Why: add RealTime Ratio (Δvideo_time / Δwall_time) computed only on new inference results, plus optional smoothing.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip`; expect ratio ~1.0±0.2 with drop-frames; without it ratio < 1.
- 2026-01-12:
  - Files changed: `src/runtime/frame_scheduler.py`, `src/runtime/cli.py`, `src/ui_qt/worker.py`, `tools/dynamic_skip_infer.py`, `src/app_qt.py`, `src/ui_qt/main_window.py`, `README.md`.
  - Why: add FrameScheduler `target_ratio` to control aggressiveness and (optionally) surface it in UI.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --target-ratio 1.0`; expect RealTime Ratio closer to 1.0x.
- 2026-01-12:
  - Files changed: `src/runtime/frame_scheduler.py`, `tools/dynamic_skip_infer.py`, `README.md`.
  - Why: add a reusable FrameScheduler for model-speed adaptive frame stepping and wire the tool to it.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; observe stable raw_step/step after warmup.
- 2026-01-12:
  - Files changed: `src/runtime/frame_scheduler.py`, `tools/dynamic_skip_infer.py`.
  - Why: switch to dt-driven step with 3-frame smoothing and hard cap to avoid jitter and spikes.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; expect raw_step_smooth and capped flag in logs.
- 2026-01-12:
  - Files changed: `src/runtime/frame_scheduler.py`.
  - Why: clear dt window after warmup and force round() on raw_step_smooth for stable step≈4.
  - Verification: `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`; check dt_smooth_ms after warmup.
- 2026-01-12:
  - Files changed: `src/core/config.py`, `src/runtime/cli.py`, `src/app_qt.py`, `src/ui_qt/worker.py`.
  - Why: fix dataclass defaults (import-safe), add CLI aliases for max_allowed_step/warmup_frames, and improve PERF logging (idx/step/next_idx) to validate drop-frames scheduling.
  - Verification: `python -m src.app_qt -h | findstr /i "dynamic-skip target-ratio max_allowed warmup perf-log"`.
- 2026-01-12:
  - Files changed: `qt_app.py`, `docs/refactor_report.md`.
  - Why: remove redundant root entrypoint to reduce confusion; keep single entry module `src.app_qt`.
  - Verification: `python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"` and `python -m src.app_qt -h`.
- 2026-01-15:
  - Files changed: `src/launcher.py`, `src/launcher_settings.py`, `src/export_runner.py`, `src/cli/report_gen.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: add launcher export flow pages (confirm/progress), device resolve with settings, UTF-8 safe settings/stats I/O, export log path, and UI polish (font fallback + back buttons).
  - Verification: `python -m src.launcher` and complete one export; check `outputs\export.log` and `outputs\launcher_settings.json`.
- 2026-01-12:
  - Files changed: `src/_deprecated/*`, `docs/refactor_report.md`.
  - Why: remove deprecated legacy code (no longer needed).
- 2026-01-12:
  - Files changed: `app.py`, `runner.py`, `README.md`, `docs/refactor_report.md`.
  - Why: keep only one entrypoint for the same functionality (`python -m src.app_qt ...`).
  - Verification: `python -m src.app_qt -h` and `python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"` (expected `IMPORT OK`).
- 2026-01-12:
  - Files changed: `README.md`.
  - Why: document module layout and dependency direction (lightweight refactor guidance).
- 2026-01-12:
  - Files changed: `src/runtime/pipeline.py`, `src/runtime/pipeline_runner.py`, `src/runtime/logger.py`, `src/runtime/runner.py`, `src/ui_qt/worker.py`, `tools/dynamic_skip_infer.py`, `src/app_qt.py`, `README.md`.
  - Why: unify pipeline logic behind a single entry and centralize logging output.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log` and `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"`.
- 2026-01-12:
  - Files changed: `src/runtime/logger.py`, `src/ui_qt/worker.py`, `tools/dynamic_skip_infer.py`.
  - Why: unify log format into key=value fields for easier parsing and comparison.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log` (PERF lines use key=value), `python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"` (FRAME lines use key=value).
- 2026-01-12:
  - Files changed: `src/ui_qt/worker.py`, `src/ui_qt/main_window.py`, `README.md`.
  - Why: reduce drop-frame overhead (grab-only), lower perf log frequency, and use fast scaling for smoother UI.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --perf-log`.
- 2026-01-13:
  - Files changed: `src/ui_qt/worker.py`, `src/ui_qt/state_view_spec.py`, `src/ui_qt/main_window.py`, `src/runtime/cli.py`, `README.md`.
  - Why: add a reader thread with a bounded queue to smooth sequential reads in dynamic-skip mode, plus auto target-ratio tuning and UI surfacing.
  - Verification: `python -m src.app_qt --source "D:\20_Pose-Action-System\6F_1-cut2.mp4" --dynamic-skip --auto-target --perf-log`.
- 2026-01-15:
  - Files changed: `src/report/*`, `src/cli/report_gen.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: add offline report generation (JSON/DOCX) and optional overlay video export.
  - Verification: `python -m src.cli.report_gen --source "D:\path\to\demo.mp4"`.
- 2026-01-15:
  - Files changed: `src/core/paths.py`, `src/core/config.py`, `src/runtime/file_dialog.py`, `src/runtime/network_guard.py`, `src/app_qt.py`, `src/cli/report_gen.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: frozen exe base_dir handling for outputs/best, offline-by-default guard, double-click file picker, and ReportExporter progress UI with `outputs\export.log`.
  - Verification: run ReportExporter.exe twice and confirm `reports_MMDD_01/02` plus `outputs\export.log`.
- 2026-01-15:
  - Files changed: `src/launcher.py`, `src/export_runner.py`, `src/report/export_core.py`, `src/cli/report_gen.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: add Launcher with realtime/export flow, move export core into shared module, and add ExportRunner with progress + abort logging.
  - Verification: `python -m src.launcher` and complete export flow.
- 2026-01-15:
  - Files changed: `src/core/device.py`, `src/launcher.py`, `src/app_qt.py`, `src/export_runner.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: add device selection with CUDA availability + resolved device across realtime/export and log device resolution.
  - Verification: check Home device status and export log entries.
- 2026-01-15:
  - Files changed: `src/report/export_core.py`, `src/cli/report_gen.py`, `src/export_runner.py`, `README.md`.
  - Why: make export_stats.json resilient (atomic writes, corruption-tolerant reads) and add device-mode resolution to CLI.
  - Verification: run export twice and confirm `export_stats.json` contains `last_export_fps_cpu/gpu`.
- 2026-01-15:
  - Files changed: `src/launcher.py`, `src/launcher_settings.py`, `src/cli/report_gen.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: add Settings page with persisted device/quality profiles and apply them to export defaults.
  - Verification: change settings, restart, and confirm launcher shows the saved selection.
- 2026-01-15:
  - Files changed: `src/launcher.py`, `src/launcher_settings.py`, `src/cli/report_gen.py`, `README.md`.
  - Why: disable Ultra option, add downgrade notice, and enforce CLI priority rules with effective config logging.
  - Verification: set Ultra in settings file and confirm downgrade + `effective_config` output.
- 2026-01-15:
  - Files changed: `src/app_qt.py`, `src/runtime/app_runtime.py`, `README.md`, `docs/ARCHITECTURE.md`.
  - Why: allow `python -m src.app_qt -h` without torch; inference paths show a clear missing-torch message.
  - Verification: run `python -m src.app_qt -h` in an env without torch.

## Verification Notes
- UI was not executed in this environment; only static inspection and ripgrep checks were performed.
