# Street Watch

An Android phone films the street outside your home, a Python server on
your PC detects passing vehicles, identifies their make/model and plate via
the Claude API, and logs each one to a browsable dashboard (and a linked
Excel export) with a snapshot photo — all over your home Wi-Fi, no cloud
hosting required.

**Before you run this**: recording a public street and logging plates can
be regulated where you live (e.g. GDPR in the EU/France treats a plate as
personal data). This is built for personal home-security use on your own
street — check your local rules (a visible notice is often required) before
leaving it running long-term.

## Technology Stack and Features

- ⚡ [FastAPI](https://fastapi.tiangolo.com/) for the Python server and web dashboard.
  - 🚀 [Uvicorn](https://www.uvicorn.org/) as the ASGI server.
  - 🧠 [Ultralytics YOLOv8](https://docs.ultralytics.com/) for real-time vehicle detection.
  - 👁️ [OpenCV](https://opencv.org/) for image processing, frame annotation, and plate-region localization.
  - 🤖 [Anthropic Claude API](https://docs.anthropic.com/) (vision) for make/model identification and plate reading.
  - 📗 [openpyxl](https://openpyxl.readthedocs.io/) for Excel export with embedded thumbnails and hyperlinks.
  - 🔑 [python-dotenv](https://pypi.org/project/python-dotenv/) for environment/secrets configuration.
- 📱 Android app written in Kotlin.
  - 📷 [CameraX](https://developer.android.com/training/camerax) for camera preview, frame capture, and zoom control.
  - 🌐 [OkHttp](https://square.github.io/okhttp/) for frame upload over HTTP.
  - 🔁 An Android foreground Service for continuous background streaming.
  - 🐘 [Gradle](https://gradle.org/) (Kotlin DSL) as the build system.
- 🗄️ Reference/legacy pipeline, kept for comparison and not used live (see [Tuning & known limitations](#tuning--known-limitations)).
  - 🔤 [EasyOCR](https://github.com/JaidedAI/EasyOCR), [Hugging Face Transformers](https://huggingface.co/docs/transformers/index), [PyTorch](https://pytorch.org/), and [timm](https://github.com/huggingface/pytorch-image-models) for free/local OCR and make/model classification.
- 🎥 Live Wi-Fi video streaming from an Android phone to a home server, no cloud hosting required.
- 🚗 Real-time vehicle detection with bounding-box overlay.
- 🔍 AI-powered make/model identification and license plate reading.
- 🧮 Position-based deduplication so one passing car produces one log entry, not one per frame.
- 🔎 Adjustable camera zoom (1x / 2x / 5x) and configurable frame interval.
- 🌙 Background-safe streaming that keeps running with the screen off or the app backgrounded.
- ⚙️ Non-blocking architecture — slow API calls never freeze the live feed.
- 🖥️ Live view page with detection and plate-region overlay for aiming and monitoring.
- 📋 Web dashboard with:
  - 🗂️ Cars / Archive tabs (auto-sorts unidentified or manually archived detections).
  - 📅 Date-range filters (Today, Yesterday, This week, Last week, This month).
  - 🏭 Top-5 manufacturers chart.
  - ⏰ Hour-by-hour traffic timeline.
- 📁 Excel export with embedded thumbnails, clickable links to full snapshots, and crash-safe atomic writes.
- 🗃️ One-click archive workflow to move bad or unidentified captures out of the main log.

## How it works

```
Android phone (camera, CameraX)              Python server (FastAPI)
  - live preview + 1x/2x/5x zoom               |
  - foreground service, keeps streaming   -->  POST /frame (JPEG over Wi-Fi)
    with the screen off or app backgrounded    |
                                                v
                                    YOLOv8 (find vehicles, free/local)
                                                |
                              position-based dedup tracker
                              (collapses one passing car into one event,
                               so a single sighting isn't billed/logged
                               once per frame)
                                                |
                                    Claude API (vision): make/model
                                    + plate text, in one call
                                                |
                                                v
                      detections.xlsx  <-->  /dashboard (Cars / Archive tabs,
                      (thumbnail +           date-range filters, top
                       hyperlink per row)     manufacturers, hourly timeline)
```

Both the phone and the PC must be on the same Wi-Fi network. Everything
else — the live camera feed, the dashboard, the Excel file — is served
locally; nothing leaves your network except the one cropped photo per
detected car sent to the Claude API for identification.

## 1. Run the server

The ML dependencies (torch, ultralytics) lag behind the newest Python
releases, so if you're on a very recent Python, prefer 3.11/3.12 for the
venv instead.

```bash
cd server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Get an API key from [console.anthropic.com](https://console.anthropic.com),
then:

```bash
copy .env.example .env
```

and fill in `ANTHROPIC_API_KEY=` in that new `.env` file.

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

First run downloads the YOLOv8 weights (~6MB, cached after that). Find your
PC's local IP for the phone to connect to:

```bash
ipconfig
```

Look for the `IPv4 Address` under your active Wi-Fi adapter (e.g.
`192.168.1.100`). You'll need:
- The Wi-Fi network set to **Private** (not Public) in Windows.
- A Windows Firewall inbound rule allowing `venv\Scripts\python.exe` on
  port `8000` — Settings → Firewall & network protection → Allow an app.

## 2. Build the Android app

This repo includes the app's source and Gradle build files, but not a
generated Gradle wrapper (that's normally created by Android Studio itself).
Easiest path:

1. In Android Studio: **File > New > New Project > Empty Views Activity**,
   language **Kotlin**, package name `com.streetwatch.capture`, minimum SDK
   **API 26**. Let it finish creating and syncing.
2. Copy the files from this repo's `android-app/` into the new project,
   merging into the generated `app/build.gradle.kts` (add the new
   dependencies) and `AndroidManifest.xml` (add the extra permissions and
   the `StreamingService` entry) rather than overwriting them outright,
   since Android Studio's generated project layout can vary by version;
   the Kotlin source files and `strings.xml`/`activity_main.xml` can be
   copied over directly:
   - `app/src/main/java/com/streetwatch/capture/MainActivity.kt`
   - `app/src/main/java/com/streetwatch/capture/StreamingService.kt`
   - `app/src/main/java/com/streetwatch/capture/FrameUploader.kt`
   - `app/src/main/res/layout/activity_main.xml`
   - `app/src/main/res/values/strings.xml`
   - `app/src/main/res/drawable/ic_launcher_background.xml`
   - `app/src/main/res/drawable/ic_launcher_foreground.xml`
3. Let Gradle sync (it will pull in CameraX and OkHttp).
4. Run the app on a real phone over USB with developer mode / USB debugging
   enabled — the camera won't work in the emulator in any useful way for
   this. On Android 14+/15+ you may also need to grant a local-network
   permission alongside camera, since some Android versions gate any
   connection to a private IP (192.168.x.x) separately from plain internet
   access.

## 3. Use it

1. Mount the phone so it has a clear view of the street, plugged in to
   power (continuous streaming drains the battery fast).
2. Open the app, grant the camera (and notification) permission.
3. Enter the server URL, e.g. `http://192.168.1.100:8000`.
4. Pick a zoom level (1x/2x/5x) and a frame interval in milliseconds —
   lower sends more frames/second, higher reduces load if the server falls
   behind.
5. Tap **Start streaming**. A persistent notification means it's running,
   including with the screen off or the app backgrounded.
6. Watch it live at `http://<server-ip>:8000/view`, or check results at
   `http://<server-ip>:8000/dashboard`.

## Tuning & known limitations

- **Speed**: after a one-time model warm-up on server start, per-frame
  processing is well under a second on a CPU-only PC — comfortably fast
  enough for a phone streaming a few frames per second. The Claude API
  call for a newly-detected car runs in the background, so it doesn't
  block the live feed while waiting on a response.
- **Plate & make/model reading** goes through the Claude API on the full
  vehicle crop and is generally accurate on a clear, reasonably close,
  well-lit shot — but isn't perfect, especially on blurry, angled, or
  low-light captures. There's a cost-per-detection tradeoff here: a
  position-based tracker (`tracker.py`) collapses one passing car into a
  single API call rather than one per frame.
- **The blue "plate" box in the live view is a best-effort visual guide**,
  not the actual OCR region — it's a local, free heuristic
  (`plate_locator.py`) using edge/contour analysis, so it can occasionally
  land on a grille or reflection instead of the real plate. It has no
  effect on the actual plate reading, which always uses the full vehicle
  crop regardless.
- **Dedup**: `config.DEDUP_WINDOW_SECONDS` controls how long a vehicle
  has to be absent before the next sighting counts as a new car.
- `server/make_model_classifier.py` and `server/plate_reader.py` are the
  original free/local pipeline (Hugging Face classifier + EasyOCR) kept
  for reference/comparison — the live pipeline in `app.py` uses
  `vision_classifier.py` (Claude) instead, since it was meaningfully more
  accurate in testing.
