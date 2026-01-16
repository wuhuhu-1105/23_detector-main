from __future__ import annotations

from typing import Dict, Set

from ultralytics import YOLO

from src.core.config import DetectorConfig
from src.core.types import Box, TagsRaw


class BlockingRaw:
    def __init__(self, cfg: DetectorConfig) -> None:
        self.cfg = cfg
        self.model = YOLO(cfg.model_path)
        self.names = self.model.names

    def process(self, frame) -> TagsRaw:
        results = self.model.predict(
            frame,
            conf=self.cfg.conf,
            iou=self.cfg.iou,
            imgsz=self.cfg.imgsz,
            device=self.cfg.device,
            half=self.cfg.half,
            verbose=False,
        )
        tags: Set[str] = set()
        conf_by_tag: Dict[str, float] = {}
        boxes_out: list[Box] = []
        yolo_result = results[0] if results else None
        if yolo_result is not None:
            boxes = yolo_result.boxes
            if boxes is not None and boxes.cls is not None:
                for cls_id, conf, xyxy in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist()):
                    name = self.names.get(int(cls_id), str(int(cls_id)))
                    tags.add(name)
                    conf_by_tag[name] = max(conf_by_tag.get(name, 0.0), float(conf))
                    boxes_out.append(Box(label=name, conf=float(conf), xyxy=tuple(map(float, xyxy))))
        return TagsRaw(tags=tags, conf_by_tag=conf_by_tag, boxes=boxes_out, yolo_result=yolo_result)
