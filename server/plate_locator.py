"""Finds a plate-shaped rectangle within a vehicle crop, for drawing an
accurate live-view overlay box. This is classic edge/contour-based
localization (no ML, no external model file) - it looks for a wide,
rectangular high-contrast region in the lower part of the crop, which is
where a plate almost always is. It's a real detection (unlike a fixed
proportional guess), but still a heuristic: it can miss on low-contrast or
heavily reflective plates. Purely visual - has no effect on OCR/plate
reading accuracy, which goes through the Claude vision call separately.
"""
import cv2
import numpy as np

_SEARCH_TOP_FRACTION = 0.3  # skip the roofline/windows - plates aren't up there
_MIN_ASPECT_RATIO = 2.0
_MAX_ASPECT_RATIO = 6.0
_MIN_AREA_FRACTION = 0.01
_MAX_AREA_FRACTION = 0.35
_IDEAL_ASPECT_RATIO = 3.5
_MIN_EDGE_DENSITY = 0.06  # plate characters create internal edges; a shadow or
                          # reflection doesn't, so this is what tells them apart


def find_plate_region(crop_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """Returns (x1, y1, x2, y2) in the crop's own coordinates, or None."""
    height, width = crop_bgr.shape[:2]
    if height == 0 or width == 0:
        return None

    search_top = int(height * _SEARCH_TOP_FRACTION)
    search_region = crop_bgr[search_top:, :]
    if search_region.size == 0:
        return None

    gray = cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(gray, 30, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    region_area = search_region.shape[0] * search_region.shape[1]
    best_box = None
    best_score = -1.0

    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if box_height == 0:
            continue
        aspect_ratio = box_width / box_height
        area_fraction = (box_width * box_height) / region_area

        if not (_MIN_ASPECT_RATIO <= aspect_ratio <= _MAX_ASPECT_RATIO):
            continue
        if not (_MIN_AREA_FRACTION <= area_fraction <= _MAX_AREA_FRACTION):
            continue

        # a shadow or reflection is smooth inside; plate characters aren't -
        # reject candidates with too little internal edge content
        interior = edges[y:y + box_height, x:x + box_width]
        edge_density = np.count_nonzero(interior) / interior.size if interior.size else 0
        if edge_density < _MIN_EDGE_DENSITY:
            continue

        # prefer larger, higher-edge-density candidates closer to a plate's
        # typical proportions
        shape_fit = 1.0 - abs(aspect_ratio - _IDEAL_ASPECT_RATIO) / _IDEAL_ASPECT_RATIO
        score = area_fraction * shape_fit * edge_density
        if score > best_score:
            best_score = score
            best_box = (x, y + search_top, x + box_width, y + search_top + box_height)

    return best_box
