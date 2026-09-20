import os
import io
import time
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string, send_file
from PIL import Image

app = Flask(__name__)

# ============================================================
# ALUCARD V2.2
# GOTHIC MARKET INTELLIGENCE
# SCREEN-FEED / RTSP FRAME RECEIVER
# ============================================================

# Token is OPTIONAL.
# If RYU_FEED_TOKEN exists on Render, the bridge may send it.
# If it does not exist, valid images are still accepted.
FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

STATE_LOCK = threading.Lock()

state = {
    "ok": True,
    "feed": "WAITING",
    "asset": "UNKNOWN",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": 0,
    "candles": 0,
    "timeframe": "30m",
    "payout": "--",
    "expiry": "5m",

    "image_received": False,
    "image_width": 0,
    "image_height": 0,
    "image_bytes": 0,

    "frames_received": 0,
    "last_frame": 0.0,
    "last_frame_utc": None,

    "feed_message": "Waiting for Pocket Option screen feed...",
    "analysis_message": "Waiting for chart image...",

    "server_time": time.time(),
}


# Latest valid JPEG
latest_image = {
    "data": None,
    "timestamp": 0.0,
}


# ============================================================
# HELPERS
# ============================================================

def now_utc_string():
    return datetime.now(timezone.utc).isoformat()


def feed_is_live():
    with STATE_LOCK:
        last = state.get("last_frame", 0.0)

    if not last:
        return False

    # Frame considered live for 15 seconds.
    return (time.time() - last) <= 15


