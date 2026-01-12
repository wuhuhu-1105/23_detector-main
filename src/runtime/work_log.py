from __future__ import annotations

import csv
import os
import time
from typing import Optional, Set


def _blocking_status(tags_d: Optional[Set[str]]) -> str:
    if not tags_d:
        return "unknown"
    if "blocking" in tags_d:
        return "blocking"
    if "no_blocking" in tags_d:
        return "no_blocking"
    return "unknown"


class WorkLogWriter:
    def __init__(self, out_dir: str, interval_s: float = 1.0, stamp: Optional[str] = None) -> None:
        self._interval_s = max(0.1, float(interval_s))
        os.makedirs(out_dir, exist_ok=True)
        if stamp is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
        self._path = os.path.join(out_dir, f"work_log_{stamp}.csv")
        self._file = open(self._path, "w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["time_s", "blocking_status", "people_count"])
        self._next_t = 0.0

    @property
    def path(self) -> str:
        return self._path

    def update(self, duration_s: Optional[float], tags_d: Optional[Set[str]], people_count: Optional[int]) -> None:
        if duration_s is None:
            return
        while duration_s >= self._next_t:
            status = _blocking_status(tags_d)
            people_val = "" if people_count is None else people_count
            self._writer.writerow([f"{self._next_t:.2f}", status, people_val])
            self._next_t += self._interval_s

    def close(self) -> None:
        self._file.close()
