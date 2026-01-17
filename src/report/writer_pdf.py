from __future__ import annotations

from .types import Report


def write_report_pdf(report: Report, docx_path: str, pdf_path: str) -> str:
    try:
        from docx2pdf import convert
    except ImportError as exc:
        raise ImportError("docx2pdf is required for report.pdf generation") from exc

    convert(docx_path, pdf_path)
    return pdf_path
