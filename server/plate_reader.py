"""License-plate text extraction via EasyOCR.

This does not use a dedicated plate-localization model: EasyOCR's own text
detector is run over the lower portion of each vehicle crop (where a plate
almost always sits) and the results are filtered down to strings that look
like a plate. This keeps the install lightweight, at the cost of accuracy
compared to a purpose-built ALPR model.
"""
import re
from dataclasses import dataclass

import numpy as np

import config

_PLATE_CHARS = re.compile(r"[A-Z0-9]{%d,%d}" % (config.PLATE_MIN_CHARS, config.PLATE_MAX_CHARS))


@dataclass
class PlateResult:
    text: str | None
    confidence: float


class PlateReader:
    def __init__(self) -> None:
        import easyocr

        self._reader = easyocr.Reader(["en"], gpu=False)

    def read(self, vehicle_crop_bgr: np.ndarray) -> PlateResult:
        if vehicle_crop_bgr.size == 0:
            return PlateResult(None, 0.0)

        height = vehicle_crop_bgr.shape[0]
        plate_region = vehicle_crop_bgr[int(height * 0.4):, :]

        raw_results = self._reader.readtext(plate_region)
        best: PlateResult = PlateResult(None, 0.0)
        for _bbox, text, confidence in raw_results:
            candidate = re.sub(r"[^A-Z0-9]", "", text.upper())
            if not _PLATE_CHARS.fullmatch(candidate):
                continue
            if confidence > best.confidence:
                best = PlateResult(candidate, float(confidence))

        if best.confidence < config.PLATE_CONFIDENCE_THRESHOLD:
            return PlateResult(None, best.confidence)
        return best
