"""Receives camera frames from the Android app and runs the detection pipeline.

Run with:
    uvicorn app:app --host 0.0.0.0 --port 8000

The Android app POSTs raw JPEG bytes to /frame. Each frame is:
  1. Passed through YOLOv8 to find vehicle bounding boxes (free, local).
  2. A position-based tracker decides if a box is a car we haven't already
     logged recently, purely from bounding-box overlap - this has to happen
     *before* the next step, since that step costs money per call and we
     only want to pay for it once per car, not once per frame.
  3. Newly-confirmed vehicles get sent to the Claude API for make/model +
     plate reading in one call, then written to detections.xlsx + a
     snapshot image (sorted into review/ if the box was cut off by the
     frame edge, meaning the crop doesn't show the whole car).
"""
import logging
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parent / ".env")

import config
from dashboard import archive_row, render_dashboard
from excel_export import ExcelExporter
from plate_locator import find_plate_region
from tracker import Tracker
from vehicle_detector import VehicleDetector
from vision_classifier import VisionClassifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("street-watch")

app = FastAPI(title="street-watch")
app.mount("/snapshots", StaticFiles(directory=config.SNAPSHOT_DIR), name="snapshots")

_vehicle_detector = VehicleDetector()
_vision_classifier = VisionClassifier()
_tracker = Tracker()
_excel = ExcelExporter()

_latest_frame_jpeg: bytes | None = None

_VIEWER_HTML = """<!doctype html>
<html><head><title>street-watch live</title></head>
<body style="margin:0;background:#000;display:flex;align-items:center;justify-content:center;height:100vh;">
<img id="f" style="max-width:100%;max-height:100%;" />
<script>
const img = document.getElementById('f');
function refresh() { img.src = '/latest.jpg?t=' + Date.now(); }
img.onload = () => setTimeout(refresh, 200);
img.onerror = () => setTimeout(refresh, 1000);
refresh();
</script>
</body></html>"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/view")
def view() -> Response:
    return Response(content=_VIEWER_HTML, media_type="text/html")


@app.get("/dashboard")
def dashboard(tab: str = "cars", date_range: str = "today", error: str | None = None) -> Response:
    return Response(content=render_dashboard(tab, date_range, error), media_type="text/html")


@app.post("/archive")
def archive(snapshot: str = Form(...), date_range: str = Form("today")) -> RedirectResponse:
    _, error = archive_row(snapshot)
    url = f"/dashboard?tab=cars&date_range={date_range}" + (f"&error={error}" if error else "")
    return RedirectResponse(url=url, status_code=303)


@app.get("/latest.jpg")
def latest_frame() -> Response:
    if _latest_frame_jpeg is None:
        return Response(status_code=404, content="no frame received yet")
    return Response(content=_latest_frame_jpeg, media_type="image/jpeg")


def _classify_and_log(crop: np.ndarray, vehicle_label: str, needs_review: bool) -> None:
    """Runs on a background thread so the slow Claude API call never blocks
    the frame-response path - without this, every newly-detected car would
    freeze frame processing (and the live view) for as long as the call takes."""
    result = _vision_classifier.classify(crop)
    _excel.append_event(
        vehicle_label=vehicle_label,
        make_model=result.make_model,
        make_model_confidence=1.0 if result.make_model else 0.0,
        plate_text=result.plate,
        plate_confidence=1.0 if result.plate else 0.0,
        snapshot_bgr=crop,
        needs_review=needs_review,
    )
    logger.info("logged %s plate=%s make/model=%s", vehicle_label, result.plate, result.make_model)


@app.post("/frame")
async def receive_frame(request: Request, background_tasks: BackgroundTasks) -> Response:
    global _latest_frame_jpeg

    body = await request.body()
    frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return Response(status_code=400, content="could not decode JPEG")

    display_frame = frame.copy()  # annotated separately so drawing never leaks into saved crops
    vehicles = _vehicle_detector.detect(frame)
    events_queued = 0
    frame_height, frame_width = frame.shape[:2]
    margin = config.FRAME_EDGE_MARGIN_PX

    for vehicle in vehicles:
        bbox = (vehicle.x1, vehicle.y1, vehicle.x2, vehicle.y2)

        cv2.rectangle(display_frame, (vehicle.x1, vehicle.y1), (vehicle.x2, vehicle.y2), (0, 255, 0), 8)
        cv2.putText(
            display_frame, f"{vehicle.label} {vehicle.confidence:.2f}",
            (vehicle.x1, max(vehicle.y1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )

        # Best-effort plate localization for the live-view overlay only -
        # this has no effect on actual plate reading, which goes through
        # the Claude vision call below on the full vehicle crop regardless.
        # Falls back to a wide heuristic band when no confident match is
        # found, since a real detection isn't always possible.
        vehicle_crop_for_display = frame[vehicle.y1:vehicle.y2, vehicle.x1:vehicle.x2]
        located_plate = find_plate_region(vehicle_crop_for_display)
        vehicle_width = vehicle.x2 - vehicle.x1
        vehicle_height = vehicle.y2 - vehicle.y1
        if located_plate:
            px1, py1, px2, py2 = located_plate
            plate_top_left = (vehicle.x1 + px1, vehicle.y1 + py1)
            plate_bottom_right = (vehicle.x1 + px2, vehicle.y1 + py2)
        else:
            plate_width = int(vehicle_width * 0.75)
            plate_height = int(vehicle_height * 0.22)
            plate_center_x = (vehicle.x1 + vehicle.x2) // 2
            plate_center_y = vehicle.y1 + int(vehicle_height * 0.62)
            plate_top_left = (plate_center_x - plate_width // 2, plate_center_y - plate_height // 2)
            plate_bottom_right = (plate_center_x + plate_width // 2, plate_center_y + plate_height // 2)
        cv2.rectangle(display_frame, plate_top_left, plate_bottom_right, (255, 0, 0), 3)

        if not _tracker.is_new_event(None, vehicle.label, bbox):
            continue

        crop = frame[vehicle.y1:vehicle.y2, vehicle.x1:vehicle.x2].copy()
        is_cut_off = (
            vehicle.x1 <= margin
            or vehicle.y1 <= margin
            or vehicle.x2 >= frame_width - margin
            or vehicle.y2 >= frame_height - margin
        )
        background_tasks.add_task(_classify_and_log, crop, vehicle.label, is_cut_off)
        events_queued += 1

    encode_ok, encoded = cv2.imencode(".jpg", display_frame)
    if encode_ok:
        _latest_frame_jpeg = encoded.tobytes()

    return Response(status_code=200, content=f"{events_queued} event(s) queued")
