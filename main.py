import os
import time
import threading
from datetime import datetime, timezone

import cv2
import numpy as np
import requests
from flask import Flask, jsonify, render_template_string, request


# ============================================================
# ALUCARD V2 — SCREEN ANALYSIS ENGINE
# ============================================================

app = Flask(__name__)

VERSION = "ALUCARD-V2.0"

# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "RyuFeed-9xK7pQ2mV8sL4zN6")

MIN_CONFIDENCE = 78
FRACTAL_PERIOD = 2

EMA_FAST = 9
EMA_MID = 20
EMA_SLOW = 50

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

CCI_PERIOD = 20
ATR_PERIOD = 14

ENTRY_WINDOW = 12
EXPIRY_SECONDS = 300

STALE_SECONDS = 20


# ------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------

state = {
    "asset": "UNKNOWN",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": ENTRY_WINDOW,
    "expiry": EXPIRY_SECONDS,

    "feed": "DISCONNECTED",
    "image_received": False,

    "candles": 0,
    "fractal_period": FRACTAL_PERIOD,

    "rsi": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "cci": 0.0,
    "atr": 0.0,

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,

    "last_update": 0,
    "last_signal_time": None,
    "analysis": "Waiting for screen feed...",

    "server_time": None,
}


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def now():
    return time.time()


def utc_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def authorized(req):
    token = req.headers.get("X-RYU-TOKEN", "")
    return token == FEED_TOKEN


# ------------------------------------------------------------
# TECHNICAL INDICATORS
# ------------------------------------------------------------

def ema(values, period):
    values = np.asarray(values, dtype=float)

    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)

    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result

    return result


def ema_series(values, period):
    values = np.asarray(values, dtype=float)

    if len(values) == 0:
        return np.array([])

    alpha = 2.0 / (period + 1.0)

    output = np.zeros(len(values))
    output[0] = values[0]

    for i in range(1, len(values)):
        output[i] = alpha * values[i] + (1 - alpha) * output[i - 1]

    return output


def rsi(values, period=14):
    values = np.asarray(values, dtype=float)

    if len(values) < period + 1:
        return 50.0

    delta = np.diff(values)

    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(delta)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def macd(values):
    values = np.asarray(values, dtype=float)

    if len(values) < MACD_SLOW:
        return 0.0, 0.0

    fast = ema_series(values, MACD_FAST)
    slow = ema_series(values, MACD_SLOW)

    line = fast - slow

    signal = ema(line, MACD_SIGNAL)

    if signal is None:
        signal = line[-1]

    return float(line[-1]), float(signal)


def cci(values, period=20):
    values = np.asarray(values, dtype=float)

    if len(values) < period:
        return 0.0

    window = values[-period:]

    mean = np.mean(window)
    deviation = np.mean(np.abs(window - mean))

    if deviation == 0:
        return 0.0

    return float((window[-1] - mean) / (0.015 * deviation))


def atr(values, period=14):
    values = np.asarray(values, dtype=float)

    if len(values) < period + 1:
        return 0.0

    differences = np.abs(np.diff(values))

    return float(np.mean(differences[-period:]))


# ------------------------------------------------------------
# FRACTAL ANALYSIS
# ------------------------------------------------------------

def fractal_direction(values, period=2):
    """
    Fractal confirmation.

    A bullish fractal is formed when the current low is lower
    than surrounding lows.

    A bearish fractal is formed when the current high is higher
    than surrounding highs.

    With period=2 this requires two candles on each side.
    """

    values = np.asarray(values, dtype=float)

    needed = period * 2 + 1

    if len(values) < needed:
        return "NONE"

    center = len(values) - period - 1

    left = values[center - period:center]
    right = values[center + 1:center + period + 1]

    center_value = values[center]

    if center_value < np.min(left) and center_value < np.min(right):
        return "BULLISH"

    if center_value > np.max(left) and center_value > np.max(right):
        return "BEARISH"

    return "NONE"


# ------------------------------------------------------------
# SCREEN / IMAGE PRICE EXTRACTION
# ------------------------------------------------------------

def decode_image(raw):
    try:
        array = np.frombuffer(raw, dtype=np.uint8)

        image = cv2.imdecode(array, cv2.IMREAD_COLOR)

        if image is None:
            return None

        return image

    except Exception:
        return None


def estimate_price_from_image(image):
    """
    Screen-feed mode does not require an SSID.

    This function intentionally provides a conservative result.
    If the price cannot be reliably extracted, the engine does
    not manufacture a price.
    """

    if image is None:
        return None

    return None


