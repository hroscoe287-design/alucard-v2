import os
import time
import threading
from datetime import datetime, timezone

import cv2
import numpy as np
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# ============================================================
# ALUCARD CONFIGURATION
# ============================================================

APP_NAME = "ALUCARD SIGNAL BOT"
FEED_URL = os.getenv("RTSP_FEED_URL", "").strip()

ANALYSIS_SECONDS = int(os.getenv("ANALYSIS_SECONDS", "3"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "70"))

# ============================================================
# SHARED STATE
# ============================================================

state = {
    "connected": False,
    "feed": "NOT CONFIGURED",
    "signal": "WAIT",
    "confidence": 0,
    "price": 0,
    "trend": "UNKNOWN",
    "rsi": 50,
    "ema_fast": 0,
    "ema_slow": 0,
    "candle_count": 0,
    "last_update": "Never",
    "message": "Waiting for screen feed...",
    "scan": 0,
}

lock = threading.Lock()


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    values = np.asarray(values, dtype=float)
    alpha = 2.0 / (period + 1.0)

    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result

    return float(result)


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    values = np.asarray(values, dtype=float)
    differences = np.diff(values)

    gains = np.where(differences > 0, differences, 0)
    losses = np.where(differences < 0, -differences, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


# ============================================================
# SCREEN ANALYSIS
#
# This extracts a price-like series from the chart area.
# Because Pocket Option does not provide a public OTC market
# API, this is deliberately treated as screen analysis.
# ============================================================

def extract_chart_signal(frame):
    if frame is None:
        return None

    h, w = frame.shape[:2]

    # Ignore most of the dashboard UI.
    # Focus on the central/right chart area.
    x1 = int(w * 0.20)
    x2 = int(w * 0.92)
    y1 = int(h * 0.15)
    y2 = int(h * 0.85)

    roi = frame[y1:y2, x1:x2]

    if roi.size == 0:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Light chart/grid/candle structures produce intensity changes.
    # Create a vertical activity profile.
    profile = np.mean(gray, axis=0)

    if len(profile) < 30:
        return None

    # Smooth profile.
    kernel_size = 9
    kernel = np.ones(kernel_size) / kernel_size
    smooth = np.convolve(profile, kernel, mode="same")

    # Convert chart activity into a normalized pseudo-price series.
    # This is not a broker price feed; it is a visual measurement.
    normalized = (smooth - np.min(smooth))

    max_value = np.max(normalized)

    if max_value <= 0:
        return None

    normalized = normalized / max_value

    # Reverse so upward chart movement behaves like rising price.
    pseudo_price = normalized * 100.0

    # Remove extreme edges.
    pseudo_price = pseudo_price[10:-10]

    if len(pseudo_price) < 30:
        return None

    # Sample into approximately 100 observations.
    target = 100
    indices = np.linspace(
        0,
        len(pseudo_price) - 1,
        min(target, len(pseudo_price)),
        dtype=int
    )

    prices = pseudo_price[indices]

    return prices.astype(float)


def generate_signal(prices):
    if prices is None or len(prices) < 30:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "trend": "UNKNOWN",
            "rsi": 50,
            "ema_fast": 0,
            "ema_slow": 0,
            "message": "Not enough chart data."
        }

    fast = ema(prices, 9)
    slow = ema(prices, 21)
    rsi = calculate_rsi(prices, 14)

    if fast is None or slow is None:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "trend": "UNKNOWN",
            "rsi": round(rsi, 1),
            "ema_fast": 0,
            "ema_slow": 0,
            "message": "Calculating indicators..."
        }

    recent_change = prices[-1] - prices[-10]
    ema_difference = fast - slow

    score = 0

    # Trend
    if ema_difference > 0:
        score += 25
        trend = "BULLISH"
    else:
        score -= 25
        trend = "BEARISH"

    # Recent momentum
    if recent_change > 1.0:
        score += 20
    elif recent_change < -1.0:
        score -= 20

    # RSI confirmation
    if 50 <= rsi <= 70:
        score += 15
    elif 30 <= rsi < 50:
        score -= 5
    elif rsi > 75:
        score -= 15
    elif rsi < 25:
        score += 15

    # Convert score to confidence.
    confidence = min(95, max(50, 50 + abs(score)))

    if score >= 45 and confidence >= MIN_CONFIDENCE:
        signal = "CALL"
        message = "Bullish screen structure detected."
    elif score <= -45 and confidence >= MIN_CONFIDENCE:
        signal = "PUT"
        message = "Bearish screen structure detected."
    else:
        signal = "WAIT"
        confidence = min(confidence, 69)
        message = "Conditions are not strong enough."

    return {
        "signal": signal,
        "confidence": int(confidence),
        "trend": trend,
        "rsi": round(rsi, 1),
        "ema_fast": round(fast, 4),
        "ema_slow": round(slow, 4),
        "message": message
    }


