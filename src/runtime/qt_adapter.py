from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np
from PyQt6.QtGui import QImage

from src.core.types import Box, FrameOutput
from src.ui_qt.state_view_spec import StatusDTO, normalize_state, to_state_cn, to_state_color_rgb

_COLOR_MAP = {
    "people": (255, 255, 255),
    "sampling_close": (0, 255, 0),
    "blocking": (0, 170, 255),
}


def _draw_box(img: np.ndarray, box: Box, color: Tuple[int, int, int], prefix: str) -> None:
    x1, y1, x2, y2 = [int(v) for v in box.xyxy]
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    label = f"{prefix}:{box.label} {box.conf:.2f}"
    if box.track_id is not None:
        label += f" id:{box.track_id}"
    cv2.putText(img, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def render_to_qimage(
    frame_bgr: np.ndarray,
    detections: Dict[str, List[Box]],
    *,
    no_overlay: bool = False,
) -> QImage:
    frame = frame_bgr if no_overlay else frame_bgr.copy()
    if not no_overlay:
        for key, boxes in detections.items():
            color = _COLOR_MAP.get(key, (160, 160, 160))
            for box in boxes:
                _draw_box(frame, box, color, key)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = frame_rgb.shape[:2]
    bytes_per_line = w * 3
    return QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()


def frame_output_to_view(output: FrameOutput, *, no_overlay: bool = False) -> Tuple[QImage, StatusDTO]:
    tags_c = set(output.metrics.get("tags_c") or [])
    tags_d = set(output.metrics.get("tags_d") or [])
    people_ok = output.metrics.get("people_ok")
    people_count = output.metrics.get("people_count") or 0
    state_reason = output.metrics.get("state_reason")
    state_5class, state_reason = normalize_state(
        output.state,
        output.state,
        state_reason,
        people_ok,
        people_count,
        tags_c,
        tags_d,
    )
    if not state_5class:
        state_5class = "-"
    color_rgb = to_state_color_rgb(state_5class)
    video_t_s = output.metrics.get("video_t_s")
    if video_t_s is None:
        video_t_s = (output.timestamp_ms / 1000.0) if output.timestamp_ms is not None else None

    status = StatusDTO(
        state_raw=output.state,
        state_5class=state_5class,
        state_cn=to_state_cn(state_5class),
        color=color_rgb,
        color_rgb=color_rgb,
        duration_s=output.state_duration_sec if output.state_duration_sec is not None else 0.0,
        video_t_s=video_t_s,
        tags_c_set=tags_c,
        tags_d_set=tags_d,
        people_count=people_count,
        people_ok=bool(people_ok) if people_ok is not None else True,
        people_alarm=(not people_ok) if people_ok is not None else False,
        run_state_cn="Running",
        frame_index=output.frame_index,
        fps=output.fps,
    )
    qimage = render_to_qimage(output.frame_bgr, output.detections, no_overlay=no_overlay)
    return qimage, status