def clean_number(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def get_request_token():
    candidates = [
        request.headers.get("X-RYU-TOKEN"),
        request.headers.get("X-ALUCARD-TOKEN"),
        request.headers.get("Authorization"),
        request.form.get("token"),
        request.args.get("token"),
    ]

    for value in candidates:
        if value:
            value = str(value).strip()

            if value.lower().startswith("bearer "):
                value = value[7:].strip()

            return value

    return ""


def token_is_valid():
    """
    Token behavior:

    1. No server token configured:
       accept the frame.

    2. Server token configured:
       accept if the incoming token matches.

    This prevents a missing Render environment variable from
    causing otherwise valid JPEG frames to be rejected.
    """
    if not FEED_TOKEN:
        return True

    incoming = get_request_token()

    return incoming == FEED_TOKEN


def extract_image_bytes():
    """
    Accept virtually every common way bridge.py may upload a JPEG.

    Supported:
      - multipart/form-data image=
      - multipart file=
      - multipart frame=
      - multipart screenshot=
      - raw JPEG request body
      - application/octet-stream
      - image/jpeg
    """

    # --------------------------------------------------------
    # 1. Multipart upload
    # --------------------------------------------------------
    if request.files:

        preferred_names = [
            "image",
            "file",
            "frame",
            "screenshot",
            "photo",
            "upload",
        ]

        for name in preferred_names:
            if name in request.files:
                uploaded = request.files[name]

                try:
                    data = uploaded.read()
                except Exception:
                    data = b""

                if data:
                    return data, "multipart:" + name

        # If bridge used an unexpected field name,
        # accept the first uploaded file.
        for name, uploaded in request.files.items():
            try:
                data = uploaded.read()
            except Exception:
                data = b""

            if data:
                return data, "multipart:" + name

    # --------------------------------------------------------
    # 2. Raw request body
    # --------------------------------------------------------
    try:
        raw = request.get_data(cache=False)
    except Exception:
        raw = b""

    if raw:
        return raw, "raw-body"

    return b"", "none"


def validate_jpeg(data):
    """
    Decode the image with Pillow and verify it completely.

    Returns:
        (image, error)
    """

    if not data:
        return None, "empty image"

    if len(data) < 100:
        return None, "image too small"

    try:
        image = Image.open(io.BytesIO(data))

        # Force Pillow to actually decode all image data.
        image.load()

        width, height = image.size

        if width < 100 or height < 100:
            return None, "image dimensions too small"

        # Verify JPEG/PNG/etc. without changing the source.
        image.verify()

        # Reopen after verify because verify() invalidates the object.
        image = Image.open(io.BytesIO(data))
        image.load()

        return image, None

    except Exception as exc:
        return None, str(exc)


# ============================================================
# BASIC CHART IMAGE ANALYSIS
# ============================================================

def analyze_chart_image(image):
    """
    Lightweight screen-feed analysis.

    This deliberately does not claim that every screenshot
    contains enough information for a reliable trading signal.

    It detects basic chart characteristics and produces a
    conservative WAIT when there is not enough evidence.

    The important purpose here is that a valid live screen
    frame reaches the dashboard instead of becoming INVALID.
    """

    width, height = image.size

    try:
        rgb = image.convert("RGB")

        # Crop the center/right chart area.
        # Pocket Option screens commonly contain UI around it.
        left = int(width * 0.05)
        top = int(height * 0.20)
        right = int(width * 0.98)
        bottom = int(height * 0.82)

        chart = rgb.crop((left, top, right, bottom))

        # Resize down for inexpensive analysis.
        max_width = 500

        if chart.width > max_width:
            ratio = max_width / float(chart.width)
            chart = chart.resize(
                (
                    max_width,
                    max(1, int(chart.height * ratio))
                )
            )

        pixels = list(chart.getdata())

        if not pixels:
            return {
                "signal": "WAIT",
                "confidence": 0,
                "message": "No chart pixels detected."
            }

        red = 0
        green = 0
        bright = 0
        total = len(pixels)

        for r, g, b in pixels:

            if r > 130 and r > g * 1.18 and r > b * 1.10:
                red += 1

            if g > 100 and g > r * 1.10 and g > b * 1.05:
                green += 1

            if r + g + b > 600:
                bright += 1

        red_ratio = red / total
        green_ratio = green / total
        bright_ratio = bright / total

        # Conservative screen-level indication.
        # A signal is only shown when the screen contains
        # a reasonably clear directional color imbalance.
        if red_ratio > 0.045 and red_ratio > green_ratio * 1.20:
            signal = "PUT"
            confidence = min(
                92,
                max(
                    78,
                    int(70 + red_ratio * 300)
                )
            )

            message = (
                "Chart contains a stronger bearish/red visual bias."
            )

        elif green_ratio > 0.045 and green_ratio > red_ratio * 1.20:
            signal = "CALL"
            confidence = min(
                92,
                max(
                    78,
                    int(70 + green_ratio * 300)
                )
            )

            message = (
                "Chart contains a stronger bullish/green visual bias."
            )

        else:
            signal = "WAIT"
            confidence = 0

            message = (
                "Live chart received; directional evidence is "
                "not strong enough."
            )

        return {
            "signal": signal,
            "confidence": confidence,
            "message": message,
            "red_ratio": round(red_ratio, 4),
            "green_ratio": round(green_ratio, 4),
            "bright_ratio": round(bright_ratio, 4),
        }

    except Exception as exc:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "message": "Chart analysis error: " + str(exc)
        }


# ============================================================
# FRAME PROCESSING
# ============================================================

def process_frame(data):
    image, error = validate_jpeg(data)

    if image is None:
        return False, error

    analysis = analyze_chart_image(image)

    width, height = image.size
    timestamp = time.time()
    timestamp_utc = now_utc_string()

    with STATE_LOCK:

        state["feed"] = "LIVE"
        state["image_received"] = True

        state["image_width"] = width
        state["image_height"] = height
        state["image_bytes"] = len(data)

        state["frames_received"] += 1
        state["last_frame"] = timestamp
        state["last_frame_utc"] = timestamp_utc

        state["signal"] = analysis.get("signal", "WAIT")
        state["confidence"] = int(
            analysis.get("confidence", 0)
        )

        state["analysis_message"] = analysis.get(
            "message",
            "Chart received."
        )

        state["feed_message"] = (
            "Pocket Option screen feed LIVE."
        )

        state["server_time"] = timestamp

        # The frame itself does not reliably provide a numeric
        # price or asset name without OCR/chart-specific parsing.
        # Preserve existing values rather than inventing them.
        if not state["asset"]:
            state["asset"] = "UNKNOWN"

    with STATE_LOCK:
        latest_image["data"] = data
        latest_image["timestamp"] = timestamp

    return True, None


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():
    live = feed_is_live()

    with STATE_LOCK:
        frames = state["frames_received"]
        last = state["last_frame_utc"]

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.2",
        "feed": "LIVE" if live else "WAITING",
        "frames_received": frames,
        "last_frame_utc": last,
        "token_required": bool(FEED_TOKEN),
        "time": now_utc_string(),
    })