# ============================================================
# FEED WORKER
# ============================================================

def feed_worker():
    global state

    while True:
        if not FEED_URL:
            with lock:
                state["connected"] = False
                state["feed"] = "NOT CONFIGURED"
                state["signal"] = "WAIT"
                state["confidence"] = 0
                state["message"] = (
                    "Add RTSP_FEED_URL in Render environment variables."
                )

            time.sleep(3)
            continue

        capture = None

        try:
            capture = cv2.VideoCapture(FEED_URL)

            if not capture.isOpened():
                with lock:
                    state["connected"] = False
                    state["feed"] = "OFFLINE"
                    state["message"] = "Unable to open RTSP feed."

                time.sleep(5)
                continue

            with lock:
                state["connected"] = True
                state["feed"] = "LIVE"
                state["message"] = "Screen feed connected."

            while True:
                ok, frame = capture.read()

                if not ok or frame is None:
                    with lock:
                        state["connected"] = False
                        state["feed"] = "DISCONNECTED"
                        state["message"] = "Screen feed stopped."

                    break

                prices = extract_chart_signal(frame)
                result = generate_signal(prices)

                with lock:
                    state["connected"] = True
                    state["feed"] = "LIVE"
                    state["signal"] = result["signal"]
                    state["confidence"] = result["confidence"]
                    state["trend"] = result["trend"]
                    state["rsi"] = result["rsi"]
                    state["ema_fast"] = result["ema_fast"]
                    state["ema_slow"] = result["ema_slow"]
                    state["candle_count"] = len(prices) if prices is not None else 0
                    state["price"] = (
                        round(float(prices[-1]), 3)
                        if prices is not None and len(prices)
                        else 0
                    )
                    state["scan"] += 1
                    state["last_update"] = datetime.now(
                        timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                    state["message"] = result["message"]

                time.sleep(ANALYSIS_SECONDS)

        except Exception as exc:
            with lock:
                state["connected"] = False
                state["feed"] = "ERROR"
                state["message"] = str(exc)[:180]

            time.sleep(5)

        finally:
            if capture is not None:
                capture.release()


# ============================================================
# API
# ============================================================

@app.route("/api/status")
def api_status():
    with lock:
        return jsonify(dict(state))


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "feed_configured": bool(FEED_URL)
    })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALUCARD SIGNAL BOT</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top, #250000 0%, #090909 45%, #000 100%);
    color: #eee;
    font-family: Arial, Helvetica, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #4a0000;
    background: rgba(0,0,0,.75);
}

.logo {
    font-size: 25px;
    font-weight: 900;
    letter-spacing: 3px;
}

.subtitle {
    margin-top: 5px;
    font-size: 11px;
    letter-spacing: 2px;
    color: #aaa;
}

.container {
    max-width: 1100px;
    margin: auto;
    padding: 15px;
}

.status {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #111;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 15px;
}

.dot {
    width: 12px;
    height: 12px;
    display: inline-block;
    border-radius: 50%;
    margin-right: 7px;
    background: #555;
}

.live {
    background: #00d26a;
    box-shadow: 0 0 12px #00d26a;
}

.offline {
    background: #d00000;
}

.signal {
    text-align: center;
    border-radius: 18px;
    padding: 25px 10px;
    background: #0d0d0d;
    border: 1px solid #3c0000;
    margin-bottom: 15px;
}

.signal-name {
    font-size: 58px;
    font-weight: 900;
    letter-spacing: 4px;
}

.call {
    color: #35ff8a;
    text-shadow: 0 0 18px rgba(53,255,138,.35);
}

