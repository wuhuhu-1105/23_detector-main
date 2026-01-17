from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Optional

from src.core.device import resolve_device
from src.core.logging_spec import EFFECTIVE_CONFIG_FIELDS
from src.core.contracts import __version__ as contracts_version
from src.core.contracts.config import ReportConfig
from src.core.contracts.results import ReportExportResult
from src.core.paths import get_outputs_root
from src.launcher_settings import load_settings_with_meta
from src.runtime.file_dialog import pick_video_path
from src.services.report_service import ReportService, SERVICE_VERSION as report_service_version


def _build_parser() -> argparse.ArgumentParser:
    from src.report import ReportConfig

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Video path")
    parser.add_argument("--outdir", "--out", "--output-dir", dest="outdir", default=None)
    parser.add_argument("--format", choices=["json", "docx", "pdf", "all"], default="all")
    parser.add_argument("--export-video", action="store_true", help="Export overlay video")
    parser.add_argument("--video-out", default=None, help="Output path for overlay video")
    parser.add_argument("--no-boxes", action="store_true", help="Disable detection boxes overlay")
    parser.add_argument("--device", default=None, help="Inference device (e.g. cpu, cuda:0)")
    parser.add_argument("--device-mode", choices=["auto", "cpu", "gpu"], default="auto")
    parser.add_argument("--half", action="store_true", help="Enable FP16 inference when supported")
    parser.add_argument("--allow-network", dest="allow_network", action="store_true")
    parser.add_argument("--no-network", dest="allow_network", action="store_false")
    ReportConfig.add_cli_args(parser)
    parser.set_defaults(allow_network=False)
    return parser


