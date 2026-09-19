import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string
from PIL import Image

app = Flask(__name__)

# ============================================================
# ALUCARD V2 — GOTHIC MARKET INTELLIGENCE
# Flask + Gunicorn + Pillow + Requests ONLY
# No cv2 / OpenCV required
# ============================================================

VERSION = "ALUCARD-2.1"

RYU_FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "")

state = {
    "feed": "DISCONNECTED",
    "asset": "UNKNOWN",
    "price": 0.0,

    "signal": "WAIT",
    "confidence": 0,

    "entry": 0.0,
    "entry_window": 12,

    "candles": 0,
    "fractal": 2,

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,

    "rsi": 0.0,
    "macd": 0.0,
    "cci": 0.0,
    "atr": 0.0,

    "payout": 0,
    "expiry": 300,

    "analysis": "Waiting for screen feed...",

    "image_received": False,
    "last_feed": 0,

    "feed_age": 0,
    "server_time": "",
}


# ============================================================
# FEED HEALTH
# ============================================================

def update_feed_health():
    while True:
        try:
            last = state.get("last_feed", 0)

            if last == 0:
                state["feed"] = "DISCONNECTED"
                state["feed_age"] = 0
            else:
                age = time.time() - last
                state["feed_age"] = round(age, 1)

                if age <= 10:
                    state["feed"] = "LIVE"
                elif age <= 30:
                    state["feed"] = "STALE"
                else:
                    state["feed"] = "DISCONNECTED"

            state["server_time"] = datetime.now(
                timezone.utc
            ).isoformat()

        except Exception:
            pass

        time.sleep(1)


threading.Thread(
    target=update_feed_health,
    daemon=True
).start()


# ============================================================
# SAFE NUMBER
# ============================================================

