from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterator, Optional, Tuple

import cv2

def get_video_time_s(frame_index: int, cap: cv2.VideoCapture) -> Optional[float]:
    _ = frame_index
    msec = cap.get(cv2.CAP_PROP_POS_MSEC)
    if msec is None or math.isnan(msec) or msec <= 0:
        return None
    return float(msec) / 1000.0


@dataclass
class VideoSource:
    path: str

    def __iter__(self) -> Iterator[Tuple[int, float, Optional[float], "cv2.Mat"]]:
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {self.path}")
        idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                video_t_s = get_video_time_s(idx, cap)
                yield idx, float(timestamp_ms), video_t_s, frame
                idx += 1
        finally:
            cap.release()
