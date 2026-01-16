from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from src.core.device import resolve_device
from src.launcher_settings import load_settings_with_meta
from src.report.export_core import (
    default_output_root,
    ensure_outdir,
    next_reports_dir,
    report_data_dir,
    run_export,
)
from src.runtime.file_dialog import pick_video_path


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
    outputs_root = args.outdir or default_output_root()
    reports_dir = next_reports_dir(outputs_root)
    report_dir = report_data_dir(reports_dir)
    ensure_outdir(outputs_root)
    ensure_outdir(reports_dir)
    ensure_outdir(report_dir)

    log_path = os.path.join(outputs_root, "export.log")
    log_file = open(log_path, "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

    class ExportWorker(QThread):
        progress = pyqtSignal(int, int, float, object, str)
        finished = pyqtSignal(int, dict)

        def run(self) -> None:
            fmt = args.format
            export_pdf = fmt in ("pdf", "all")
            export_docx = fmt in ("docx", "all", "pdf")
            export_overlay = bool(args.export_video)
            code, info = run_export(
                args,
                outputs_root=outputs_root,
                reports_dir=reports_dir,
                report_dir=report_dir,
                export_overlay=export_overlay,
                export_docx=export_docx,
                export_pdf=export_pdf,
                progress_cb=self.progress.emit,
                use_tqdm=False,
                log_fn=_log_line,
            )
            self.finished.emit(code, info)

    window = QWidget()
    window.setWindowTitle("Report Exporter")
    layout = QVBoxLayout(window)
    label_progress = QLabel("Preparing...")
    label_reports = QLabel(f"reports_dir: {reports_dir}")
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
            box = QMessageBox(window)
            box.setWindowTitle("Export completed")
            box.setText("Report export completed.")
            open_btn = QPushButton("Open output folder")
            close_btn = QPushButton("Close")
            box.addButton(open_btn, QMessageBox.ButtonRole.AcceptRole)
            box.addButton(close_btn, QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == open_btn:
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

    outputs_root = args.outdir or default_output_root()
    reports_dir = next_reports_dir(outputs_root)
    report_dir = report_data_dir(reports_dir)
    try:
        ensure_outdir(outputs_root)
        ensure_outdir(reports_dir)
        ensure_outdir(report_dir)
    except OSError as exc:
        print(f"[PATH] Output directory not writable: {exc}")
        return 2

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

    fmt = args.format
    export_pdf = fmt in ("pdf", "all")
    export_docx = fmt in ("docx", "all", "pdf")
    export_overlay = bool(args.export_video)
    # Ultra disabled; do not override imgsz from settings.

    log_path = os.path.join(outputs_root, "export.log")
    def _log(message: str) -> None:
        _log_line(message)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except OSError:
            pass

    def _param_source(flag: str) -> str:
        return "cli" if _flag_present(flag) else "default"

    effective_msg = (
        "effective_config: "
        f"device={resolved_device}(source={device_mode}) "
        f"imgsz={args.imgsz}(source={_param_source('--imgsz')}) "
        f"c_imgsz={args.c_imgsz}(source={_param_source('--c-imgsz')}) "
        f"people_grace_s={args.people_grace_s}(source={_param_source('--people-grace-s')}) "
        f"unblocked_alarm_s={args.unblocked_alarm_s}(source={_param_source('--unblocked-alarm-s')}) "
        f"sampling_min_s={args.sampling_min_s}(source={_param_source('--sampling-min-s')})"
    )
    _log(effective_msg)

    code, info = run_export(
        args,
        outputs_root=outputs_root,
        reports_dir=reports_dir,
        report_dir=report_dir,
        export_overlay=export_overlay,
        export_docx=export_docx,
        export_pdf=export_pdf,
        progress_cb=None,
        use_tqdm=True,
        log_fn=_log,
    )
    if info.get("last_fps"):
        stats_path = os.path.join(outputs_root, "export_stats.json")
        key = "last_export_fps_gpu" if resolved_device == "cuda" else "last_export_fps_cpu"
        data = _read_stats(stats_path)
        data[key] = round(float(info["last_fps"]), 2)
        try:
            _write_stats_atomic(stats_path, data)
            _log(f"stats_path: {stats_path}")
        except OSError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
