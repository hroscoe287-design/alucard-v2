import os
import time
import threading
from datetime import datetime, timezone

import av
import numpy as np
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

RTSP_FEED_URL = os.getenv("RTSP_FEED_URL", "").strip()
STREAM_TIMEOUT = float(os.getenv("STREAM_TIMEOUT", "8"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "75"))

lock = threading.Lock()

state = {
    "connected": False,
    "last_frame": None,
    "last_frame_time": 0,
    "frames": 0,
    "fps": 0,
    "signal": "WAIT",
    "confidence": 0,
    "reason": "Waiting for screen feed",
    "error": "",
    "started": time.time(),
}

previous_gray = None
fps_counter = 0
fps_start = time.time()


def analyze_frame(frame):
    """
    Basic screen-feed health / visual-movement analysis.

    This intentionally does NOT pretend to know the Pocket Option
    candle direction from arbitrary pixels. It only produces an
    experimental visual signal when there is enough movement.
    """

    global previous_gray

    img = np.asarray(frame)

    if img.ndim != 3 or img.shape[2] < 3:
        return "WAIT", 0, "Invalid video frame"

    # Resize for inexpensive analysis.
    small = img[::8, ::8, :3]

    gray = (
        0.299 * small[:, :, 0]
        + 0.587 * small[:, :, 1]
        + 0.114 * small[:, :, 2]
    ).astype(np.uint8)

    if previous_gray is None:
        previous_gray = gray
        return "WAIT", 0, "Building visual baseline"

    # Average pixel movement between frames.
    diff = np.mean(np.abs(gray.astype(np.float32) -
                          previous_gray.astype(np.float32)))

    previous_gray = gray

    # Screen may be static, paused, or disconnected.
    if diff < 1.0:
        return "WAIT", 0, "Screen movement too low"

    if diff < 3.0:
        return "WAIT", 55, "Low visual movement"

    # This is deliberately conservative.
    # A screen-feed movement alone is NOT enough to claim a trade.
    confidence = min(70, int(50 + diff * 2))

    return "WAIT", confidence, "Feed active; waiting for chart extraction"


def capture_loop():
    global fps_counter, fps_start

    while True:
        if not RTSP_FEED_URL:
            with lock:
                state["connected"] = False
                state["error"] = "RTSP_FEED_URL is not configured"
            time.sleep(3)
            continue

        container = None

        try:
            with lock:
                state["error"] = "Connecting to RTSP feed..."

            container = av.open(
                RTSP_FEED_URL,
                mode="r",
                options={
                    "rtsp_transport": "tcp",
                    "stimeout": "8000000",
                    "rw_timeout": "8000000",
                },
            )

            stream = next(
                (s for s in container.streams if s.type == "video"),
                None
            )

            if stream is None:
                raise RuntimeError("No video stream found")

            stream.thread_type = "AUTO"

            with lock:
                state["connected"] = True
                state["error"] = ""

            for packet in container.demux(stream):
                for frame in packet.decode():
                    image = frame.to_ndarray(format="bgr24")

                    now = time.time()

                    signal, confidence, reason = analyze_frame(image)

                    fps_counter += 1

                    if now - fps_start >= 1:
                        current_fps = fps_counter / (now - fps_start)
                        fps_counter = 0
                        fps_start = now
                    else:
                        current_fps = state["fps"]

                    with lock:
                        state["connected"] = True
                        state["last_frame_time"] = now
                        state["frames"] += 1
                        state["fps"] = round(current_fps, 1)
                        state["signal"] = signal
                        state["confidence"] = confidence
                        state["reason"] = reason
                        state["last_frame"] = image

        except Exception as exc:
            with lock:
                state["connected"] = False
                state["error"] = str(exc)
                state["signal"] = "WAIT"
                state["confidence"] = 0

            time.sleep(3)

        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass


def jpeg_bytes():
    with lock:
        frame = state["last_frame"]

    if frame is None:
        return None

    try:
        import cv2

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 80],
        )

        if not ok:
            return None

        return encoded.tobytes()

    except Exception:
        return None