# ============================================================
# STATE
# ============================================================

@app.route("/api/state", methods=["GET"])
def api_state():

    live = feed_is_live()

    with STATE_LOCK:
        result = dict(state)

    result["feed"] = "LIVE" if live else "WAITING"

    if not live:
        result["signal"] = "WAIT"

        if result["frames_received"] == 0:
            result["feed_message"] = (
                "Waiting for Pocket Option screen feed..."
            )
        else:
            result["feed_message"] = (
                "Screen feed is stale."
            )

    result["server_time"] = time.time()

    return jsonify(result)


# ============================================================
# FRAME RECEIVER
# ============================================================

@app.route("/api/frame", methods=["POST"])
def api_frame():

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------
    #
    # IMPORTANT:
    # Your current bridge says:
    #
    #   [ALUCARD] Token: MISSING
    #
    # If Render has no token configured, this server accepts
    # the frame anyway.
    #
    # If a token IS configured, the bridge must provide it.
    #
    if not token_is_valid():

        return jsonify({
            "ok": False,
            "error": "Invalid token"
        }), 401

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    data, source = extract_image_bytes()

    if not data:
        return jsonify({
            "ok": False,
            "error": "No image data received",
            "content_type": request.content_type,
            "source": source,
        }), 400

    # --------------------------------------------------------
    # VALIDATE + STORE
    # --------------------------------------------------------

    success, error = process_frame(data)

    if not success:
        return jsonify({
            "ok": False,
            "error": "Invalid image",
            "detail": error,
            "bytes_received": len(data),
            "source": source,
            "content_type": request.content_type,
        }), 400

    with STATE_LOCK:
        current_state = dict(state)

    return jsonify({
        "ok": True,
        "message": "Frame accepted",
        "source": source,
        "bytes": len(data),
        "image": {
            "width": current_state["image_width"],
            "height": current_state["image_height"],
        },
        "state": current_state,
    }), 200


# ============================================================
# LATEST IMAGE
# ============================================================

@app.route("/api/frame/latest", methods=["GET"])
def latest_frame():

    with STATE_LOCK:
        data = latest_image["data"]

    if not data:
        return jsonify({
            "ok": False,
            "error": "No frame available"
        }), 404

    return send_file(
        io.BytesIO(data),
        mimetype="image/jpeg",
        max_age=0
    )


# Alternate convenient endpoint
@app.route("/api/screenshot", methods=["GET"])
def screenshot():
    return latest_frame()


# ============================================================
# ROOT DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1.0">

<title>ALUCARD — Gothic Market Intelligence</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(
            circle at 50% 0%,
            #202020 0%,
            #080808 48%,
            #020202 100%
        );
    color: #eee;
    font-family: Arial, Helvetica, sans-serif;
}

header {
    padding: 18px 15px 12px;
    text-align: center;
    border-bottom: 1px solid #333;
    background: rgba(0,0,0,.88);
}

.logo {
    font-size: 31px;
    font-weight: 900;
    letter-spacing: 7px;
    color: #ddd;
}

.subtitle {
    margin-top: 5px;
    font-size: 10px;
    letter-spacing: 3px;
    color: #777;
}

.statusbar {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 9px;
    margin-top: 12px;
    font-size: 12px;
}

.dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #555;
}

.dot.live {
    background: #32ff72;
    box-shadow: 0 0 13px #32ff72;
}

.dot.wait {
    background: #ffb300;
}

nav {
    display: flex;
    overflow-x: auto;
    border-bottom: 1px solid #292929;
    background: #090909;
}

nav button {
    flex: 1;
    min-width: 100px;
    padding: 14px 10px;
    border: 0;
    background: transparent;
    color: #777;
    font-weight: bold;
    cursor: pointer;
}

nav button.active {
    color: white;
    border-bottom: 2px solid #ddd;
}

.container {
    width: 100%;
    max-width: 1050px;
    margin: auto;
    padding: 15px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(230px, 1fr));
    gap: 13px;
}