def num(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


def integer(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


# ============================================================
# TOKEN CHECK
# ============================================================

def valid_token(req):
    if not RYU_FEED_TOKEN:
        return True

    supplied = req.headers.get("X-RYU-TOKEN", "")

    return supplied == RYU_FEED_TOKEN


# ============================================================
# SIMPLE ANALYSIS ENGINE
# ============================================================

def calculate_analysis():

    price = num(state["price"])
    ema9 = num(state["ema9"])
    ema20 = num(state["ema20"])
    ema50 = num(state["ema50"])
    rsi = num(state["rsi"])
    macd = num(state["macd"])
    cci = num(state["cci"])

    if state["feed"] != "LIVE":
        return "Waiting for live screen feed..."

    if price <= 0:
        return "Waiting for valid price..."

    score_call = 0
    score_put = 0

    # EMA structure
    if ema9 > 0 and ema20 > 0:
        if ema9 > ema20:
            score_call += 1
        elif ema9 < ema20:
            score_put += 1

    if ema20 > 0 and ema50 > 0:
        if ema20 > ema50:
            score_call += 1
        elif ema20 < ema50:
            score_put += 1

    # RSI
    if rsi > 50:
        score_call += 1
    elif 0 < rsi < 50:
        score_put += 1

    # MACD
    if macd > 0:
        score_call += 1
    elif macd < 0:
        score_put += 1

    # CCI
    if cci > 0:
        score_call += 1
    elif cci < 0:
        score_put += 1

    total = score_call + score_put

    if total == 0:
        return "Live feed active — collecting indicators..."

    if score_call > score_put:
        strength = int(
            50 + ((score_call - score_put) * 10)
        )
        strength = min(strength, 95)

        if strength >= 78:
            state["signal"] = "CALL"
            state["confidence"] = strength
            return "Bullish alignment detected."

        return "Bullish bias — waiting for confirmation."

    if score_put > score_call:
        strength = int(
            50 + ((score_put - score_call) * 10)
        )
        strength = min(strength, 95)

        if strength >= 78:
            state["signal"] = "PUT"
            state["confidence"] = strength
            return "Bearish alignment detected."

        return "Bearish bias — waiting for confirmation."

    return "Indicators are mixed — WAIT."


# ============================================================
# JSON FEED
# ============================================================

@app.route("/api/feed", methods=["POST"])
def receive_feed():

    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    # --------------------------------------------------------
    # IMAGE / SCREENSHOT FEED
    # --------------------------------------------------------

    if request.files:

        uploaded = (
            request.files.get("image")
            or request.files.get("file")
            or request.files.get("screen")
        )

        if uploaded:

            try:
                image = Image.open(uploaded.stream)

                width, height = image.size

                state["image_received"] = True
                state["last_feed"] = time.time()
                state["feed"] = "LIVE"

                state["analysis"] = (
                    f"Screen feed active — "
                    f"{width}x{height} frame received."
                )

                return jsonify({
                    "ok": True,
                    "message": "Screen image accepted",
                    "width": width,
                    "height": height,
                    "state": state
                })

            except Exception as e:

                return jsonify({
                    "ok": False,
                    "error": f"Invalid image: {str(e)}"
                }), 400

    # --------------------------------------------------------
    # JSON FEED
    # --------------------------------------------------------

    data = request.get_json(silent=True)

    if data is None:

        return jsonify({
            "ok": False,
            "error": "No JSON data or image received"
        }), 400

    state["asset"] = str(
        data.get("asset", state["asset"])
    )

    state["price"] = num(
        data.get("price", state["price"])
    )

    state["candles"] = integer(
        data.get("candles", state["candles"])
    )

    state["fractal"] = integer(
        data.get("fractal", state["fractal"])
    )

    state["ema9"] = num(
        data.get("ema9", state["ema9"])
    )

    state["ema20"] = num(
        data.get("ema20", state["ema20"])
    )

    state["ema50"] = num(
        data.get("ema50", state["ema50"])
    )

    state["rsi"] = num(
        data.get("rsi", state["rsi"])
    )

    state["macd"] = num(
        data.get("macd", state["macd"])
    )

    state["cci"] = num(
        data.get("cci", state["cci"])
    )

    state["atr"] = num(
        data.get("atr", state["atr"])
    )

    state["payout"] = num(
        data.get("payout", state["payout"])
    )

    state["expiry"] = integer(
        data.get("expiry", state["expiry"])
    )

    state["entry_window"] = integer(
        data.get(
            "entry_window",
            state["entry_window"]
        )
    )

    state["entry"] = num(
        data.get("entry", state["price"])
    )

    # If the sender provides its own signal/confidence,
    # preserve it.
    incoming_signal = str(
        data.get("signal", "")
    ).upper()

    incoming_confidence = integer(
        data.get("confidence", -1)
    )

    if incoming_signal in ("CALL", "PUT", "WAIT"):
        state["signal"] = incoming_signal

    if incoming_confidence >= 0:
        state["confidence"] = max(
            0,
            min(incoming_confidence, 100)
        )

    state["last_feed"] = time.time()
    state["feed"] = "LIVE"
    state["image_received"] = False

    # Only calculate when the sender did not provide
    # a meaningful signal.
    if not incoming_signal:

        state["signal"] = "WAIT"

        state["analysis"] = calculate_analysis()

    else:

        if state["signal"] == "CALL":
            state["analysis"] = (
                "CALL signal received from live feed."
            )

        elif state["signal"] == "PUT":
            state["analysis"] = (
                "PUT signal received from live feed."
            )

        else:
            state["analysis"] = (
                "Live feed active — waiting for confirmation."
            )

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": state
    })


# ============================================================
# STATE API
# ============================================================

@app.route("/api/state", methods=["GET"])
def api_state():

    return jsonify(state)


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "app": "ALUCARD V2",
        "version": VERSION,
        "feed": state["feed"],
        "feed_age": state["feed_age"],
        "time": state["server_time"]
    })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>

<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>ALUCARD V2</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top,
        #202020 0%,
        #090909 55%,
        #000000 100%);

    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #444;
}

.title {
    font-size: 30px;
    font-weight: bold;
    letter-spacing: 4px;
}

.subtitle {
    color: #aaa;
    margin-top: 5px;
    letter-spacing: 2px;
}

.status {
    margin-top: 12px;
    font-weight: bold;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(150px, 1fr));

    gap: 10px;
    padding: 14px;
}

.card {
    background: rgba(20,20,20,.9);
    border: 1px solid #444;
    border-radius: 8px;
    padding: 15px;
    min-height: 85px;
}

.label {
    color: #999;
    font-size: 12px;
    text-transform: uppercase;
}

.value {
    font-size: 24px;
    margin-top: 8px;
    font-weight: bold;
}

.signal {
    font-size: 36px;
}

.analysis {
    margin: 14px;
    padding: 18px;
    border: 1px solid #444;
    border-radius: 8px;
    background: #111;
}

.tabs {
    display: flex;
    gap: 8px;
    padding: 14px;
    overflow-x: auto;
}

.tab {
    padding: 10px 18px;
    border: 1px solid #444;
    border-radius: 5px;
    white-space: nowrap;
}

