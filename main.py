import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ------------------------------------------------------------
# ALUCARD SIGNAL BOT
# Screen-stream receiver / signal dashboard
# ------------------------------------------------------------

RTSP_FEED_URL = os.getenv("RTSP_FEED_URL", "").strip()
FEED_TOKEN = os.getenv("FEED_TOKEN", "").strip()

state = {
    "connected": False,
    "last_update": None,
    "frame_count": 0,
    "asset": "EUR/USD OTC",
    "signal": "WAIT",
    "confidence": 0,
    "entry_price": "--",
    "payout": "--",
    "timeframe": "5m",
    "message": "Waiting for screen feed...",
}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def feed_is_fresh():
    last = state.get("last_update")
    if not last:
        return False

    try:
        old = datetime.strptime(last, "%Y-%m-%d %H:%M:%S UTC")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (now - old).total_seconds() < 15
    except Exception:
        return False


@app.route("/")
def home():
    html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALUCARD SIGNAL BOT</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #07070b;
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #292934;
    background: #0c0c12;
}

.logo {
    font-size: 25px;
    font-weight: 900;
    letter-spacing: 3px;
}

.sub {
    margin-top: 5px;
    color: #999;
    font-size: 11px;
    letter-spacing: 2px;
}

.status {
    margin: 15px;
    padding: 12px;
    border: 1px solid #292934;
    border-radius: 10px;
    background: #101017;
    text-align: center;
}

.dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #777;
    margin-right: 7px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    padding: 15px;
}

.card {
    background: #111118;
    border: 1px solid #292934;
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
    margin-top: 8px;
    font-size: 22px;
    font-weight: bold;
}

.signal {
    grid-column: span 2;
    text-align: center;
    padding: 25px;
}

.signalValue {
    font-size: 42px;
    font-weight: 900;
    margin-top: 8px;
}

.wait {
    color: #aaa;
}

.call {
    color: #36e58a;
}

.put {
    color: #ff5577;
}

.info {
    padding: 15px;
}

.infoBox {
    background: #101017;
    border: 1px solid #292934;
    border-radius: 12px;
    padding: 15px;
}

.small {
    color: #888;
    font-size: 12px;
    line-height: 1.6;
}

@media(max-width:600px) {
    .grid {
        grid-template-columns: 1fr 1fr;
    }
}
</style>
</head>

<body>

<div class="header">
    <div class="logo">ALUCARD SIGNAL BOT</div>
    <div class="sub">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="status">
    <span class="dot" id="dot"></span>
    <span id="connection">CHECKING FEED...</span>
</div>

<div class="grid">

    <div class="card">
        <div class="label">Asset</div>
        <div class="value" id="asset">--</div>
    </div>

    <div class="card">
        <div class="label">Timeframe</div>
        <div class="value" id="timeframe">--</div>
    </div>

    <div class="card signal">
        <div class="label">Current Signal</div>
        <div class="signalValue wait" id="signal">WAIT</div>
        <div class="small" id="confidence">Confidence: 0%</div>
    </div>

    <div class="card">
        <div class="label">Entry Price</div>
        <div class="value" id="entry">--</div>
    </div>

    <div class="card">
        <div class="label">Payout</div>
        <div class="value" id="payout">--</div>
    </div>

</div>

<div class="info">
    <div class="infoBox">
        <div class="label">Feed Information</div>
        <div class="small">
            Last update: <span id="last">--</span><br>
            Frames received: <span id="frames">0</span><br>
            Feed URL configured: <span id="feed">NO</span>
        </div>
    </div>
</div>

<script>
async function updateDashboard() {
    try {
        const response = await fetch("/api/status", {
            cache: "no-store"
        });

        const data = await response.json();

        document.getElementById("asset").textContent =
            data.asset || "--";

        document.getElementById("timeframe").textContent =
            data.timeframe || "--";

        const signal = document.getElementById("signal");

        signal.textContent = data.signal || "WAIT";

        signal.className = "signalValue";

        if (data.signal === "CALL") {
            signal.classList.add("call");
        } else if (data.signal === "PUT") {
            signal.classList.add("put");
        } else {
            signal.classList.add("wait");
        }

        document.getElementById("confidence").textContent =
            "Confidence: " + (data.confidence || 0) + "%";

        document.getElementById("entry").textContent =
            data.entry_price || "--";

        document.getElementById("payout").textContent =
            data.payout || "--";

        document.getElementById("last").textContent =
            data.last_update || "--";

        document.getElementById("frames").textContent =
            data.frame_count || 0;

        document.getElementById("feed").textContent =
            data.feed_configured ? "YES" : "NO";

        const connection =
            document.getElementById("connection");

        const dot =
            document.getElementById("dot");

        if (data.connected) {
            connection.textContent = "LIVE SCREEN FEED";
            dot.style.background = "#36e58a";
        } else {
            connection.textContent = "WAITING FOR SCREEN FEED";
            dot.style.background = "#777";
        }

    } catch (error) {
        document.getElementById("connection").textContent =
            "DASHBOARD CONNECTION ERROR";

        document.getElementById("dot").style.background =
            "#ff5577";
    }
}

updateDashboard();
setInterval(updateDashboard, 2000);
</script>

</body>
</html>
"""

    return render_template_string(html)


@app.route("/api/status")
def api_status():
    connected = feed_is_fresh()
    state["connected"] = connected

    return jsonify({
        "connected": connected,
        "last_update": state["last_update"],
        "frame_count": state["frame_count"],
        "asset": state["asset"],
        "signal": state["signal"],
        "confidence": state["confidence"],
        "entry_price": state["entry_price"],
        "payout": state["payout"],
        "timeframe": state["timeframe"],
        "feed_configured": bool(RTSP_FEED_URL),
        "server_time": utc_now()
    })


@app.route("/api/feed", methods=["POST"])
def receive_feed():
    # Optional token protection
    if FEED_TOKEN:
        supplied = request.headers.get("X-Feed-Token", "")

        if supplied != FEED_TOKEN:
            return jsonify({
                "ok": False,
                "error": "Invalid feed token"
            }), 401

    data = request.get_json(silent=True) or {}

    state["frame_count"] += 1
    state["last_update"] = utc_now()

    if "asset" in data:
        state["asset"] = str(data["asset"])

    if "signal" in data:
        signal = str(data["signal"]).upper()

        if signal in ("CALL", "PUT", "WAIT"):
            state["signal"] = signal

    if "confidence" in data:
        try:
            value = float(data["confidence"])
            state["confidence"] = max(0, min(100, round(value)))
        except Exception:
            pass

    if "entry_price" in data:
        state["entry_price"] = str(data["entry_price"])

    if "payout" in data:
        state["payout"] = str(data["payout"])

    if "timeframe" in data:
        state["timeframe"] = str(data["timeframe"])

    return jsonify({
        "ok": True,
        "message": "Feed received",
        "frame_count": state["frame_count"],
        "timestamp": state["last_update"]
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "Alucard Signal Bot",
        "time": utc_now()
    })


@app.route("/api/test")
def api_test():
    state["frame_count"] += 1
    state["last_update"] = utc_now()

    return jsonify({
        "ok": True,
        "message": "Test feed received",
        "frame_count": state["frame_count"],
        "timestamp": state["last_update"]
    })


def background_monitor():
    while True:
        time.sleep(5)

        if state["last_update"]:
            state["connected"] = feed_is_fresh()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    monitor = threading.Thread(
        target=background_monitor,
        daemon=True
    )

    monitor.start()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
