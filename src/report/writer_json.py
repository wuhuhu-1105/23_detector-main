from __future__ import annotations

import json
import os
from dataclasses import asdict

from .types import Report


def write_report_json(report: Report, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    payload = asdict(report)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    os.replace(tmp_path, path)
    return path
