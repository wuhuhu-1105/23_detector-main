# 23_detector

## Run (PyQt6 UI default)
```
python -m src.app_qt --source path/to/video.mp4
python -m src.app_qt --source path/to/video.mp4 --dynamic-skip
```

## Run (headless pipeline)
```
python -m src.app_qt --headless --source path/to/video.mp4 --save-video out/demo.mp4
```

## Run (report generation, offline)
```
python -m src.cli.report_gen --source "D:\path\to\video.mp4"
python -m src.cli.report_gen --source "D:\path\to\video.mp4" --format docx
python -m src.cli.report_gen --source "D:\path\to\video.mp4" --device-mode gpu
```

## Run (report + overlay video)
```
python -m src.cli.report_gen --source "D:\path\to\video.mp4" --export-video
python -m src.cli.report_gen --source "D:\path\to\video.mp4" --export-video --video-out "D:\out\overlay_demo.mp4" --no-boxes
```

## Import self-check
```
python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"
```

## Module path self-check
```
python -c "import src.app_qt,inspect,os; print(os.path.abspath(inspect.getfile(src.app_qt)))"
```

## Notes
- Install deps: `pip install -r requirements.txt`
- Recommended entry: `python -m src.app_qt ...`
- Report deps: `python-docx`, `tqdm`, `opencv-python`, `docx2pdf` (Windows requires Microsoft Word for PDF export; LibreOffice `soffice` is accepted as a fallback)
- Packaged version (scheme A) defaults to CPU unless `--device` is explicitly provided.
- Launcher provides device selection (auto/cpu/gpu) and shows CUDA availability + final device.
- `python -m src.app_qt -h` works without torch; actual inference requires torch.
- UI panel shows current state and duration.
- UI options: `--infer-every N`, `--max-fps FPS`, `--no-overlay`
- Display options: `--display-fps 15` (smooth UI refresh; repeats latest frame if infer is slower)
- Real-time metric: `RealTime Ratio` shows video-time / wall-time speed (closer to 1.0 is real-time).
- Scheduler tuning: `--target-ratio 1.0` (1.0 = aim real-time; 0.8 = smoother/slower; 1.2 = more aggressive catch-up)
- Auto tuning: `--auto-target` adjusts target ratio based on real-time ratio drift.
- Perf logging: `--perf-log` prints key=value PERF lines once per second.
- Save size: `--save-size 1280,720` or `--save-size 1280x720`
- Test outputs: `--test` writes `out/run_*.jsonl` and `out/summary.json`; otherwise headless prints JSON to stdout only.
- Dynamic-skip path reads via `cv2.VideoCapture` and `PipelineRunner` (bypasses `VideoSource/iter_frame_outputs`).

## Programs (what each one does)
- `python -m src.app_qt`: Main entry. UI by default, headless with `--headless`.
- `python -m src.runtime.app_runtime`: Headless-only entry (test/log/summary).
- `python -m src.cli.report_gen`: Offline report generator (JSON/DOCX/PDF + optional overlay video).
- `python -m src.launcher`: Launcher UI (Home/Realtime/Export flow).
- `python -m src.runtime.runner`: Internal runtime runner (normally called by `src.app_qt`).
- `tools/dynamic_skip_infer.py`: Standalone dynamic-skip demo/analysis tool.
- `tools/summarize_run.py`: Summarize latest `run_*.jsonl` into averages/table.

## Dynamic frame skipping tool
```
python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"
```

## FrameScheduler (model-speed adaptive)
FrameScheduler adapts frame stepping based on measured inference time, so you do not need to change code when the model or hardware speed changes.
Example:
```
python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"
```

## Module layout (lightweight)
- core: configs/types (no UI/runtime deps)
- detectors/filters/engine: model logic and state machine
- io: video I/O helpers
- runtime: orchestration, schedulers, adapters, logger, pipeline entry (no UI widget code)
- report: report builder + writers + video export
- ui_qt: PyQt6 UI only (depends on runtime + core)
Dependency direction: core <- detectors/filters/engine/io <- runtime <- ui_qt

## Output Layout
Example (first and second run on the same day):
```
D:\23_detector\outputs\reports_0115_01\report_6F_1-cut2.docx
D:\23_detector\outputs\reports_0115_01\overlay_6F_1-cut2.mp4
D:\23_detector\outputs\reports_0115_01\report\run_6F_1-cut2.jsonl
D:\23_detector\outputs\reports_0115_01\report\report_6F_1-cut2.json
D:\23_detector\outputs\reports_0115_01\report\report_6F_1-cut2.pdf

D:\23_detector\outputs\reports_0115_02\report_6F_1-cut2.docx
D:\23_detector\outputs\reports_0115_02\overlay_6F_1-cut2.mp4
D:\23_detector\outputs\reports_0115_02\report\run_6F_1-cut2.jsonl
D:\23_detector\outputs\reports_0115_02\report\report_6F_1-cut2.json
D:\23_detector\outputs\reports_0115_02\report\report_6F_1-cut2.pdf
```
Notes:
- `reports_MMDD_NN` uses local date for `MMDD`, and `NN` increments from `01`.
- Human-readable outputs are in the report root; JSON/JSONL are in `report/`.
- Three-file set: `report_<video_stem>.docx`, `overlay_<video_stem>.mp4`, `run_<video_stem>.jsonl`.
- Frozen exporter log: `outputs\export.log` (ReportExporter.exe default log).

Report data files under `reports_MMDD_NN\report\`:
- Required: `report_<stem>.json`, `run_<stem>.jsonl`
- Optional: `report_<stem>.pdf`, `frames_meta_<stem>.jsonl`
- Any future structured outputs must also live under `report\`.

## Launcher Export Flow
Home ? ???? ? ??? ? Confirm???+?????? Progress???+ETA?? ???? ? ? Home?
??????????????????? `outputs\export.log` ?? `aborted_by_user`?
?????Home ??? auto/cpu/gpu???? CUDA ????????????
?????`outputs\export_stats.json`??? `last_export_fps_cpu/last_export_fps_gpu`??
??????????????????High????? `outputs\launcher_settings.json`???????????
Ultra ???????????? High?????? Ultra ?????????

## CLI Priority Rules
Explicit CLI args take priority, then launcher settings (when CLI args are not provided), then built-in defaults.
CLI logs an `effective_config` line with the resolved device and key parameters plus their sources.

## Offline Mode (default)
Default is offline (`--no-network`): no auto-downloads are allowed. If weights are missing, the program fails fast with a clear error.
To allow downloads, use `--allow-network` explicitly.

Example (CLI):
```
python -m src.cli.report_gen --source "D:\path\to\video.mp4" --allow-network
```
For double-click (EXE) runs, use the command line if you need `--allow-network`.

## Packaging (PyInstaller onedir)
Install PyInstaller in the detector environment:
```
pip install pyinstaller
```

Build DetectorUI (windowed, no console):
```
pyinstaller --noconfirm --onedir --windowed --name DetectorUI ^
  --collect-all PyQt6 --collect-all cv2 --collect-all ultralytics --collect-all torch --collect-all torchvision ^
  --add-data "best;best" src\app_qt.py
```

Build ReportExporter (windowed, no console; logs to outputs/export.log):
```
pyinstaller --noconfirm --onedir --windowed --name ReportExporter ^
  --collect-all PyQt6 --collect-all cv2 --collect-all ultralytics --collect-all torch --collect-all torchvision ^
  --add-data "best;best" src\cli\report_gen.py
```
Notes:
- Frozen ReportExporter shows a progress dialog and writes logs to `outputs\export.log`.
