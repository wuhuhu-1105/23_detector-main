from __future__ import annotations

from typing import Optional, Set

from ultralytics import YOLO

from src.core.config import DetectorConfig
from src.core.types import Box, PeopleRaw


class PeopleTrackerRaw:
    def __init__(self, cfg: DetectorConfig) -> None:
        self.cfg = cfg
        self.model = YOLO(cfg.model_path)

    def process(self, frame) -> PeopleRaw:
        results = self.model.track(
            frame,
            persist=True,
            conf=self.cfg.conf,
            iou=self.cfg.iou,
            imgsz=self.cfg.imgsz,
            classes=[0],
            verbose=False,
        )
        active_ids: Set[int] = set()
        boxes_out: list[Box] = []
        yolo_result = results[0] if results else None
        if yolo_result is not None:
            boxes = yolo_result.boxes
            if boxes is not None:
                ids = boxes.id.tolist() if boxes.id is not None else []
                xyxy_list = boxes.xyxy.tolist() if boxes.xyxy is not None else []
                conf_list = boxes.conf.tolist() if boxes.conf is not None else []
                for i, xyxy in enumerate(xyxy_list):
                    track_id = int(ids[i]) if i < len(ids) and ids[i] is not None else None
                    if track_id is not None:
                        active_ids.add(track_id)
                    conf = float(conf_list[i]) if i < len(conf_list) else 0.0
                    boxes_out.append(
                        Box(label="person", conf=conf, xyxy=tuple(map(float, xyxy)), track_id=track_id)
                    )
        return PeopleRaw(active_ids=active_ids, count_raw=len(active_ids), boxes=boxes_out, yolo_result=yolo_result)