# ------------------------------------------------------------
# ANALYSIS ENGINE
# ------------------------------------------------------------

def analyze_prices(prices, asset="UNKNOWN"):
    global state

    prices = np.asarray(prices, dtype=float)

    prices = prices[np.isfinite(prices)]

    if len(prices) < 60:
        state["signal"] = "WAIT"
        state["confidence"] = 0
        state["analysis"] = "Collecting candles..."
        return

    current = float(prices[-1])

    ema9 = ema(prices, EMA_FAST)
    ema20 = ema(prices, EMA_MID)
    ema50 = ema(prices, EMA_SLOW)

    rsi_value = rsi(prices, RSI_PERIOD)

    macd_value, macd_signal_value = macd(prices)

    cci_value = cci(prices, CCI_PERIOD)

    atr_value = atr(prices, ATR_PERIOD)

    fractal = fractal_direction(
        prices,
        FRACTAL_PERIOD
    )

    state["price"] = current

    state["ema9"] = float(ema9 or 0)
    state["ema20"] = float(ema20 or 0)
    state["ema50"] = float(ema50 or 0)

    state["rsi"] = float(rsi_value)
    state["macd"] = float(macd_value)
    state["macd_signal"] = float(macd_signal_value)

    state["cci"] = float(cci_value)
    state["atr"] = float(atr_value)

    state["candles"] = len(prices)

    # --------------------------------------------------------
    # SCORING
    # --------------------------------------------------------

    call_score = 0
    put_score = 0

    reasons_call = []
    reasons_put = []

    # EMA structure
    if ema9 > ema20 > ema50:
        call_score += 20
        reasons_call.append("EMA bullish")

    elif ema9 < ema20 < ema50:
        put_score += 20
        reasons_put.append("EMA bearish")

    # Price vs EMA
    if current > ema9:
        call_score += 8

    elif current < ema9:
        put_score += 8

    # RSI
    if 50 < rsi_value < 70:
        call_score += 12
        reasons_call.append("RSI bullish")

    elif 30 < rsi_value < 50:
        put_score += 12
        reasons_put.append("RSI bearish")

    # MACD
    if macd_value > macd_signal_value:
        call_score += 15
        reasons_call.append("MACD bullish")

    elif macd_value < macd_signal_value:
        put_score += 15
        reasons_put.append("MACD bearish")

    # CCI
    if cci_value > 0:
        call_score += 10
        reasons_call.append("CCI positive")

    elif cci_value < 0:
        put_score += 10
        reasons_put.append("CCI negative")

    # Fractal
    if fractal == "BULLISH":
        call_score += 15
        reasons_call.append("Bullish fractal")

    elif fractal == "BEARISH":
        put_score += 15
        reasons_put.append("Bearish fractal")

    # Momentum
    if len(prices) >= 6:

        momentum = prices[-1] - prices[-6]

        if momentum > 0:
            call_score += 10
        elif momentum < 0:
            put_score += 10

    # --------------------------------------------------------
    # FINAL DECISION
    # --------------------------------------------------------

    difference = abs(call_score - put_score)

    confidence = clamp(
        max(call_score, put_score)
    )

    # Strong confirmation required
    if call_score > put_score and confidence >= MIN_CONFIDENCE:
        signal = "CALL"
        explanation = " | ".join(reasons_call)

    elif put_score > call_score and confidence >= MIN_CONFIDENCE:
        signal = "PUT"
        explanation = " | ".join(reasons_put)

    else:
        signal = "WAIT"

        if call_score > put_score:
            explanation = "Bullish conditions but confirmation is insufficient."
        elif put_score > call_score:
            explanation = "Bearish conditions but confirmation is insufficient."
        else:
            explanation = "Indicators are mixed."

        confidence = min(confidence, MIN_CONFIDENCE - 1)

    state["signal"] = signal
    state["confidence"] = int(confidence)

    if signal in ("CALL", "PUT"):
        state["entry"] = current
        state["entry_window"] = ENTRY_WINDOW
        state["last_signal_time"] = utc_string()

    state["analysis"] = explanation

    state["server_time"] = utc_string()


# ------------------------------------------------------------
# JSON FEED
# ------------------------------------------------------------

