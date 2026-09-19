import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request

# OpenCV is optional so Render does not crash if it is temporarily unavailable.
try:
    import cv2
except Exception:
    cv2 = None

app = Flask(__name__)

# ============================================================
# ALUCARD SIGNAL BOT
# FEED-FIRST ANALYSIS ENGINE
# ============================================================

VERSION = "ALUCARD-4.0"

FEED_TOKEN = os.getenv("ALUCARD_FEED_TOKEN", "")
MIN_CONFIDENCE = 78
FRACTAL_PERIOD = 2
ENTRY_WINDOW = 12
EXPIRY = 300

state = {
    "analysis": "Waiting for screen feed...",
    "asset": "UNKNOWN",
    "atr": 0.0,
    "candles": 0,
    "cci": 0.0,
    "confidence": 0,
    "ema20": 0.0,
    "ema50": 0.0,
    "ema9": 0.0,
    "entry": 0.0,
    "entry_window": ENTRY_WINDOW,
    "expiry": EXPIRY,
    "feed": "DISCONNECTED",
    "fractal_period": FRACTAL_PERIOD,
    "image_received": False,
    "last_signal_time": None,
    "last_update": 0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "price": 0.0,
    "rsi": 0.0,
    "server_time": None,
    "signal": "WAIT",
}


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def authorized():
    """
    Accept the bridge token when one is configured.
    If no token is configured, allow the local bridge to work.
    """
    if not FEED_TOKEN:
        return True

    supplied = (
        request.headers.get("X-ALUCARD-TOKEN")
        or request.headers.get("X-RYU-TOKEN")
        or request.args.get("token")
    )

    return supplied == FEED_TOKEN


def mark_feed_live():
    state["feed"] = "LIVE"
    state["image_received"] = True
    state["last_update"] = time.time()
    state["server_time"] = now_iso()


def stale_check():
    while True:
        try:
            last = state.get("last_update", 0)

            if last:
                age = time.time() - last

                # Feed becomes disconnected after 15 seconds
                # without a new frame.
                if age > 15:
                    state["feed"] = "DISCONNECTED"
                    state["signal"] = "WAIT"
                    state["confidence"] = 0
                    state["analysis"] = "Waiting for screen feed..."

        except Exception:
            pass

        time.sleep(2)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def home():
    return render_template_string("""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALUCARD SIGNAL BOT</title>

<style>
*{box-sizing:border-box}

body{
    margin:0;
    background:#050505;
    color:#eee;
    font-family:Arial,sans-serif;
}

header{
    padding:20px;
    text-align:center;
    border-bottom:1px solid #333;
}

h1{
    margin:0;
    letter-spacing:5px;
}

.subtitle{
    color:#888;
    margin-top:7px;
}

.container{
    max-width:1100px;
    margin:auto;
    padding:15px;
}

.status{
    padding:14px;
    margin-bottom:15px;
    border:1px solid #333;
    background:#101010;
    font-weight:bold;
}

.grid{
    display:grid;
    grid-template-columns:repeat(2,1fr);
    gap:12px;
}

.card{
    background:#0d0d0d;
    border:1px solid #292929;
    padding:18px;
}

.label{
    color:#888;
    font-size:12px;
    text-transform:uppercase;
    letter-spacing:2px;
}

.value{
    margin-top:7px;
    font-size:25px;
    font-weight:bold;
}

.signal{
    font-size:42px;
    text-align:center;
    padding:25px;
}

.wait{color:#aaa}
.call{color:#38ff75}
.put{color:#ff3d5d}

@media(max-width:700px){
    .grid{grid-template-columns:1fr}
}
</style>
</head>

<body>

<header>
<h1>ALUCARD</h1>
<div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</header>

<div class="container">

<div class="status">
Feed:
<span id="feed">DISCONNECTED</span>
&nbsp;&nbsp;
Asset:
<span id="asset">UNKNOWN</span>
</div>

<div class="card signal">
<div class="label">Signal</div>
<div id="signal" class="value wait">WAIT</div>
</div>

<br>

<div class="grid">

<div class="card">
<div class="label">Price</div>
<div id="price" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">Confidence</div>
<div id="confidence" class="value">0%</div>
</div>

<div class="card">
<div class="label">Entry</div>
<div id="entry" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">Entry Window</div>
<div id="entry_window" class="value">12s</div>
</div>

<div class="card">
<div class="label">Candles</div>
<div id="candles" class="value">0</div>
</div>

<div class="card">
<div class="label">Fractal</div>
<div id="fractal" class="value">2</div>
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
<div class="label">MACD</div>
<div id="macd" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">MACD Signal</div>
<div id="macd_signal" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">CCI</div>
<div id="cci" class="value">0.00</div>
</div>

<div class="card">
<div class="label">ATR</div>
<div id="atr" class="value">0.000000</div>
</div>

<div class="card">
<div class="label">Expiry</div>
<div id="expiry" class="value">300s</div>
</div>

<div class="card">
<div class="label">Analysis</div>
<div id="analysis" class="value" style="font-size:17px">
Waiting for screen feed...
</div>
</div>

</div>
</div>

<script>
async function update(){

    try{

        const r = await fetch("/api/state", {
            cache:"no-store"
        });

        const s = await r.json();

        document.getElementById("feed").textContent =
            s.feed || "DISCONNECTED";

        document.getElementById("asset").textContent =
            s.asset || "UNKNOWN";

        const signal = document.getElementById("signal");

        signal.textContent = s.signal || "WAIT";

        signal.className =
            "value " +
            (
                s.signal === "CALL" ? "call" :
                s.signal === "PUT" ? "put" :
                "wait"
            );

        document.getElementById("price").textContent =
            Number(s.price || 0).toFixed(6);

        document.getElementById("confidence").textContent =
            Number(s.confidence || 0).toFixed(0) + "%";

        document.getElementById("entry").textContent =
            Number(s.entry || 0).toFixed(6);

        document.getElementById("entry_window").textContent =
            Number(s.entry_window || 12) + "s";

        document.getElementById("candles").textContent =
            Number(s.candles || 0);

        document.getElementById("fractal").textContent =
            Number(s.fractal_period || 2);

        document.getElementById("ema9").textContent =
            Number(s.ema9 || 0).toFixed(6);

        document.getElementById("ema20").textContent =
            Number(s.ema20 || 0).toFixed(6);

        document.getElementById("ema50").textContent =
            Number(s.ema50 || 0).toFixed(6);

        document.getElementById("rsi").textContent =
            Number(s.rsi || 0).toFixed(2);

        document.getElementById("macd").textContent =
            Number(s.macd || 0).toFixed(6);

        document.getElementById("macd_signal").textContent =
            Number(s.macd_signal || 0).toFixed(6);

        document.getElementById("cci").textContent =
            Number(s.cci || 0).toFixed(2);

        document.getElementById("atr").textContent =
            Number(s.atr || 0).toFixed(6);

        document.getElementById("expiry").textContent =
            Number(s.expiry || 300) + "s";

        document.getElementById("analysis").textContent =
            s.analysis || "Waiting for screen feed...";

    }catch(e){

        document.getElementById("feed").textContent =
            "DISCONNECTED";

    }
}

update();
setInterval(update,1000);
</script>

</body>
</html>
""")


