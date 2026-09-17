"""Best-effort make/model classification for a cropped vehicle image.

Make/model recognition is the hardest of the three signals we extract:
there's no small, universally-accurate open model for it. This wraps a
pretrained Hugging Face image-classification model and degrades to
"unknown" if the model can't be loaded (e.g. no internet on first run) or
the prediction confidence is too low to be worth recording.

To swap in a stronger option later (e.g. a paid recognition API), replace
the body of `classify()` and keep the same return type.
"""
from dataclasses import dataclass

import numpy as np

import config

_MODEL_ID = "dima806/car_models_image_detection"
_MIN_CONFIDENCE = 0.35


@dataclass
class MakeModelResult:
    label: str | None
    confidence: float


class MakeModelClassifier:
    def __init__(self) -> None:
        self._pipeline = None
        self._load_failed = False
        if not config.MAKE_MODEL_ENABLED:
            self._load_failed = True
            return
        try:
            from transformers import pipeline

            self._pipeline = pipeline("image-classification", model=_MODEL_ID)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully either way
            print(f"[make_model_classifier] could not load {_MODEL_ID}: {exc}")
            self._load_failed = True

    def classify(self, vehicle_crop_bgr: np.ndarray) -> MakeModelResult:
        if self._load_failed or vehicle_crop_bgr.size == 0:
            return MakeModelResult(None, 0.0)

        from PIL import Image

        rgb = vehicle_crop_bgr[:, :, ::-1]
        image = Image.fromarray(rgb)
        predictions = self._pipeline(image, top_k=1)
        if not predictions:
            return MakeModelResult(None, 0.0)

        top = predictions[0]
        confidence = float(top["score"])
        if confidence < _MIN_CONFIDENCE:
            return MakeModelResult(None, confidence)
        return MakeModelResult(top["label"], confidence)
