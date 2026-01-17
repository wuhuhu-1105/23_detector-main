from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.contracts.config import ReportConfig
from src.core.contracts import __version__ as contracts_version
from src.services.report_service import ReportService, SERVICE_VERSION as report_service_version


class ExportRunner(QThread):
    started = pyqtSignal(str, str, str)
    progress = pyqtSignal(int, int, float, object, str)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str, str)

    def __init__(
        self,
        args,
        *,
        outputs_root: str,
        reports_dir: str,
        report_dir: str,
        export_overlay: bool,
        export_pdf: bool,
        export_docx: bool,
        log_path: str,
    ) -> None:
        super().__init__()
        self._args = args
        self._outputs_root = outputs_root
        self._reports_dir = reports_dir
        self._report_dir = report_dir
        self._export_overlay = export_overlay
        self._export_pdf = export_pdf
        self._export_docx = export_docx
        self._log_path = log_path
        self._last_fps: Optional[float] = None
        self._run_id = uuid.uuid4().hex

    def _log(self, message: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _read_stats(self, path: str) -> dict:
        try:
            if not os.path.exists(path):
                return {}
            if os.path.getsize(path) == 0:
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_stats_atomic(self, path: str, data: dict) -> None:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)

    def run(self) -> None:
        self.started.emit(self._outputs_root, self._reports_dir, self._report_dir)
        device_mode = getattr(self._args, "device_mode", "auto")
        resolved_device = getattr(self._args, "device", "cpu")
        cuda_available = getattr(self._args, "cuda_available", None)
        cuda_reason = getattr(self._args, "cuda_reason", "")
        self._log(
            "run_start "
            f"run_id={self._run_id} "
            f"contracts_version={contracts_version} "
            "service=report "
            f"service_version={report_service_version} "
            f"source={self._args.source} "
            f"device={resolved_device} "
            f"device_mode={device_mode}"
        )
        self._log(f"outputs_root: {self._outputs_root}")
        self._log(f"reports_dir: {self._reports_dir}")
        self._log(f"report_dir: {self._report_dir}")
        self._log(
            f"device_mode={device_mode} resolved_device={resolved_device} "
            f"cuda_available={cuda_available} reason={cuda_reason}"
        )

        def _on_progress(done: int, total: int, fps: float, eta, stage: str) -> None:
            if fps and fps > 0:
                self._last_fps = fps
            self.progress.emit(done, total, fps, eta, stage)

        overrides = {
            "enable_min_sampling_duration": bool(self._args.enable_min_sampling_duration),
            "sampling_min_s": float(self._args.sampling_min_s),
            "people_grace_s": float(self._args.people_grace_s),
            "unblocked_alarm_s": float(self._args.unblocked_alarm_s),
            "gap_allow_unblocked_s": float(self._args.gap_allow_unblocked_s),
            "sampling_start_s": float(self._args.sampling_start_s),
            "sampling_end_s": float(self._args.sampling_end_s),
            "gap_allow_sampling_s": float(self._args.gap_allow_sampling_s),
            "fps_assume": float(self._args.fps_assume),
            "device_mode": device_mode,
            "cuda_available": cuda_available,
            "cuda_reason": cuda_reason,
        }
        cfg = ReportConfig(
            outdir=self._args.outdir,
            outputs_root=self._outputs_root,
            reports_dir=self._reports_dir,
            report_dir=self._report_dir,
            format=self._args.format,
            export_video=bool(self._export_overlay),
            video_out=self._args.video_out,
            no_boxes=bool(self._args.no_boxes),
            device=self._args.device,
            device_mode=device_mode,
            half=bool(self._args.half),
            allow_network=bool(self._args.allow_network),
            use_tqdm=False,
            log_fn=self._log,
            run_id=self._run_id,
            overrides=overrides,
        )

        service = ReportService()
        service.on_progress(lambda ev: _on_progress(ev.done_frames, ev.total_frames, ev.fps, ev.eta_s, ev.stage))
        try:
            result = service.export(self._args.source, cfg)
        except Exception as exc:
            reason = f"Export failed: {exc}"
            self.failed.emit(reason, self._log_path)
            return

        info = {
            "outputs_root": result.outputs_root,
            "reports_dir": result.reports_dir,
            "report_dir": result.report_dir,
            "docx": result.docx_path,
            "mp4": result.overlay_path,
            "jsonl": result.run_jsonl,
            "json": result.report_json,
            "pdf": result.pdf_path,
            "last_fps": result.last_fps,
        }

        if self._last_fps:
            stats_path = os.path.join(self._outputs_root, "export_stats.json")
            key = "last_export_fps_gpu" if resolved_device == "cuda" else "last_export_fps_cpu"
            try:
                data = self._read_stats(stats_path)
                data[key] = round(self._last_fps, 2)
                self._write_stats_atomic(stats_path, data)
                self._log(f"stats_path: {stats_path}")
            except OSError:
                pass
        self.completed.emit(info)