# ============================================================
# STATE API
# ============================================================

@app.get("/api/state")
def api_state():
    return jsonify(state)


# ============================================================
# SCREEN FRAME API
#
# THIS IS THE IMPORTANT FIX.
#
# Your existing alucard_bridge.py posts to:
#
#     /api/frame
#
# The previous main.py did not have this route, causing 404.
# ============================================================

@app.post("/api/frame")
def api_frame():

    if not authorized():
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    raw = request.get_data()

    if not raw:
        return jsonify({
            "ok": False,
            "error": "No frame received"
        }), 400

    # --------------------------------------------------------
    # Confirm that this is actually an image when OpenCV is
    # available. We do NOT reject the frame if OpenCV is
    # unavailable because restoring the feed is the priority.
    # --------------------------------------------------------

    image_ok = True

    if cv2 is not None:
        try:
            import numpy as np

            arr = np.frombuffer(raw, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if image is None:
                image_ok = False

        except Exception:
            # Do not kill the feed because analysis failed.
            image_ok = True

    if not image_ok:
        return jsonify({
            "ok": False,
            "error": "Invalid image frame"
        }), 400

    # --------------------------------------------------------
    # FEED STATUS
    # --------------------------------------------------------

    mark_feed_live()

    state["analysis"] = "Screen feed received"

    # --------------------------------------------------------
    # Until a reliable chart-recognition/OCR layer extracts
    # candles and price from the actual Pocket Option image,
    # do NOT manufacture a trading signal.
    # --------------------------------------------------------

    state["signal"] = "WAIT"
    state["confidence"] = 0

    return jsonify({
        "ok": True,
        "message": "Frame accepted",
        "image_received": True,
        "feed": "LIVE",
        "state": state
    })


# ============================================================
# SIMPLE JSON FEED SUPPORT
#
# Keeps compatibility with earlier testing.
# ============================================================

@app.post("/api/feed")
def api_feed():

    if not authorized():
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    # Only copy known state fields.
    allowed = {
        "asset",
        "price",
        "signal",
        "confidence",
        "entry",
        "entry_window",
        "candles",
        "feed",
        "ema9",
        "ema20",
        "ema50",
        "rsi",
        "macd",
        "macd_signal",
        "cci",
        "atr",
    }

    for key in allowed:
        if key in data:
            state[key] = data[key]

    state["feed"] = "LIVE"
    state["image_received"] = False
    state["last_update"] = time.time()
    state["server_time"] = now_iso()

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": state
    })


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "feed": state["feed"],
        "image_received": state["image_received"],
        "opencv": cv2 is not None
    })


# ============================================================
# START FEED WATCHDOG
# ============================================================

threading.Thread(
    target=stale_check,
    daemon=True
).start()


# ============================================================
# LOCAL START
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