def _ensure_runtime_defaults(args: argparse.Namespace) -> None:
    defaults = {
        "enable_b": None,
        "enable_c": None,
        "enable_d": None,
        "enable_e": None,
        "off_mode_b": None,
        "off_mode_c": None,
        "off_mode_d": None,
        "inject_people_count": None,
        "inject_tags_c": "",
        "inject_tags_d": "",
        "imgsz": None,
        "c_imgsz": None,
        "c_iou": None,
        "c_conf_close": None,
        "c_conf_sampling": None,
        "c_max_det": None,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def _log_line(message: str) -> None:
    print(message)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _read_stats(path: str) -> dict:
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_stats_atomic(path: str, data: dict) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def _default_outputs_root() -> str:
    return get_outputs_root()


def _build_report_config(args: argparse.Namespace) -> ReportConfig:
    overrides = {
        "enable_min_sampling_duration": bool(args.enable_min_sampling_duration),
        "sampling_min_s": float(args.sampling_min_s),
        "people_grace_s": float(args.people_grace_s),
        "unblocked_alarm_s": float(args.unblocked_alarm_s),
        "gap_allow_unblocked_s": float(args.gap_allow_unblocked_s),
        "sampling_start_s": float(args.sampling_start_s),
        "sampling_end_s": float(args.sampling_end_s),
        "gap_allow_sampling_s": float(args.gap_allow_sampling_s),
        "fps_assume": float(args.fps_assume),
        "device_mode": getattr(args, "device_mode", "auto"),
        "cuda_available": getattr(args, "cuda_available", None),
        "cuda_reason": getattr(args, "cuda_reason", ""),
    }
    return ReportConfig(
        outdir=args.outdir,
        format=args.format,
        export_video=bool(args.export_video),
        video_out=args.video_out,
        no_boxes=bool(args.no_boxes),
        device=args.device,
        device_mode=getattr(args, "device_mode", "auto"),
        half=bool(args.half),
        allow_network=bool(args.allow_network),
        overrides=overrides,
    )


def _result_to_info(result: ReportExportResult) -> dict:
    return {
        "outputs_root": result.outputs_root,
        "reports_dir": result.reports_dir,
        "report_dir": result.report_dir,
        "run_id": result.run_id,
        "docx": result.docx_path,
        "mp4": result.overlay_path,
        "jsonl": result.run_jsonl,
        "json": result.report_json,
        "pdf": result.pdf_path,
        "last_fps": result.last_fps,
    }


def _result_summary(result: ReportExportResult, source: Optional[str] = None) -> str:
    parts = [
        "report_export_result:",
        f"source={source or '-'}",
        f"run_id={result.run_id or '-'}",
        f"reports_dir={result.reports_dir}",
        f"report_dir={result.report_dir}",
        f"json={result.report_json}",
        f"jsonl={result.run_jsonl}",
    ]
    if result.docx_path:
        parts.append(f"docx={result.docx_path}")
    if result.overlay_path:
        parts.append(f"mp4={result.overlay_path}")
    if result.pdf_path:
        parts.append(f"pdf={result.pdf_path}")
    return " ".join(parts)


def _run_gui_export(parser: argparse.ArgumentParser) -> int:
    from PyQt6.QtCore import QThread, pyqtSignal
    from PyQt6.QtWidgets import (
        QApplication,
        QFileDialog,
        QLabel,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    def _pick_video_qt() -> Optional[str]:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select video file",
            "",
            "Video files (*.mp4 *.avi);;All files (*.*)",
        )
        return path or None

    if len(sys.argv) == 1:
        app = QApplication(sys.argv)
        selected = _pick_video_qt()
        if not selected:
            QMessageBox.information(None, "Report Exporter", "No video selected. Exiting.")
            return 0
        args = parser.parse_args(["--source", selected])
    else:
        args = parser.parse_args()
        app = QApplication(sys.argv)

    _ensure_runtime_defaults(args)
    outputs_root = args.outdir or _default_outputs_root()
    log_path = os.path.join(outputs_root, "export.log")
    run_id = uuid.uuid4().hex
    log_file = open(log_path, "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
    _log_line(
        "run_start "
        f"run_id={run_id} "
        f"contracts_version={contracts_version} "
        "service=report "
        f"service_version={report_service_version} "
        f"source={args.source} "
        f"device={args.device or 'auto'} "
        f"device_mode={getattr(args, 'device_mode', 'auto')}"
    )

    class ExportWorker(QThread):
        progress = pyqtSignal(int, int, float, object, str)
        finished = pyqtSignal(int, dict)

        def run(self) -> None:
            cfg = _build_report_config(args)
            cfg.use_tqdm = False
            cfg.log_fn = _log_line
            cfg.run_id = run_id
            service = ReportService()
            service.on_progress(lambda e: self.progress.emit(e.done_frames, e.total_frames, e.fps, e.eta_s, e.stage))
            try:
                result = service.export(args.source, cfg)
                info = _result_to_info(result)
                self.finished.emit(0, info)
            except Exception:
                self.finished.emit(1, {})

    window = QWidget()
    window.setWindowTitle("Report Exporter")
    layout = QVBoxLayout(window)
    label_progress = QLabel("Preparing...")
    label_reports = QLabel("reports_dir: (pending)")
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 0)
    layout.addWidget(label_progress)
    layout.addWidget(progress_bar)
    layout.addWidget(label_reports)

    worker = ExportWorker()

    def _format_eta(eta: Optional[float]) -> str:
        if eta is None:
            return "--"
        eta = max(0, int(eta))
        mm, ss = divmod(eta, 60)
        hh, mm = divmod(mm, 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def _on_progress(done: int, total: int, fps: float, eta: Optional[float], stage: str) -> None:
        if stage == "pdf":
            progress_bar.setRange(0, 0)
            label_progress.setText("正在生成 PDF...")
            return
        if total > 0:
            progress_bar.setRange(0, total)
            progress_bar.setValue(done)
            pct = (done / total) * 100.0
            label_progress.setText(
                f"frame {done}/{total} | {fps:.2f} fps | ETA {_format_eta(eta)} | {pct:.1f}%"
            )
        else:
            progress_bar.setRange(0, 0)
            label_progress.setText(f"frame {done}/? | {fps:.2f} fps | ETA --")

    def _on_finished(code: int, info: dict) -> None:
        if code == 0:
            reports_dir = info.get("reports_dir") or ""
            box = QMessageBox(window)
            box.setWindowTitle("Export completed")
            box.setText("Report export completed.")
            open_btn = QPushButton("Open output folder")
            close_btn = QPushButton("Close")
            box.addButton(open_btn, QMessageBox.ButtonRole.AcceptRole)
            box.addButton(close_btn, QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == open_btn:
                if reports_dir:
                    os.startfile(reports_dir)
        else:
            QMessageBox.critical(window, "Export failed", f"Export failed (code {code}).")
        app.quit()

    worker.progress.connect(_on_progress)
    worker.finished.connect(_on_finished)
    window.show()
    worker.start()
    return app.exec()


def main() -> int:
    from src.core.encoding import ensure_utf8_stdio

    ensure_utf8_stdio()
    parser = _build_parser()
    if getattr(sys, "frozen", False):
        return _run_gui_export(parser)

    if len(sys.argv) == 1:
        selected = pick_video_path()
        if not selected:
            print("No video selected. Exiting.")
            return 0
        args = parser.parse_args(["--source", selected])
    else:
        args = parser.parse_args()

    _ensure_runtime_defaults(args)

    outputs_root = args.outdir or _default_outputs_root()
    run_id = uuid.uuid4().hex

    settings, downgraded = load_settings_with_meta(outputs_root)
    if downgraded:
        log_path = os.path.join(outputs_root, "export.log")
        msg = "settings_downgrade: Ultra -> High"
        _log_line(msg)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

    def _flag_present(flag: str) -> bool:
        return flag in sys.argv

    if args.device is None and args.device_mode == "auto" and settings.device_mode and not _flag_present("--device-mode"):
        args.device_mode = settings.device_mode

    if args.device:
        resolved_device = args.device
        device_mode = "manual"
        cuda_available = None
        cuda_reason = ""
    else:
        resolved_device, cuda_available, cuda_reason = resolve_device(args.device_mode)
        device_mode = args.device_mode
    args.device = resolved_device
    setattr(args, "device_mode", device_mode)
    setattr(args, "cuda_available", cuda_available)
    setattr(args, "cuda_reason", cuda_reason)

    log_path = os.path.join(outputs_root, "export.log")
    def _log(message: str) -> None:
        _log_line(message)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except OSError:
            pass

    _log(
        "run_start "
        f"run_id={run_id} "
        f"contracts_version={contracts_version} "
        "service=report "
        f"service_version={report_service_version} "
        f"source={args.source} "
        f"device={args.device or 'auto'} "
        f"device_mode={getattr(args, 'device_mode', 'auto')}"
    )

    def _param_source(flag: str) -> str:
        return "cli" if _flag_present(flag) else "default"

    values = {
        "device": (resolved_device, device_mode),
        "imgsz": (args.imgsz, _param_source("--imgsz")),
        "c_imgsz": (args.c_imgsz, _param_source("--c-imgsz")),
        "people_grace_s": (args.people_grace_s, _param_source("--people-grace-s")),
        "unblocked_alarm_s": (args.unblocked_alarm_s, _param_source("--unblocked-alarm-s")),
        "sampling_min_s": (args.sampling_min_s, _param_source("--sampling-min-s")),
    }
    parts = ["effective_config:", f"run_id={run_id}"]
    for key in EFFECTIVE_CONFIG_FIELDS:
        value, source = values[key]
        parts.append(f"{key}={value}(source={source})")
    parts.append(f"contracts_version={contracts_version}")
    parts.append(f"service_version={report_service_version}")
    effective_msg = " ".join(parts)
    _log(effective_msg)

    cfg = _build_report_config(args)
    cfg.use_tqdm = True
    cfg.log_fn = _log
    cfg.run_id = run_id

    progress_seen = {"stages": set()}

    def _on_progress(ev) -> None:
        if ev.stage in progress_seen["stages"]:
            return
        progress_seen["stages"].add(ev.stage)
        msg = f" message={ev.message}" if getattr(ev, "message", None) else ""
        _log(
            f"progress_event: run_id={ev.run_id} done={ev.done_frames} total={ev.total_frames} "
            f"fps={ev.fps:.2f} eta={ev.eta_s} stage={ev.stage}{msg}"
        )

    service = ReportService()
    service.on_progress(_on_progress)
    try:
        result = service.export(args.source, cfg)
    except Exception as exc:
        _log(f"[EXPORT] {exc}")
        return 4

    _log(_result_summary(result, source=args.source))

    if result.last_fps:
        stats_path = os.path.join(outputs_root, "export_stats.json")
        key = "last_export_fps_gpu" if resolved_device == "cuda" else "last_export_fps_cpu"
        data = _read_stats(stats_path)
        data[key] = round(float(result.last_fps), 2)
        try:
            _write_stats_atomic(stats_path, data)
            _log(f"stats_path: {stats_path}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
