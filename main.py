import os
import time
import threading
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

RTSP_FEED_URL = os.getenv("RTSP_FEED_URL", "").strip()
FEED_TOKEN = os.getenv("FEED_TOKEN", "").strip()

DEFAULT_ASSET = os.getenv("DEFAULT_ASSET", "EUR/USD OTC")
EXPIRY_SECONDS = int(os.getenv("EXPIRY_SECONDS", "300"))

state = {
    "connected": False,
    "last_update": 0,
    "asset": DEFAULT_ASSET,
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "feed": "WAITING FOR SCREEN FEED",
    "scan": 0,
}


# --------------------------------------------------
# BACKGROUND STATUS LOOP
# --------------------------------------------------

def monitor():
    while True:
        now = time.time()

        if state["last_update"] > 0:
            age = now - state["last_update"]

            if age <= 15:
                state["connected"] = True
                state["feed"] = "LIVE"
            else:
                state["connected"] = False
                state["feed"] = "STALE / DISCONNECTED"

        state["scan"] += 1
        time.sleep(5)


threading.Thread(target=monitor, daemon=True).start()


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

HTML = """
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
    background: #050509;
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #292929;
    background: #09090e;
}

.title {
    font-size: 27px;
    font-weight: bold;
    letter-spacing: 3px;
}

.subtitle {
    color: #888;
    margin-top: 5px;
    font-size: 12px;
    letter-spacing: 2px;
}

.container {
    max-width: 1100px;
    margin: auto;
    padding: 15px;
}

.status {
    display: grid;
    grid-template-columns: repeat(3,1fr);
    gap: 10px;
    margin-bottom: 15px;
}

.card {
    background: #101015;
    border: 1px solid #292933;
    border-radius: 12px;
    padding: 15px;
}

.label {
    color: #777;
    font-size: 11px;
    text-transform: uppercase;
}

.value {
    font-size: 20px;
    margin-top: 6px;
    font-weight: bold;
}

.live {
    color: #55ff99;
}

.wait {
    color: #ffcc55;
}

.signal {
    text-align: center;
    padding: 30px 15px;
    margin-bottom: 15px;
}

.signal-name {
    font-size: 48px;
    font-weight: bold;
    letter-spacing: 5px;
}

.confidence {
    font-size: 22px;
    margin-top: 10px;
}

.chart {
    height: 330px;
    background:
        linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
    background-size: 35px 35px;
    border: 1px solid #292933;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #555;
    text-align: center;
}

.notice {
    margin-top: 15px;
    padding: 15px;
    border-radius: 10px;
    background: #0d0d12;
    border: 1px solid #24242d;
    color: #999;
    font-size: 13px;
    line-height: 1.5;
}

@media(max-width:700px) {
    .status {
        grid-template-columns: 1fr;
    }

    .signal-name {
        font-size: 38px;
    }

    .chart {
        height: 260px;
    }
}
</style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD SIGNAL BOT</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="container">

    <div class="status">

        <div class="card">
            <div class="label">Screen Feed</div>
            <div id="feed" class="value wait">WAITING</div>
        </div>

        <div class="card">
            <div class="label">Asset</div>
            <div id="asset" class="value">---</div>
        </div>

        <div class="card">
            <div class="label">Scan</div>
            <div id="scan" class="value">0</div>
        </div>

    </div>

    <div class="card signal">
        <div class="label">Current Signal</div>

        <div id="signal" class="signal-name">
            WAIT
        </div>

        <div id="confidence" class="confidence">
            Confidence: 0%
        </div>
    </div>

    <div class="chart">
        <div>
            <div style="font-size:20px;">POCKET OPTION SCREEN FEED</div>
            <div style="margin-top:8px;">
                RTSP video analysis connection
            </div>
        </div>
    </div>

    <div class="notice">
        Alucard is waiting for the Android Pocket Option screen stream.
        Keep Pocket Option on the screen while the screen-stream service
        is running. This dashboard does not place trades.
    </div>

</div>

<script>

async function updateStatus() {

    try {

        const response = await fetch("/api/status");
        const data = await response.json();

        document.getElementById("feed").textContent = data.feed;
        document.getElementById("asset").textContent = data.asset;
        document.getElementById("scan").textContent = data.scan;

        document.getElementById("signal").textContent = data.signal;

        document.getElementById("confidence").textContent =
            "Confidence: " + data.confidence + "%";

        const feed = document.getElementById("feed");

        if (data.connected) {
            feed.className = "value live";
        } else {
            feed.className = "value wait";
        }

    } catch (error) {

        document.getElementById("feed").textContent =
            "SERVER ERROR";

    }
}

updateStatus();
setInterval(updateStatus, 3000);

</script>

</body>
</html>
"""


# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/status")
def status():

    return jsonify({
        "connected": state["connected"],
        "feed": state["feed"],
        "asset": state["asset"],
        "price": state["price"],
        "signal": state["signal"],
        "confidence": state["confidence"],
        "scan": state["scan"],
        "rtsp_configured": bool(RTSP_FEED_URL),
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "Alucard Signal Bot"
    })


@app.route("/api/feed", methods=["POST"])
def feed():

    from flask import request

    if FEED_TOKEN:
        supplied = request.headers.get("X-Feed-Token", "")

        if supplied != FEED_TOKEN:
            return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    state["last_update"] = time.time()

    if "asset" in data:
        state["asset"] = str(data["asset"])

    if "price" in data:
        try:
            state["price"] = float(data["price"])
        except:
            pass

    if "signal" in data:
        signal = str(data["signal"]).upper()

        if signal in ["CALL", "PUT", "WAIT"]:
            state["signal"] = signal

    if "confidence" in data:
        try:
            state["confidence"] = max(
                0,
                min(100, int(float(data["confidence"])))
            )
        except:
            pass

    return jsonify({
        "ok": True,
        "feed": "LIVE"
    })


# --------------------------------------------------
# START
# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
)
