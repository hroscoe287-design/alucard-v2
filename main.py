from flask import Flask, request, jsonify, Response
import time
import io
import threading
import math

from PIL import Image, ImageFilter

app = Flask(__name__)

# ============================================================
# ALUCARD V2.1
# LIVE SCREEN FEED + IMAGE CANDLE ANALYSIS
# No OpenCV required
# ============================================================

FRAME_TIMEOUT = 25
MAX_FRAMES = 60

latest_frame = None
lock = threading.Lock()

state = {
    "feed": "DISCONNECTED",
    "connected": False,
    "image_received": False,
    "last_update": 0,
    "last_frame": "none",
    "frame_count": 0,

    "asset": "EURUSD",
    "price": 0.0,

    "signal": "WAIT",
    "confidence": 0,

    "entry": 0.0,
    "entry_window": 12,
    "candles": 0,
    "fractal": 2,
    "expiry": "5m",

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "rsi": 0.0,
    "cci": 0.0,
    "atr": 0.0,

    "analysis": "Waiting for enough chart data..."
}

# Screen-derived candle measurements.
# These are normalized chart measurements, not fabricated market prices.
candle_history = []


# ============================================================
# TIME
# ============================================================

def utc_text():
    return time.strftime(
        "%Y-%m-%d %H:%M:%S UTC",
        time.gmtime()
    )


# ============================================================
# FEED STATUS
# ============================================================

def update_status():
    with lock:
        last = state["last_update"]

        if last and (time.time() - last) <= FRAME_TIMEOUT:
            state["feed"] = "LIVE"
            state["connected"] = True
        else:
            state["feed"] = "DISCONNECTED"
            state["connected"] = False


# ============================================================
# BASIC MATH
# ============================================================

def ema(values, period):
    if len(values) < period:
        return 0.0

    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period

    for x in values[period:]:
        value = (x * k) + (value * (1.0 - k))

    return value


def rsi(values, period=14):
    if len(values) <= period:
        return 0.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def cci(values, period=20):
    if len(values) < period:
        return 0.0

    window = values[-period:]
    mean = sum(window) / period

    deviations = [
        abs(x - mean)
        for x in window
    ]

    mean_deviation = sum(deviations) / period

    if mean_deviation == 0:
        return 0.0

    return (values[-1] - mean) / (0.015 * mean_deviation)


def atr(values, period=14):
    if len(values) <= period:
        return 0.0

    ranges = []

    for i in range(1, len(values)):
        ranges.append(abs(values[i] - values[i - 1]))

    return sum(ranges[-period:]) / period


# ============================================================
# IMAGE ANALYSIS
# ============================================================

