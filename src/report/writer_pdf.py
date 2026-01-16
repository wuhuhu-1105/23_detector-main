from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Tuple

from .types import Report


def _try_docx2pdf(docx_path: str, pdf_path: str) -> Tuple[bool, str]:
    try:
        from docx2pdf import convert
    except ImportError:
        return False, "docx2pdf not installed"
    try:
        convert(docx_path, pdf_path)
        return True, ""
    except Exception as exc:
        return False, f"docx2pdf failed: {exc}"


def _try_libreoffice(docx_path: str, pdf_path: str) -> Tuple[bool, str]:
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if not soffice:
        return False, "LibreOffice (soffice) not found"
    out_dir = os.path.dirname(pdf_path) or "."
    cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return False, f"LibreOffice failed to start: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, f"LibreOffice failed: {err or 'non-zero exit'}"
    stem = os.path.splitext(os.path.basename(docx_path))[0]
    produced = os.path.join(out_dir, f"{stem}.pdf")
    if not os.path.exists(produced):
        return False, "LibreOffice did not create PDF output"
    if os.path.abspath(produced) != os.path.abspath(pdf_path):
        try:
            os.replace(produced, pdf_path)
        except OSError as exc:
            return False, f"LibreOffice PDF move failed: {exc}"
    return True, ""


def write_report_pdf(report: Report, docx_path: str, pdf_path: str) -> str:
    errors: List[str] = []
    ok, reason = _try_docx2pdf(docx_path, pdf_path)
    if ok:
        return pdf_path
    if reason:
        errors.append(reason)
    ok, reason = _try_libreoffice(docx_path, pdf_path)
    if ok:
        return pdf_path
    if reason:
        errors.append(reason)
    detail = "; ".join(errors) if errors else "unknown error"
    raise ImportError(
        "PDF export failed. Install docx2pdf (requires Microsoft Word) "
        "or LibreOffice. Details: " + detail
    )
