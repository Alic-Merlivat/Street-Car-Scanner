"""Central configuration for the street-watch server."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
REVIEW_DIR = SNAPSHOT_DIR / "review"
EXCEL_PATH = DATA_DIR / "detections.xlsx"

# A vehicle box within this many pixels of the full camera frame's edge is
# treated as cut off (not showing the whole car) and filed under
# SNAPSHOT_DIR/review instead of the main snapshots folder.
FRAME_EDGE_MARGIN_PX = 4

# COCO class ids (from the pretrained YOLOv8 model) that count as "a vehicle".
VEHICLE_CLASS_IDS = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

VEHICLE_CONFIDENCE_THRESHOLD = 0.45
PLATE_CONFIDENCE_THRESHOLD = 0.40

# Detections of the same plate (or, if the plate can't be read, the same
# vehicle position) within this many seconds are treated as the same
# passing car and collapsed into a single Excel row instead of one per frame.
DEDUP_WINDOW_SECONDS = 8.0

# Regex-ish sanity filter for OCR text before we trust it as a plate.
PLATE_MIN_CHARS = 4
PLATE_MAX_CHARS = 10

MAKE_MODEL_ENABLED = True

# Model used for make/model + plate reading via the Claude API (see
# vision_classifier.py). Haiku is fast/cheap and plenty capable for this;
# bump to a Sonnet model id for higher accuracy at higher cost.
VISION_MODEL = "claude-haiku-4-5-20251001"