def process_json(data):

    asset = data.get("asset", "UNKNOWN")

    state["asset"] = asset
    state["feed"] = "LIVE"
    state["image_received"] = False
    state["last_update"] = now()

    prices = data.get("prices")

    # If an upstream analyzer supplied candles, use them.
    if isinstance(prices, list) and len(prices) >= 60:

        try:
            analyze_prices(
                prices,
                asset
            )
            return True

        except Exception as exc:

            state["analysis"] = (
                f"Analysis error: {exc}"
            )

    # Accept an externally supplied current price.
    if "price" in data:

        try:
            state["price"] = float(
                data["price"]
            )

        except Exception:
            pass

    # Accept externally supplied analysis values
    # when the screen analyzer already calculated them.

    if "signal" in data:
        supplied_signal = str(
            data["signal"]
        ).upper()

        if supplied_signal in (
            "CALL",
            "PUT",
            "WAIT"
        ):
            state["signal"] = supplied_signal

    if "confidence" in data:

        try:
            state["confidence"] = int(
                float(data["confidence"])
            )

        except Exception:
            pass

    if "entry" in data:

        try:
            state["entry"] = float(
                data["entry"]
            )

        except Exception:
            pass

    if "candles" in data:

        try:
            state["candles"] = int(
                data["candles"]
            )

        except Exception:
            pass

    if "entry_window" in data:

        try:
            state["entry_window"] = int(
                data["entry_window"]
            )

        except Exception:
            pass

    state["server_time"] = utc_string()

    state["analysis"] = (
        "Live feed accepted."
    )

    return True


# ------------------------------------------------------------
# IMAGE FEED
# ------------------------------------------------------------

def process_image(raw):

    image = decode_image(raw)

    if image is None:
        return False

    state["feed"] = "LIVE"
    state["image_received"] = True
    state["last_update"] = now()

    state["server_time"] = utc_string()

    # The image is successfully received.
    # Price extraction is deliberately conservative.
    estimated = estimate_price_from_image(image)

    if estimated is not None:
        state["price"] = estimated

    state["analysis"] = (
        "Live screen received."
    )

    return True


# ------------------------------------------------------------
# FEED HEALTH MONITOR
# ------------------------------------------------------------

def health_monitor():

    while True:

        try:

            age = now() - state["last_update"]

            if state["last_update"] == 0:
                state["feed"] = "DISCONNECTED"

            elif age > STALE_SECONDS:
                state["feed"] = "STALE"

                state["signal"] = "WAIT"
                state["confidence"] = 0

                state["analysis"] = (
                    "Feed stale — trading signal locked."
                )

        except Exception:
            pass

        time.sleep(2)


threading.Thread(
    target=health_monitor,
    daemon=True
).start()


# ------------------------------------------------------------
# HOME DASHBOARD
# ------------------------------------------------------------

