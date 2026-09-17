"""Make/model + plate reading via the Claude API's vision capability.

Replaces the free local plate_reader.py + make_model_classifier.py: one
call per confirmed new vehicle sighting gets both answers, since a
general vision-language model reads plates and identifies car models far
more reliably than the small free local models this project started with.

Requires ANTHROPIC_API_KEY to be set (e.g. via a .env file - see .env.example).
"""
import base64
import json
import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np
from anthropic import Anthropic

import config

logger = logging.getLogger("street-watch")

_PROMPT = (
    "Look at this photo of a vehicle. Respond with ONLY a JSON object, "
    "no other text, no markdown formatting:\n"
    '{"make_model": "<make and model, e.g. \\"BMW M3 Touring\\", '
    'or null if you cannot identify it>", '
    '"plate": "<license plate characters only, no spaces or dashes, '
    'or null if no plate is visible or it cannot be read>"}'
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_NON_ALNUM = re.compile(r"[^A-Z0-9]")


@dataclass
class VisionResult:
    make_model: str | None
    plate: str | None


class VisionClassifier:
    def __init__(self) -> None:
        self._client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    def classify(self, vehicle_crop_bgr: np.ndarray) -> VisionResult:
        encode_ok, encoded = cv2.imencode(".jpg", vehicle_crop_bgr)
        if not encode_ok:
            return VisionResult(None, None)

        image_b64 = base64.standard_b64encode(encoded.tobytes()).decode("utf-8")
        try:
            response = self._client.messages.create(
                model=config.VISION_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }],
            )
            text = response.content[0].text
        except Exception as exc:  # noqa: BLE001 - an API hiccup shouldn't break the pipeline
            logger.warning("vision classifier call failed: %s", exc)
            return VisionResult(None, None)

        match = _JSON_BLOCK.search(text)
        if not match:
            logger.warning("vision classifier returned no JSON: %r", text)
            return VisionResult(None, None)

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("vision classifier returned invalid JSON: %r", text)
            return VisionResult(None, None)

        make_model = data.get("make_model") or None
        plate = data.get("plate") or None
        if plate:
            plate = _NON_ALNUM.sub("", plate.upper()) or None
        return VisionResult(make_model=make_model, plate=plate)