</style>

</head>

<body>

<div class="header">

    <div class="title">
        ALUCARD
    </div>

    <div class="subtitle">
        GOTHIC MARKET INTELLIGENCE
    </div>

    <div class="status" id="status">
        Feed: DISCONNECTED
    </div>

</div>

<div class="tabs">
    <div class="tab">Signals</div>
    <div class="tab">Trades</div>
    <div class="tab">Performance</div>
    <div class="tab">Settings</div>
</div>

<div class="grid">

    <div class="card">
        <div class="label">Asset</div>
        <div class="value" id="asset">UNKNOWN</div>
    </div>

    <div class="card">
        <div class="label">Price</div>
        <div class="value" id="price">0.000000</div>
    </div>

    <div class="card">
        <div class="label">Signal</div>
        <div class="value signal" id="signal">
            WAIT
        </div>
    </div>

    <div class="card">
        <div class="label">Confidence</div>
        <div class="value" id="confidence">
            0%
        </div>
    </div>

    <div class="card">
        <div class="label">Entry</div>
        <div class="value" id="entry">
            0.000000
        </div>
    </div>

    <div class="card">
        <div class="label">Entry Window</div>
        <div class="value" id="entry_window">
            12s
        </div>
    </div>

    <div class="card">
        <div class="label">Candles</div>
        <div class="value" id="candles">
            0
        </div>
    </div>

    <div class="card">
        <div class="label">Fractal</div>
        <div class="value" id="fractal">
            2
        </div>
    </div>

</div>

<div class="analysis">

    <div class="label">
        LIVE ANALYSIS
    </div>

    <div class="value"
         id="analysis"
         style="font-size:18px;">
        Waiting for screen feed...
    </div>

</div>

<div class="grid">

    <div class="card">
        <div class="label">EMA 9</div>
        <div class="value" id="ema9">0.000000</div>
    </div>

    <div class="card">
        <div class="label">EMA 20</div>
        <div class="value" id="ema20">0.000000</div>
    </div>

    <div class="card">
        <div class="label">EMA 50</div>
        <div class="value" id="ema50">0.000000</div>
    </div>

    <div class="card">
        <div class="label">RSI</div>
        <div class="value" id="rsi">0.00</div>
    </div>

    <div class="card">
        <div class="label">MACD</div>
        <div class="value" id="macd">0.00</div>
    </div>

    <div class="card">
        <div class="label">CCI</div>
        <div class="value" id="cci">0.00</div>
    </div>

    <div class="card">
        <div class="label">ATR</div>
        <div class="value" id="atr">0.00</div>
    </div>

</div>

<script>

async function update() {

    try {

        const response =
            await fetch("/api/state");

        const s =
            await response.json();

        document.getElementById("status")
            .innerText =
            "Feed: " +
            s.feed +
            "   Asset: " +
            s.asset;

        document.getElementById("asset")
            .innerText = s.asset;

        document.getElementById("price")
            .innerText =
            Number(s.price).toFixed(6);

        document.getElementById("signal")
            .innerText = s.signal;

        document.getElementById("confidence")
            .innerText =
            s.confidence + "%";

        document.getElementById("entry")
            .innerText =
            Number(s.entry).toFixed(6);

        document.getElementById("entry_window")
            .innerText =
            s.entry_window + "s";

        document.getElementById("candles")
            .innerText = s.candles;

        document.getElementById("fractal")
            .innerText = s.fractal;

        document.getElementById("analysis")
            .innerText = s.analysis;

        document.getElementById("ema9")
            .innerText =
            Number(s.ema9).toFixed(6);

        document.getElementById("ema20")
            .innerText =
            Number(s.ema20).toFixed(6);

        document.getElementById("ema50")
            .innerText =
            Number(s.ema50).toFixed(6);

        document.getElementById("rsi")
            .innerText =
            Number(s.rsi).toFixed(2);

        document.getElementById("macd")
            .innerText =
            Number(s.macd).toFixed(4);

        document.getElementById("cci")
            .innerText =
            Number(s.cci).toFixed(2);

        document.getElementById("atr")
            .innerText =
            Number(s.atr).toFixed(6);

    } catch (e) {

        document.getElementById("status")
            .innerText =
            "Feed: DISCONNECTED";

    }

}

setInterval(update, 1000);

update();

</script>

</body>
</html>
"""


@app.route("/", methods=["GET"])
def dashboard():

    return render_template_string(HTML)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
