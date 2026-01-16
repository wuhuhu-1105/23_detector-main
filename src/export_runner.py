from __future__ import annotations

import json
import os
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.report.export_core import run_export


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
        self._log(f"source: {self._args.source}")
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

        code, info = run_export(
            self._args,
            outputs_root=self._outputs_root,
            reports_dir=self._reports_dir,
            report_dir=self._report_dir,
            export_overlay=self._export_overlay,
            export_docx=self._export_docx,
            export_pdf=self._export_pdf,
            progress_cb=_on_progress,
            use_tqdm=False,
            log_fn=self._log,
        )
        if code == 0:
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
        else:
            reason = f"Export failed (code {code})."
            if code == 5 and self._export_pdf:
                reason += " PDF export may require Microsoft Word or LibreOffice."
            self.failed.emit(reason, self._log_path)