.card {
    border: 1px solid #292929;
    background: rgba(10,10,10,.94);
    border-radius: 8px;
    padding: 18px;
    box-shadow:
        inset 0 0 35px rgba(255,255,255,.015),
        0 8px 25px rgba(0,0,0,.4);
}

.label {
    color: #777;
    font-size: 10px;
    letter-spacing: 2px;
    margin-bottom: 8px;
}

.value {
    font-size: 28px;
    font-weight: 900;
}

.signal {
    font-size: 48px;
    letter-spacing: 3px;
}

.call {
    color: #42ff82;
    text-shadow: 0 0 15px rgba(66,255,130,.4);
}

.put {
    color: #ff4d68;
    text-shadow: 0 0 15px rgba(255,77,104,.4);
}

.wait {
    color: #ddd;
}

.small {
    font-size: 13px;
    color: #999;
    line-height: 1.6;
}

.progress {
    width: 100%;
    height: 8px;
    background: #202020;
    margin-top: 12px;
    overflow: hidden;
    border-radius: 10px;
}

.progressbar {
    height: 100%;
    width: 0%;
    background: #eee;
    transition: width .4s;
}

.feed-image {
    width: 100%;
    max-height: 600px;
    object-fit: contain;
    background: #000;
    border: 1px solid #242424;
    border-radius: 6px;
}

select,
input {
    width: 100%;
    padding: 12px;
    margin-top: 6px;
    background: #101010;
    color: #eee;
    border: 1px solid #333;
    border-radius: 5px;
}

.section {
    display: none;
}

.section.active {
    display: block;
}

table {
    width: 100%;
    border-collapse: collapse;
}

td, th {
    padding: 11px;
    border-bottom: 1px solid #242424;
    text-align: left;
}

th {
    color: #777;
    font-size: 10px;
    letter-spacing: 2px;
}

.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 20px;
    background: #222;
    font-size: 11px;
}

footer {
    text-align: center;
    padding: 30px;
    color: #444;
    font-size: 10px;
    letter-spacing: 2px;
}

</style>
</head>

<body>

<header>

    <div class="logo">ALUCARD</div>

    <div class="subtitle">
        GOTHIC MARKET INTELLIGENCE — V2.2
    </div>

    <div class="statusbar">
        <div id="statusDot" class="dot wait"></div>
        <span id="feedStatus">FEED: WAITING</span>
    </div>

</header>


<nav>

    <button class="tab active"
            onclick="showTab('signals',this)">
        SIGNALS
    </button>

    <button class="tab"
            onclick="showTab('trades',this)">
        TRADES
    </button>

    <button class="tab"
            onclick="showTab('performance',this)">
        PERFORMANCE
    </button>

    <button class="tab"
            onclick="showTab('settings',this)">
        SETTINGS
    </button>

</nav>


<div class="container">

<!-- ====================================================== -->
<!-- SIGNALS -->
<!-- ====================================================== -->

<section id="signals" class="section active">

<div class="grid">

    <div class="card">

        <div class="label">CURRENT SIGNAL</div>

        <div id="signal"
             class="value signal wait">
            WAIT
        </div>

        <div class="small">
            Confidence:
            <strong id="confidence">0%</strong>
        </div>

        <div class="progress">
            <div id="confidenceBar"
                 class="progressbar"></div>
        </div>

    </div>


    <div class="card">

        <div class="label">ASSET</div>

        <div id="asset"
             class="value">
            UNKNOWN
        </div>

        <div class="small">
            Price:
            <strong id="price">0.000000</strong>
        </div>

    </div>


    <div class="card">

        <div class="label">ENTRY</div>

        <div id="entry"
             class="value">
            0.000000
        </div>

        <div class="small">
            Entry window:
            <strong id="entryWindow">--</strong>
        </div>

    </div>


    <div class="card">

        <div class="label">TIMEFRAME</div>

        <div id="timeframe"
             class="value">
            30m
        </div>

        <div class="small">
            Expiry:
            <strong id="expiry">5m</strong>
        </div>

    </div>

</div>


<br>