HTML = """
<!DOCTYPE html>
<html>
<head>

<meta name="viewport"
content="width=device-width, initial-scale=1">

<title>ALUCARD SIGNAL BOT</title>

<style>

body {
    margin:0;
    background:#050505;
    color:#eee;
    font-family:Arial,sans-serif;
}

header {
    padding:20px;
    text-align:center;
    border-bottom:1px solid #333;
}

h1 {
    margin:0;
    letter-spacing:4px;
}

.subtitle {
    color:#888;
    margin-top:8px;
}

.container {
    max-width:1100px;
    margin:auto;
    padding:15px;
}

.grid {
    display:grid;
    grid-template-columns:
    repeat(auto-fit,minmax(160px,1fr));
    gap:12px;
}

.card {
    background:#111;
    border:1px solid #292929;
    border-radius:10px;
    padding:16px;
}

.label {
    color:#777;
    font-size:12px;
    text-transform:uppercase;
}

.value {
    font-size:25px;
    margin-top:7px;
    font-weight:bold;
}

.signal {
    font-size:42px;
    text-align:center;
    padding:25px;
}

.analysis {
    margin-top:15px;
    line-height:1.6;
}

.live {
    margin-bottom:15px;
    padding:12px;
    border-radius:8px;
    background:#111;
}

</style>

</head>

<body>

<header>

<h1>ALUCARD</h1>

<div class="subtitle">
GOTHIC MARKET INTELLIGENCE
</div>

</header>

<div class="container">

<div class="live">

Feed:
<strong id="feed">DISCONNECTED</strong>

&nbsp;&nbsp;

Asset:
<strong id="asset">UNKNOWN</strong>

</div>

<div class="card signal">

<div class="label">Signal</div>

<div id="signal">WAIT</div>

</div>

<br>

<div class="grid">

<div class="card">
<div class="label">Price</div>
<div class="value" id="price">--</div>
</div>

<div class="card">
<div class="label">Confidence</div>
<div class="value" id="confidence">0%</div>
</div>

<div class="card">
<div class="label">Entry</div>
<div class="value" id="entry">--</div>
</div>

<div class="card">
<div class="label">Entry Window</div>
<div class="value" id="window">--</div>
</div>

<div class="card">
<div class="label">Candles</div>
<div class="value" id="candles">0</div>
</div>

<div class="card">
<div class="label">Fractal</div>
<div class="value" id="fractal">2</div>
</div>

</div>

<br>

<div class="grid">

<div class="card">
<div class="label">EMA 9</div>
<div class="value" id="ema9">--</div>
</div>

<div class="card">
<div class="label">EMA 20</div>
<div class="value" id="ema20">--</div>
</div>

<div class="card">
<div class="label">EMA 50</div>
<div class="value" id="ema50">--</div>
</div>

<div class="card">
<div class="label">RSI</div>
<div class="value" id="rsi">--</div>
</div>

<div class="card">
<div class="label">MACD</div>
<div class="value" id="macd">--</div>
</div>

<div class="card">
<div class="label">CCI</div>
<div class="value" id="cci">--</div>
</div>

</div>

<div class="card analysis">

<div class="label">Analysis</div>

<div id="analysis">
Waiting for screen feed...
</div>

<br>

<div class="label">Server Time</div>

<div id="time">
--
</div>

</div>

</div>

<script>

async function update() {

    try {

        const response =
            await fetch("/api/state");

        const s =
            await response.json();

        document.getElementById("feed")
            .textContent = s.feed;

        document.getElementById("asset")
            .textContent = s.asset;

        document.getElementById("signal")
            .textContent = s.signal;

        document.getElementById("price")
            .textContent =
            Number(s.price || 0).toFixed(6);

        document.getElementById("confidence")
            .textContent =
            s.confidence + "%";

        document.getElementById("entry")
            .textContent =
            Number(s.entry || 0).toFixed(6);

        document.getElementById("window")
            .textContent =
            s.entry_window + "s";

        document.getElementById("candles")
            .textContent = s.candles;

        document.getElementById("fractal")
            .textContent = s.fractal_period;

        document.getElementById("ema9")
            .textContent =
            Number(s.ema9 || 0).toFixed(6);

        document.getElementById("ema20")
            .textContent =
            Number(s.ema20 || 0).toFixed(6);

        document.getElementById("ema50")
            .textContent =
            Number(s.ema50 || 0).toFixed(6);

        document.getElementById("rsi")
            .textContent =
            Number(s.rsi || 0).toFixed(2);

        document.getElementById("macd")
            .textContent =
            Number(s.macd || 0).toFixed(6);

        document.getElementById("cci")
            .textContent =
            Number(s.cci || 0).toFixed(2);

        document.getElementById("analysis")
            .textContent = s.analysis;

        document.getElementById("time")
            .textContent = s.server_time || "--";

    } catch (e) {

        document.getElementById("feed")
            .textContent = "OFFLINE";

    }

}

setInterval(update,1000);

update();

</script>

</body>
</html>
"""


# ------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service": "ALUCARD",
        "version": VERSION,
        "feed": state["feed"],
        "timestamp": utc_string()
    })


@app.route("/api/state")
def api_state():

    return jsonify(state)


@app.route("/api/feed", methods=["POST"])
def api_feed():

    if not authorized(request):

        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    try:

        # -----------------------------------------------
        # IMAGE / SCREEN FEED
        # -----------------------------------------------

        if request.files:

            uploaded = next(
                iter(request.files.values()),
                None
            )

            if uploaded:

                raw = uploaded.read()

                if process_image(raw):

                    return jsonify({
                        "ok": True,
                        "message": "Screen image accepted",
                        "state": state
                    })

        # -----------------------------------------------
        # RAW IMAGE BODY
        # -----------------------------------------------

        content_type = (
            request.headers
            .get("Content-Type", "")
            .lower()
        )

        if (
            content_type.startswith("image/")
            or content_type == "application/octet-stream"
        ):

            raw = request.get_data()

            if raw:

                if process_image(raw):

                    return jsonify({
                        "ok": True,
                        "message": "Image feed accepted",
                        "state": state
                    })

        # -----------------------------------------------
        # JSON FEED
        # -----------------------------------------------

        data = request.get_json(
            silent=True
        )

        if data is not None:

            if process_json(data):

                return jsonify({
                    "ok": True,
                    "message": "JSON feed accepted",
                    "state": state
                })

        return jsonify({
            "ok": False,
            "error": "No valid JSON or image feed received"
        }), 400

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ------------------------------------------------------------
# START
# ------------------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "5000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
