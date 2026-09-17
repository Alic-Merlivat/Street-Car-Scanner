"""Vehicle detection using a pretrained YOLOv8 model (COCO classes)."""
from dataclasses import dataclass

import numpy as np

import config


@dataclass
class VehicleBox:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str
    confidence: float


class VehicleDetector:
    """Wraps an Ultralytics YOLOv8 model, downloaded on first use."""

    def __init__(self, weights: str = "yolov8n.pt") -> None:
        from ultralytics import YOLO

        self._model = YOLO(weights)

    def detect(self, frame_bgr: np.ndarray) -> list[VehicleBox]:
        results = self._model.predict(frame_bgr, verbose=False)[0]
        boxes: list[VehicleBox] = []
        for box in results.boxes:
            class_id = int(box.cls[0])
            if class_id not in config.VEHICLE_CLASS_IDS:
                continue
            confidence = float(box.conf[0])
            if confidence < config.VEHICLE_CONFIDENCE_THRESHOLD:
                continue
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
            boxes.append(
                VehicleBox(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    label=config.VEHICLE_CLASS_IDS[class_id],
                    confidence=confidence,
                )
            )
        return boxes