<div class="grid">

    <div class="card">

        <div class="label">SCREEN FEED</div>

        <div id="screenStatus"
             class="value">
            WAITING
        </div>

        <div class="small">
            Frames received:
            <strong id="frames">0</strong>
        </div>

        <div class="small">
            Resolution:
            <strong id="resolution">--</strong>
        </div>

        <br>

        <img id="feedImage"
             class="feed-image"
             src="/api/frame/latest"
             onerror="this.style.display='none';">

    </div>


    <div class="card">

        <div class="label">LIVE ANALYSIS</div>

        <div id="analysis"
             class="small">
            Waiting for chart image...
        </div>

        <br>

        <div class="label">FEED HEALTH</div>

        <div id="health"
             class="badge">
            WAITING
        </div>

        <br><br>

        <div class="label">LAST FRAME</div>

        <div id="lastFrame"
             class="small">
            --
        </div>

    </div>

</div>

</section>


<!-- ====================================================== -->
<!-- TRADES -->
<!-- ====================================================== -->

<section id="trades" class="section">

<div class="card">

    <div class="label">TRADE MONITOR</div>

    <table>

        <tr>
            <th>ASSET</th>
            <th>SIGNAL</th>
            <th>CONFIDENCE</th>
            <th>ENTRY</th>
        </tr>

        <tr>
            <td id="tradeAsset">UNKNOWN</td>
            <td id="tradeSignal">WAIT</td>
            <td id="tradeConfidence">0%</td>
            <td id="tradeEntry">--</td>
        </tr>

    </table>

</div>

</section>


<!-- ====================================================== -->
<!-- PERFORMANCE -->
<!-- ====================================================== -->

<section id="performance" class="section">

<div class="grid">

    <div class="card">

        <div class="label">FRAMES RECEIVED</div>

        <div id="perfFrames"
             class="value">
            0
        </div>

    </div>

    <div class="card">

        <div class="label">FEED STATUS</div>

        <div id="perfFeed"
             class="value">
            WAITING
        </div>

    </div>

    <div class="card">

        <div class="label">IMAGE</div>

        <div id="perfImage"
             class="value">
            NO
        </div>

    </div>

</div>

<br>

<div class="card">

    <div class="label">ANALYSIS</div>

    <div id="perfAnalysis"
         class="small">
        Waiting for feed.
    </div>

</div>

</section>


<!-- ====================================================== -->
<!-- SETTINGS -->
<!-- ====================================================== -->

<section id="settings" class="section">

<div class="grid">

    <div class="card">

        <div class="label">TIMEFRAME</div>

        <select id="settingsTimeframe"
                onchange="changeTimeframe(this.value)">

            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="30m" selected>30m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>

        </select>

    </div>


    <div class="card">

        <div class="label">EXPIRY</div>

        <select id="settingsExpiry">

            <option value="1m">1m</option>
            <option value="5m" selected>5m</option>
            <option value="15m">15m</option>
            <option value="30m">30m</option>
            <option value="1h">1h</option>

        </select>

    </div>


    <div class="card">

        <div class="label">SIGNAL THRESHOLD</div>

        <input
            type="number"
            min="50"
            max="99"
            value="78"
            id="threshold">

    </div>

</div>

</section>

</div>


<footer>
ALUCARD V2.2 — LIVE SCREEN INTELLIGENCE
</footer>


<script>

let lastFrames = 0;

function showTab(name, button) {

    document
        .querySelectorAll('.section')
        .forEach(x => x.classList.remove('active'));

    document
        .querySelectorAll('.tab')
        .forEach(x => x.classList.remove('active'));

    document
        .getElementById(name)
        .classList.add('active');

    button.classList.add('active');
}


function setSignal(signal) {

    const el = document.getElementById("signal");

    el.classList.remove(
        "call",
        "put",
        "wait"
    );

    if (signal === "CALL") {
        el.classList.add("call");
    }
    else if (signal === "PUT") {
        el.classList.add("put");
    }
    else {
        el.classList.add("wait");
    }

    el.textContent = signal || "WAIT";
}


