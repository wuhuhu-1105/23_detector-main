from __future__ import annotations

from typing import Dict, Set

from ultralytics import YOLO

from src.core.config import SamplingCloseConfig
from src.core.types import Box, TagsRaw


class SamplingCloseRaw:
    def __init__(self, cfg: SamplingCloseConfig) -> None:
        self.cfg = cfg
        self.model = YOLO(cfg.model_path)
        self.names = self.model.names

    def process(self, frame) -> TagsRaw:
        results = self.model.predict(
            frame,
            conf=min(self.cfg.conf_close, self.cfg.conf_sampling),
            iou=self.cfg.iou,
            imgsz=self.cfg.imgsz,
            max_det=self.cfg.max_det,
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
                    if name not in ("close", "sampling"):
                        continue
                    conf_val = float(conf)
                    if name == "close" and conf_val < self.cfg.conf_close:
                        continue
                    if name == "sampling" and conf_val < self.cfg.conf_sampling:
                        continue
                    tags.add(name)
                    conf_by_tag[name] = max(conf_by_tag.get(name, 0.0), conf_val)
                    boxes_out.append(Box(label=name, conf=conf_val, xyxy=tuple(map(float, xyxy))))
        return TagsRaw(tags=tags, conf_by_tag=conf_by_tag, boxes=boxes_out, yolo_result=yolo_result)
