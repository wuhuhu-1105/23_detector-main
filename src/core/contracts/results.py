from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReportExportResult:
    outputs_root: str
    reports_dir: str
    report_dir: str
    report_json: str
    run_jsonl: str
    run_id: Optional[str] = None
    docx_path: Optional[str] = None
    overlay_path: Optional[str] = None
    pdf_path: Optional[str] = None
    export_log: Optional[str] = None
    frames_meta_path: Optional[str] = None
    last_fps: Optional[float] = None