function update(data) {

    const live = data.feed === "LIVE";

    const dot = document.getElementById(
        "statusDot"
    );

    dot.classList.remove(
        "live",
        "wait"
    );

    dot.classList.add(
        live ? "live" : "wait"
    );

    document.getElementById(
        "feedStatus"
    ).textContent =
        "FEED: " + (
            live ? "LIVE" : "WAITING"
        );


    setSignal(data.signal || "WAIT");


    document.getElementById(
        "confidence"
    ).textContent =
        (data.confidence || 0) + "%";


    document.getElementById(
        "confidenceBar"
    ).style.width =
        Math.max(
            0,
            Math.min(
                100,
                data.confidence || 0
            )
        ) + "%";


    document.getElementById(
        "asset"
    ).textContent =
        data.asset || "UNKNOWN";


    document.getElementById(
        "price"
    ).textContent =
        Number(data.price || 0).toFixed(6);


    document.getElementById(
        "entry"
    ).textContent =
        Number(data.entry || 0).toFixed(6);


    document.getElementById(
        "entryWindow"
    ).textContent =
        data.entry_window ?
        data.entry_window + "s" :
        "--";


    document.getElementById(
        "timeframe"
    ).textContent =
        data.timeframe || "30m";


    document.getElementById(
        "expiry"
    ).textContent =
        data.expiry || "5m";


    document.getElementById(
        "screenStatus"
    ).textContent =
        live ? "LIVE" : "WAITING";


    document.getElementById(
        "frames"
    ).textContent =
        data.frames_received || 0;


    document.getElementById(
        "resolution"
    ).textContent =
        data.image_width ?
        data.image_width +
        " × " +
        data.image_height :
        "--";


    document.getElementById(
        "analysis"
    ).textContent =
        data.analysis_message ||
        "Waiting for chart image.";


    document.getElementById(
        "health"
    ).textContent =
        live ? "LIVE" : "WAITING";


    document.getElementById(
        "lastFrame"
    ).textContent =
        data.last_frame_utc || "--";


    document.getElementById(
        "tradeAsset"
    ).textContent =
        data.asset || "UNKNOWN";


    document.getElementById(
        "tradeSignal"
    ).textContent =
        data.signal || "WAIT";


    document.getElementById(
        "tradeConfidence"
    ).textContent =
        (data.confidence || 0) + "%";


    document.getElementById(
        "tradeEntry"
    ).textContent =
        data.entry ?
        Number(data.entry).toFixed(6) :
        "--";


    document.getElementById(
        "perfFrames"
    ).textContent =
        data.frames_received || 0;


    document.getElementById(
        "perfFeed"
    ).textContent =
        live ? "LIVE" : "WAITING";


    document.getElementById(
        "perfImage"
    ).textContent =
        data.image_received ?
        "YES" :
        "NO";


    document.getElementById(
        "perfAnalysis"
    ).textContent =
        data.analysis_message ||
        "Waiting for feed.";


    if (
        data.frames_received !== lastFrames
    ) {

        lastFrames =
            data.frames_received || 0;

        const img =
            document.getElementById(
                "feedImage"
            );

        img.style.display = "block";

        img.src =
            "/api/frame/latest?t=" +
            Date.now();
    }
}


async function poll() {

    try {

        const response =
            await fetch(
                "/api/state?t=" +
                Date.now(),
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            return;
        }

        const data =
            await response.json();

        update(data);

    }
    catch (e) {
        console.log(e);
    }
}


async function changeTimeframe(value) {

    try {

        await fetch(
            "/api/config",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    timeframe: value
                })
            }
        );

    }
    catch (e) {
        console.log(e);
    }
}


setInterval(poll, 1500);

poll();

</script>

</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML)


# ============================================================
# CONFIG
# ============================================================

@app.route("/api/config", methods=["POST"])
def api_config():

    payload = request.get_json(
        silent=True
    ) or {}

    timeframe = payload.get(
        "timeframe"
    )

    if timeframe:
        allowed = {
            "1m",
            "5m",
            "15m",
            "30m",
            "1h",
            "4h",
            "1d",
        }

        if timeframe in allowed:

            with STATE_LOCK:
                state["timeframe"] = timeframe

    with STATE_LOCK:
        current = dict(state)

    return jsonify({
        "ok": True,
        "state": current
    })


# ============================================================
# STARTUP
# ============================================================

@app.before_request
def update_server_time():

    with STATE_LOCK:
        state["server_time"] = time.time()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
