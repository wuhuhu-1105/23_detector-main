from __future__ import annotations

from typing import Callable, Optional
import uuid

import sys

from src.core.contracts.config import ReportConfig
from src.core.contracts.events import ReportProgressEvent
from src.core.contracts.results import ReportExportResult


SERVICE_VERSION = "0.1"


class ReportService:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[ReportProgressEvent], None]] = []

    def on_progress(self, callback: Callable[[ReportProgressEvent], None]) -> None:
        self._callbacks.append(callback)

    def export(self, source: str, config: Optional[ReportConfig] = None) -> ReportExportResult:
        self._assert_no_cross_imports()
        config = config or ReportConfig()
        run_id = config.run_id or uuid.uuid4().hex
        from src.cli.report_gen import _build_parser, _ensure_runtime_defaults
        from src.services.report_impl.export_core import run_export

        parser = _build_parser()
        args = parser.parse_args(["--source", source])
        _ensure_runtime_defaults(args)
        config.apply_to_args(args)

        outputs_root = config.outputs_root or config.outdir or self.default_output_root()
        reports_dir = config.reports_dir or self.next_reports_dir(outputs_root)
        report_dir = config.report_dir or self.report_data_dir(reports_dir)
        self.ensure_outdir(outputs_root)
        self.ensure_outdir(reports_dir)
        self.ensure_outdir(report_dir)

        export_pdf = config.format in ("pdf", "all")
        export_docx = config.format in ("docx", "all", "pdf")
        export_overlay = bool(config.export_video)

        total_frames = self.get_total_frames(source)

        def _emit_event(
            *,
            stage: str,
            done: int = 0,
            total: int = 0,
            fps: float = 0.0,
            eta: Optional[float] = None,
            message: Optional[str] = None,
        ) -> None:
            percent = (done / total) * 100.0 if total > 0 else None
            event = ReportProgressEvent(
                event_type="progress",
                run_id=run_id,
                done_frames=done,
                total_frames=total,
                fps=fps,
                eta_s=eta,
                stage=stage,
                percent=percent,
                source=source,
                done=done,
                total=total,
                message=message,
            )
            for cb in list(self._callbacks):
                cb(event)

        def _on_progress(done: int, total: int, fps: float, eta, stage: str) -> None:
            percent = (done / total) * 100.0 if total > 0 else None
            event = ReportProgressEvent(
                event_type="progress",
                run_id=run_id,
                done_frames=done,
                total_frames=total,
                fps=fps,
                eta_s=eta,
                stage=stage,
                percent=percent,
                source=source,
                done=done,
                total=total,
            )
            for cb in list(self._callbacks):
                cb(event)

        use_tqdm = True if config.use_tqdm is None else bool(config.use_tqdm)

        def _on_stage(stage: str, message: Optional[str]) -> None:
            _emit_event(stage=stage, done=0, total=total_frames, message=message)

        code, info = run_export(
            args,
            outputs_root=outputs_root,
            reports_dir=reports_dir,
            report_dir=report_dir,
            export_overlay=export_overlay,
            export_docx=export_docx,
            export_pdf=export_pdf,
            progress_cb=_on_progress,
            stage_cb=_on_stage,
            use_tqdm=use_tqdm,
            log_fn=config.log_fn,
        )
        if code != 0:
            raise RuntimeError(f"Report export failed (code {code}).")

        return ReportExportResult(
            outputs_root=info["outputs_root"],
            reports_dir=info["reports_dir"],
            report_dir=info["report_dir"],
            report_json=info["json"],
            run_jsonl=info["jsonl"],
            run_id=run_id,
            docx_path=info.get("docx"),
            overlay_path=info.get("mp4"),
            pdf_path=info.get("pdf"),
            export_log=None,
            frames_meta_path=None,
            last_fps=info.get("last_fps"),
        )

    @staticmethod
    def default_output_root():
        from src.services.report_impl.export_core import default_output_root

        return default_output_root()

    @staticmethod
    def ensure_outdir(path):
        from src.services.report_impl.export_core import ensure_outdir

        return ensure_outdir(path)

    @staticmethod
    def get_total_frames(source: str):
        from src.services.report_impl.export_core import get_total_frames

        return get_total_frames(source)

    @staticmethod
    def next_reports_dir(outputs_root):
        from src.services.report_impl.export_core import next_reports_dir

        return next_reports_dir(outputs_root)

    @staticmethod
    def report_data_dir(reports_dir):
        from src.services.report_impl.export_core import report_data_dir

        return report_data_dir(reports_dir)

    @staticmethod
    def _assert_no_cross_imports() -> None:
        for name in sys.modules.keys():
            if name.startswith("src.ui_qt") or name.startswith("src.services.realtime_service"):
                raise RuntimeError("ReportService cannot import realtime/UI modules.")