def image_to_candle_series(image):
    """
    Attempts to detect vertical candle-like structures from
    the incoming screenshot.

    This does NOT claim to know the broker's actual price scale.
    It extracts relative candle movement from the chart image.
    """

    try:
        img = image.convert("RGB")

        width, height = img.size

        if width < 100 or height < 100:
            return []

        # Work on a smaller copy for speed.
        target_width = 500

        ratio = target_width / float(width)
        target_height = max(100, int(height * ratio))

        img = img.resize(
            (target_width, target_height)
        )

        img = img.filter(
            ImageFilter.SHARPEN
        )

        w, h = img.size

        # Ignore top/bottom UI regions.
        top = int(h * 0.18)
        bottom = int(h * 0.82)

        if bottom <= top:
            return []

        pixels = img.load()

        # Calculate brightness/color contrast by x column.
        column_activity = []

        for x in range(w):
            active = 0

            for y in range(top, bottom, 3):
                r, g, b = pixels[x, y]

                brightness = (
                    int(r) +
                    int(g) +
                    int(b)
                ) / 3.0

                # Bright chart marks against dark chart background.
                if brightness > 125:
                    active += 1

            column_activity.append(active)

        # Group active columns.
        groups = []
        start = None

        for x, value in enumerate(column_activity):

            if value >= 2:

                if start is None:
                    start = x

            else:

                if start is not None:
                    if x - start >= 1:
                        groups.append((start, x - 1))

                    start = None

        if start is not None:
            groups.append((start, w - 1))

        # Filter tiny UI/noise groups.
        groups = [
            g for g in groups
            if 2 <= (g[1] - g[0] + 1) <= 20
        ]

        if len(groups) < 5:
            return []

        # Sample centers of groups.
        centers = []

        for left, right in groups:
            center = (left + right) // 2

            ys = []

            for y in range(top, bottom, 2):

                r, g, b = pixels[center, y]

                brightness = (
                    int(r) +
                    int(g) +
                    int(b)
                ) / 3.0

                if brightness > 125:
                    ys.append(y)

            if len(ys) >= 2:

                high = min(ys)
                low = max(ys)
                middle = (high + low) / 2.0

                centers.append(
                    (middle, high, low)
                )

        if len(centers) < 5:
            return []

        # Convert screen Y position to normalized price movement.
        # Lower Y = higher chart value.
        values = []

        for middle, high, low in centers:
            normalized = (
                (bottom - middle) /
                max(1.0, float(bottom - top))
            )

            values.append(normalized)

        # Remove obviously impossible values.
        values = [
            max(0.0, min(1.0, x))
            for x in values
        ]

        return values[-MAX_FRAMES:]

    except Exception:
        return []


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze_series(values):

    if len(values) < 20:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "ema9": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "rsi": 0.0,
            "cci": 0.0,
            "atr": 0.0,
            "analysis": "Waiting for 20+ usable chart observations..."
        }

    e9 = ema(values, 9)
    e20 = ema(values, 20)

    # EMA50 needs 50 observations.
    e50 = ema(values, 50) if len(values) >= 50 else 0.0

    r = rsi(values)
    c = cci(values)
    a = atr(values)

    current = values[-1]

    score_call = 0
    score_put = 0

    # Trend
    if e9 > e20:
        score_call += 2
    elif e9 < e20:
        score_put += 2

    # Momentum
    if r >= 55:
        score_call += 1
    elif r <= 45:
        score_put += 1

    # CCI
    if c > 50:
        score_call += 1
    elif c < -50:
        score_put += 1

    # Recent movement
    recent = values[-5:]

    if recent[-1] > recent[0]:
        score_call += 1
    elif recent[-1] < recent[0]:
        score_put += 1

    total = score_call + score_put

    if total < 3:
        signal = "WAIT"
        confidence = 0
        explanation = "Mixed or insufficient chart evidence."

    elif score_call > score_put:
        confidence = min(
            95,
            60 + (score_call - score_put) * 8
        )

        signal = "CALL"

        explanation = (
            "Relative chart momentum is bullish; "
            "waiting for stronger confirmation before entry."
        )

    elif score_put > score_call:
        confidence = min(
            95,
            60 + (score_put - score_call) * 8
        )

        signal = "PUT"

        explanation = (
            "Relative chart momentum is bearish; "
            "waiting for stronger confirmation before entry."
        )

    else:
        signal = "WAIT"
        confidence = 0
        explanation = "Signals are balanced."

    # Do not allow a trade signal from weak evidence.
    if confidence < 78:
        signal = "WAIT"
        explanation = (
            "Chart detected, but confirmation threshold "
            "has not been reached."
        )

    return {
        "signal": signal,
        "confidence": int(confidence),

        "ema9": round(e9, 6),
        "ema20": round(e20, 6),
        "ema50": round(e50, 6),

        "rsi": round(r, 2),
        "cci": round(c, 2),
        "atr": round(a, 6),

        "analysis": explanation
    }


# ============================================================
# PROCESS IMAGE
# ============================================================

def process_image(data):

    global candle_history

    try:
        image = Image.open(
            io.BytesIO(data)
        )

        image.load()

    except Exception:
        return False

    values = image_to_candle_series(image)

    with lock:

        state["image_received"] = True
        state["candles"] = len(values)

        if values:

            candle_history = values

            analysis = analyze_series(values)

            state.update(analysis)

            # The screenshot gives relative movement,
            # not a verified broker price.
            state["price"] = 0.0
            state["entry"] = 0.0

            if state["signal"] == "WAIT":
                state["entry_window"] = 12
            else:
                state["entry_window"] = 12

        else:

            state["signal"] = "WAIT"
            state["confidence"] = 0

            state["analysis"] = (
                "Live screen received. "
                "Chart candles not yet detected."
            )

            state["price"] = 0.0
            state["entry"] = 0.0

    return True