def mjpeg_generator():
    while True:
        jpg = jpeg_bytes()

        if jpg:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpg
                + b"\r\n"
            )

        time.sleep(0.10)


HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALUCARD SIGNAL BOT</title>

<style>
body {
    margin: 0;
    background: #090909;
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #333;
}

.title {
    font-size: 27px;
    font-weight: bold;
    letter-spacing: 2px;
}

.subtitle {
    margin-top: 5px;
    color: #999;
    font-size: 12px;
}

.grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
    padding: 12px;
    max-width: 1200px;
    margin: auto;
}

.card {
    background: #121212;
    border: 1px solid #292929;
    border-radius: 12px;
    padding: 15px;
}

.label {
    color: #888;
    font-size: 12px;
    text-transform: uppercase;
}

.value {
    font-size: 24px;
    margin-top: 6px;
    font-weight: bold;
}

.live {
    color: #39e06f;
}

.dead {
    color: #ff4c4c;
}

.wait {
    color: #ffc857;
}

.feed {
    width: 100%;
    max-height: 650px;
    object-fit: contain;
    background: #000;
    border-radius: 8px;
    margin-top: 10px;
}

.row {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
}

.small {
    font-size: 13px;
    color: #aaa;
    margin-top: 8px;
}

.warning {
    padding: 12px;
    background: #211b08;
    border: 1px solid #55420d;
    border-radius: 8px;
    color: #e8c76b;
    font-size: 13px;
}
</style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD SIGNAL BOT</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="grid">

    <div class="card">
        <div class="label">Feed Status</div>
        <div id="status" class="value wait">CONNECTING</div>
        <div id="error" class="small"></div>
    </div>

    <div class="card">
        <div class="label">Screen Feed</div>
        <img class="feed" src="/stream">
    </div>

    <div class="card">

        <div class="row">

            <div>
                <div class="label">Signal</div>
                <div id="signal" class="value wait">WAIT</div>
            </div>

            <div>
                <div class="label">Confidence</div>
                <div id="confidence" class="value">0%</div>
            </div>

            <div>
                <div class="label">FPS</div>
                <div id="fps" class="value">0</div>
            </div>

            <div>
                <div class="label">Frames</div>
                <div id="frames" class="value">0</div>
            </div>

        </div>

        <div id="reason" class="small">
            Waiting for feed...
        </div>

    </div>

    <div class="warning">
        ScreenStream is being treated as a visual input.
        A live connection does not automatically mean the chart,
        asset, candle direction, entry price, or expiry has been
        correctly identified.
    </div>

</div>

<script>
async function update() {
    try {
        const r = await fetch("/api/status");
        const d = await r.json();

        const status = document.getElementById("status");
        status.textContent = d.connected ? "LIVE" : "OFFLINE";
        status.className = "value " + (d.connected ? "live" : "dead");

        const signal = document.getElementById("signal");
        signal.textContent = d.signal;

        if (d.signal === "CALL" || d.signal === "PUT") {
            signal.className = "value live";
        } else {
            signal.className = "value wait";
        }

        document.getElementById("confidence").textContent =
            d.confidence + "%";

        document.getElementById("fps").textContent =
            d.fps;

        document.getElementById("frames").textContent =
            d.frames;

        document.getElementById("reason").textContent =
            d.reason;

        document.getElementById("error").textContent =
            d.error || "";

    } catch (e) {
        document.getElementById("status").textContent = "OFFLINE";
        document.getElementById("status").className = "value dead";
    }
}

setInterval(update, 2000);
update();
</script>

</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():
    with lock:
        connected = state["connected"]
        last_frame = state["last_frame_time"]

        stale = (
            last_frame == 0
            or time.time() - last_frame > STREAM_TIMEOUT
        )

        result = {
            "connected": bool(connected and not stale),
            "signal": state["signal"],
            "confidence": state["confidence"],
            "reason": state["reason"],
            "fps": state["fps"],
            "frames": state["frames"],
            "error": state["error"],
            "last_frame_age": (
                round(time.time() - last_frame, 2)
               