.put {
    color: #ff4545;
    text-shadow: 0 0 18px rgba(255,69,69,.35);
}

.wait {
    color: #ffd84a;
}

.confidence {
    font-size: 18px;
    margin-top: 5px;
}

.message {
    color: #aaa;
    margin-top: 12px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
}

.card {
    background: #111;
    border: 1px solid #292929;
    border-radius: 12px;
    padding: 16px;
}

.label {
    color: #888;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.value {
    font-size: 23px;
    font-weight: bold;
    margin-top: 7px;
}

.footer {
    text-align: center;
    color: #666;
    font-size: 11px;
    padding: 25px;
}

.warning {
    margin-top: 15px;
    padding: 12px;
    border-radius: 10px;
    background: #1b1200;
    border: 1px solid #554000;
    color: #e4c96b;
    font-size: 12px;
}

@media(max-width:650px) {
    .grid {
        grid-template-columns: 1fr;
    }

    .signal-name {
        font-size: 48px;
    }
}
</style>
</head>

<body>

<div class="header">
    <div class="logo">ALUCARD SIGNAL BOT</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="container">

    <div class="status">
        <div>
            <span id="dot" class="dot"></span>
            <span id="feed">CONNECTING...</span>
        </div>
        <div>
            SCAN #<span id="scan">0</span>
        </div>
    </div>

    <div class="signal">
        <div id="signal" class="signal-name wait">WAIT</div>
        <div class="confidence">
            Confidence: <span id="confidence">0</span>%
        </div>
        <div class="message" id="message">
            Waiting for screen feed...
        </div>
    </div>

    <div class="grid">

        <div class="card">
            <div class="label">Trend</div>
            <div class="value" id="trend">UNKNOWN</div>
        </div>

        <div class="card">
            <div class="label">RSI</div>
            <div class="value" id="rsi">50</div>
        </div>

        <div class="card">
            <div class="label">EMA 9</div>
            <div class="value" id="emaFast">0</div>
        </div>

        <div class="card">
            <div class="label">EMA 21</div>
            <div class="value" id="emaSlow">0</div>
        </div>

        <div class="card">
            <div class="label">Visual Price</div>
            <div class="value" id="price">0</div>
        </div>

        <div class="card">
            <div class="label">Chart Samples</div>
            <div class="value" id="candles">0</div>
        </div>

        <div class="card">
            <div class="label">Last Update</div>
            <div class="value" id="updated">Never</div>
        </div>

        <div class="card">
            <div class="label">Feed</div>
            <div class="value" id="feed2">OFFLINE</div>
        </div>

    </div>

    <div class="warning">
        Screen-analysis mode: signals are generated from the visible chart feed.
        They are informational and do not place trades automatically.
    </div>

</div>

<div class="footer">
    ALUCARD • SCREEN ANALYSIS ENGINE
</div>

<script>
async function update() {
    try {
        const response = await fetch("/api/status");
        const s = await response.json();

        document.getElementById("feed").textContent = s.feed;
        document.getElementById("feed2").textContent = s.feed;
        document.getElementById("scan").textContent = s.scan;

        const dot = document.getElementById("dot");

        dot.className = "dot " + (
            s.connected ? "live" : "offline"
        );

        const signal = document.getElementById("signal");

        signal.textContent = s.signal;
        signal.className = "signal-name " +
            (s.signal === "CALL" ? "call" :
             s.signal === "PUT" ? "put" : "wait");

        document.getElementById("confidence").textContent = s.confidence;
        document.getElementById("trend").textContent = s.trend;
        document.getElementById("rsi").textContent = s.rsi;
        document.getElementById("emaFast").textContent = s.ema_fast;
        document.getElementById("emaSlow").textContent = s.ema_slow;
        document.getElementById("price").textContent = s.price;
        document.getElementById("candles").textContent = s.candle_count;
        document.getElementById("updated").textContent = s.last_update;
        document.getElementById("message").textContent = s.message;

    } catch (e) {
        document.getElementById("feed").textContent = "SERVER ERROR";
        document.getElementById("dot").className = "dot offline";
    }
}

update();
setInterval(update, 2000);
</script>

</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(HTML)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    thread = threading.Thread(target=feed_worker, daemon=True)
    thread.start()

    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