# ============================================================
# HEALTH
# ============================================================

@app.route("/health", methods=["GET"])
def health():

    update_status()

    with lock:
        return jsonify({
            "ok": True,
            "service": "Alucard V2.1",
            "feed": state["feed"],
            "connected": state["connected"],
            "frames": state["frame_count"]
        })


# ============================================================
# STATE
# ============================================================

@app.route("/api/state", methods=["GET"])
def api_state():

    update_status()

    with lock:
        result = dict(state)

    return jsonify(result)


@app.route("/api/status", methods=["GET"])
def api_status():

    update_status()

    with lock:
        return jsonify({
            "feed": state["feed"],
            "connected": state["connected"],
            "image_received": state["image_received"],
            "frame_count": state["frame_count"],
            "last_frame": state["last_frame"]
        })


# ============================================================
# IMAGE FRAME RECEIVER
# ============================================================

@app.route("/api/frame", methods=["POST"])
def receive_frame():

    global latest_frame

    data = None

    # Raw image body.
    if request.data:
        data = request.data

    # Multipart uploads.
    if not data and request.files:

        for name in [
            "frame",
            "image",
            "file",
            "screenshot"
        ]:

            if name in request.files:
                data = request.files[name].read()
                break

        if not data:
            first = next(
                iter(request.files.values())
            )

            data = first.read()

    if not data:

        return jsonify({
            "ok": False,
            "error": "No image/frame received"
        }), 400

    # Verify image.
    try:

        test = Image.open(
            io.BytesIO(data)
        )

        test.verify()

    except Exception:

        return jsonify({
            "ok": False,
            "error": "Invalid image"
        }), 400

    now = time.time()
    stamp = utc_text()

    with lock:

        latest_frame = data

        state["feed"] = "LIVE"
        state["connected"] = True
        state["image_received"] = True
        state["last_update"] = now
        state["last_frame"] = stamp
        state["frame_count"] += 1

    # Analyze outside the state lock.
    process_image(data)

    return jsonify({
        "ok": True,
        "message": "Screen frame accepted",
        "feed": "LIVE",
        "connected": True,
        "image_received": True,
        "last_frame": stamp,
        "frame_count": state["frame_count"]
    })


# ============================================================
# JSON FEED COMPATIBILITY
# ============================================================

@app.route("/api/feed", methods=["POST"])
def receive_feed():

    payload = request.get_json(
        silent=True
    )

    if not payload:

        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    now = time.time()

    with lock:

        if "asset" in payload:
            state["asset"] = str(
                payload["asset"]
            )

        for key in [
            "price",
            "confidence",
            "entry",
            "entry_window",
            "candles",
            "fractal",
            "ema9",
            "ema20",
            "ema50",
            "rsi",
            "cci",
            "atr"
        ]:

            if key in payload:
                state[key] = payload[key]

        if "signal" in payload:
            state["signal"] = str(
                payload["signal"]
            )

        if "analysis" in payload:
            state["analysis"] = str(
                payload["analysis"]
            )

        state["feed"] = "LIVE"
        state["connected"] = True
        state["image_received"] = False
        state["last_update"] = now
        state["last_frame"] = utc_text()

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": dict(state)
    })


# ============================================================
# IMAGE VIEW
# ============================================================

