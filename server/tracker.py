"""Collapses repeated detections of the same passing car into one event.

Without this, a car sitting in frame for 3 seconds at 5 fps would produce
~15 near-identical Excel rows. We key on plate text when we have one
(most reliable), and fall back to bounding-box overlap + vehicle label
for cars whose plate couldn't be read.
"""
import time
from dataclasses import dataclass, field

import config


@dataclass
class _TrackedVehicle:
    key: str
    last_seen: float
    bbox: tuple[int, int, int, int]


@dataclass
class Tracker:
    _active: dict[str, _TrackedVehicle] = field(default_factory=dict)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, vehicle in self._active.items()
            if now - vehicle.last_seen > config.DEDUP_WINDOW_SECONDS
        ]
        for key in expired:
            del self._active[key]

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        intersection = (ix2 - ix1) * (iy2 - iy1)
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return intersection / float(area_a + area_b - intersection)

    def is_new_event(
        self,
        plate_text: str | None,
        vehicle_label: str,
        bbox: tuple[int, int, int, int],
    ) -> bool:
        """Returns True (and records the sighting) if this looks like a new car."""
        now = time.time()
        self._prune(now)

        if plate_text:
            key = f"plate:{plate_text}"
            if key in self._active:
                self._active[key].last_seen = now
                return False
            self._active[key] = _TrackedVehicle(key, now, bbox)
            return True

        for vehicle in self._active.values():
            if not vehicle.key.startswith("box:"):
                continue
            if not vehicle.key.endswith(f":{vehicle_label}"):
                continue
            if self._iou(vehicle.bbox, bbox) > 0.3:
                vehicle.last_seen = now
                vehicle.bbox = bbox
                return False

        key = f"box:{id(bbox)}:{vehicle_label}"
        self._active[key] = _TrackedVehicle(key, now, bbox)
        return True