@app.route("/api/frame.jpg", methods=["GET"])
def frame_jpg():

    update_status()

    with lock:
        frame = latest_frame

    if not frame:

        return jsonify({
            "ok": False,
            "error": "No frame available"
        }), 404

    return Response(
        frame,
        mimetype="image/jpeg",
        headers={
            "Cache-Control":
                "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
    )


@app.route("/api/screen/latest", methods=["GET"])
def screen_latest():

    return frame_jpg()


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/", methods=["GET"])
def dashboard():

    html = r"""
<!DOCTYPE html>
<html>
<head>

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>

* {
    box-sizing:border-box;
}

body {
    margin:0;
    background:#050505;
    color:#eee;
    font-family:Arial,sans-serif;
}

.header {
    text-align:center;
    padding:18px 10px 10px;
    border-bottom:1px solid #282828;
}

.title {
    font-size:30px;
    font-weight:900;
    letter-spacing:5px;
}

.subtitle {
    color:#888;
    font-size:13px;
    margin-top:5px;
    letter-spacing:1px;
}

.tabs {
    display:flex;
    justify-content:center;
    gap:5px;
    padding:10px;
    border-bottom:1px solid #222;
}

.tab {
    padding:9px 12px;
    border:1px solid #333;
    border-radius:6px;
    color:#aaa;
    font-size:12px;
}

.tab.active {
    color:#fff;
    border-color:#666;
}

.status {
    margin:12px;
    padding:12px;
    border:1px solid #333;
    border-radius:7px;
    text-align:center;
    font-weight:bold;
}

.live {
    color:#00ff66;
}

.dead {
    color:#ff4444;
}

.last {
    text-align:center;
    color:#888;
    font-size:12px;
    margin-bottom:12px;
}

.section {
    margin:12px;
    color:#999;
    font-size:12px;
}

select {
    width:calc(100% - 24px);
    margin:0 12px 12px;
    padding:12px;
    background:#111;
    color:#fff;
    border:1px solid #333;
    border-radius:7px;
}

.grid {
    display:grid;
    grid-template-columns:repeat(2,1fr);
    gap:9px;
    padding:12px;
}

.card {
    background:#101010;
    border:1px solid #292929;
    border-radius:7px;
    padding:13px;
}

.label {
    color:#777;
    font-size:11px;
}

.value {
    margin-top:6px;
    font-size:21px;
    font-weight:bold;
}

.signal {
    grid-column:span 2;
    text-align:center;
}

.signal .value {
    font-size:34px;
}

.screen {
    margin:12px;
    border:1px solid #333;
    border-radius:7px;
    overflow:hidden;
    background:#000;
}

.screen img {
    width:100%;
    display:block;
}

.analysis {
    margin:12px;
    padding:14px;
    border:1px solid #333;
    background:#101010;
    border-radius:7px;
}

.analysisText {
    margin-top:7px;
    line-height:1.4;
}

</style>

</head>

<body>

<div class="header">

<div class="title">ALUCARD</div>

<div class="subtitle">
GOTHIC MARKET INTELLIGENCE — V2.1
</div>

</div>

<div class="tabs">

<div class="tab active">Signals</div>
<div class="tab">Trades</div>
<div class="tab">Performance</div>
<div class="tab">Settings</div>

</div>

<div id="status"
     class="status dead">
Feed: DISCONNECTED
</div>

<div id="last"
     class="last">
WAITING — last frame: none
</div>

<div class="section">
Currency / Asset
</div>

<select id="assetSelect">

<option>EURUSD</option>
<option>GBPUSD</option>
<option>USDJPY</option>
<option>USDCHF</option>
<option>USDCAD</option>
<option>AUDUSD</option>
<option>NZDUSD</option>

<option>EURGBP</option>
<option>EURJPY</option>
<option>GBPJPY</option>
<option>EURCHF</option>
<option>GBPCHF</option>

<option>EURUSD OTC</option>
<option>GBPUSD OTC</option>
<option>USDJPY OTC</option>
<option>EURJPY OTC</option>
<option>GBPJPY OTC</option>

<option>BTCUSD</option>
<option>ETHUSD</option>
<option>XRPUSD</option>

<option>Gold</option>
<option>Silver</option>
<option>Oil</option>
<option>Natural Gas</option>

<option>AAPL</option>
<option>TSLA</option>
<option>AMZN</option>
<option>MSFT</option>

<option>SP500</option>
<option>NASDAQ</option>
<option>DOW</option>

</select>

<div class="grid">

<div class="card signal">
<div class="label">SIGNAL</div>
<div id="signal" class="value">WAIT</div>
</div>

<div class="card">
<div class="label">PRICE</div>
<div id="price" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">CONFIDENCE</div>
<div id="confidence" class="value">0%</div>
</div>

<div class="card">
<div class="label">ENTRY</div>
<div id="entry" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">ENTRY WINDOW</div>
<div id="window" class="value">12s</div>
</div>

<div class="card">
<div class="label">CANDLES</div>
<div id="candles" class="value">0</div>
</div>

<div class="card">
<div class="label">FRACTAL</div>
<div id="fractal" class="value">2</div>
</div>

<div class="card">
<div class="label">EXPIRY</div>
<div id="expiry" class="value">5m</div>
</div>

<div class="card">
<div class="label">EMA 9</div>
<div id="ema9" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">EMA 20</div>
<div id="ema20" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">EMA 50</div>
<div id="ema50" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">RSI</div>
<div id="rsi" class="value">0.00</div>
</div>

<div class="card">
<div class="label">CCI</div>
<div id="cci" class="value">0.00</div>
</div>

<div class="card">
<div class="label">ATR</div>
<div id="atr" class="value">0.000000</div>
</div>

</div>

<div class="screen">

<img id="screenImage"
     src="/api/frame.jpg"
     onerror="this.style.display='none';">

</div>

<div class="analysis">

<div class="label">
LIVE ANALYSIS
</div>

<div id="analysis"
     class="analysisText">
Waiting for screen feed...
</div>

</div>

<script>

async function updateDashboard() {

    try {

        const response =
            await fetch(
                "/api/state?t=" +
                Date.now(),
                {
                    cache:"no-store"
                }
            );

        const d =
            await response.json();

        const status =
            document.getElementById(
                "status"
            );

        const last =
            document.getElementById(
                "last"
            );

        if (d.feed === "LIVE") {

            status.innerText =
                "Feed: LIVE   |   Asset: " +
                (d.asset || "UNKNOWN");

            status.className =
                "status live";

            last.innerText =
                "LIVE — last frame: " +
                (d.last_frame || "unknown");

        } else {

            status.innerText =
                "Feed: DISCONNECTED   |   Asset: " +
                (d.asset || "UNKNOWN");

            status.className =
                "status dead";

            last.innerText =
                "WAITING — last frame: " +
                (d.last_frame || "none");
        }

        document.getElementById(
            "signal"
        ).innerText =
            d.signal || "WAIT";

        document.getElementById(
            "price"
        ).innerText =
            Number(d.price || 0)
            .toFixed(6);

        document.getElementById(
            "confidence"
        ).innerText =
            (d.confidence || 0) + "%";

        document.getElementById(
            "entry"
        ).innerText =
            Number(d.entry || 0)
            .toFixed(6);

        document.getElementById(
            "window"
        ).innerText =
            (d.entry_window || 12) + "s";

        document.getElementById(
            "candles"
        ).innerText =
            d.candles || 0;

        document.getElementById(
            "fractal"
        ).innerText =
            d.fractal || 2;

        document.getElementById(
            "expiry"
        ).innerText =
            d.expiry || "5m";

        document.getElementById(
            "ema9"
        ).innerText =
            Number(d.ema9 || 0)
            .toFixed(6);

        document.getElementById(
            "ema20"
        ).innerText =
            Number(d.ema20 || 0)
            .toFixed(6);

        document.getElementById(
            "ema50"
        ).innerText =
            Number(d.ema50 || 0)
            .toFixed(6);

        document.getElementById(
            "rsi"
        ).innerText =
            Number(d.rsi || 0)
            .toFixed(2);

        document.getElementById(
            "cci"
        ).innerText =
            Number(d.cci || 0)
            .toFixed(2);

        document.getElementById(
            "atr"
        ).innerText =
            Number(d.atr || 0)
            .toFixed(6);

        document.getElementById(
            "analysis"
        ).innerText =
            d.analysis ||
            "Waiting for screen feed...";

        if (d.image_received) {

            const img =
                document.getElementById(
                    "screenImage"
                );

            img.style.display =
                "block";

            img.src =
                "/api/frame.jpg?t=" +
                Date.now();
        }

    } catch (error) {

        const status =
            document.getElementById(
                "status"
            );

        status.innerText =
            "Feed: DISCONNECTED";

        status.className =
            "status dead";
    }
}

updateDashboard();

setInterval(
    updateDashboard,
    2000
);

</script>

</body>
</html>
"""

    return Response(
        html,
        mimetype="text/html"
    )


# ============================================================
# BACKGROUND FEED WATCHDOG
# ============================================================

def watchdog():

    while True:

        try:
            update_status()
        except Exception:
            pass

        time.sleep(2)


threading.Thread(
    target=watchdog,
    daemon=True
).start()


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    import os

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
