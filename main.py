import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request
from PIL import Image

app = Flask(__name__)

VERSION = "ALUCARD-V2.1"

ASSETS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "CHFJPY",
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "USDCHF_otc", "AUDUSD_otc",
    "USDCAD_otc", "NZDUSD_otc", "EURGBP_otc", "EURJPY_otc", "GBPJPY_otc",
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "BTCUSD_otc", "ETHUSD_otc",
    "LTCUSD_otc", "XRPUSD_otc", "GOLD", "SILVER", "OIL", "NATGAS",
    "AAPL", "TSLA", "AMZN", "MSFT", "GOOGL", "META", "NASDAQ", "SP500",
    "DOWJONES"
]

STATE = {
    "version": VERSION,
    "feed": "DISCONNECTED",
    "feed_health": "WAITING",
    "image_received": False,
    "last_feed": 0.0,
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
    "cci": 0.0,
    "atr": 0.0,
    "analysis": "Waiting for screen feed...",
    "payout": 0,
    "expiry": "5m",
    "timestamp": "",
    "error": ""
}

LOCK = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def update_state(data):
    with LOCK:
        for key in (
            "asset", "signal", "analysis", "expiry", "feed",
            "feed_health", "error"
        ):
            if key in data and data[key] is not None:
                STATE[key] = str(data[key])

        for key in (
            "price", "entry", "ema9", "ema20", "ema50",
            "rsi", "cci", "atr", "payout"
        ):
            if key in data:
                STATE[key] = safe_float(data[key], STATE[key])

        for key in ("confidence", "entry_window", "candles", "fractal"):
            if key in data:
                STATE[key] = safe_int(data[key], STATE[key])

        STATE["last_feed"] = time.time()
        STATE["timestamp"] = now_iso()
        STATE["feed"] = "LIVE"
        STATE["feed_health"] = "CONNECTED"
        STATE["error"] = ""


def feed_watchdog():
    while True:
        time.sleep(3)

        with LOCK:
            age = time.time() - STATE["last_feed"]

            if STATE["last_feed"] and age > 15:
                STATE["feed"] = "DISCONNECTED"
                STATE["feed_health"] = "STALE"
                STATE["signal"] = "WAIT"
                STATE["confidence"] = 0
                STATE["analysis"] = (
                    "Screen feed is stale. Waiting for new frame."
                )


threading.Thread(target=feed_watchdog, daemon=True).start()


@app.get("/")
def home():
    return render_template_string(HTML)


@app.get("/api/state")
def api_state():
    with LOCK:
        result = dict(STATE)

        if STATE["last_feed"]:
            result["feed_age"] = round(
                time.time() - STATE["last_feed"], 1
            )
        else:
            result["feed_age"] = None

    return jsonify(result)


@app.get("/api/assets")
def api_assets():
    return jsonify({"assets": ASSETS})


@app.post("/api/feed")
def api_feed():
    token = (
        os.environ.get("RYU_FEED_TOKEN")
        or os.environ.get("ALUCARD_FEED_TOKEN")
    )

    supplied = (
        request.headers.get("X-RYU-TOKEN")
        or request.headers.get("X-ALUCARD-TOKEN")
    )

    if token and supplied != token:
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    if request.is_json:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "ok": False,
                "error": "Invalid JSON"
            }), 400

        update_state(data)

        with LOCK:
            STATE["image_received"] = False
            result = dict(STATE)

        return jsonify({
            "ok": True,
            "message": "JSON feed accepted",
            "state": result
        })

    image_file = (
        request.files.get("image")
        or request.files.get("file")
        or request.files.get("frame")
    )

    if image_file:
        try:
            image = Image.open(image_file.stream)
            image.verify()
        except Exception:
            return jsonify({
                "ok": False,
                "error": "Invalid image"
            }), 400

        data = {}

        for key in (
            "asset",
            "price",
            "signal",
            "confidence",
            "entry",
            "entry_window",
            "candles"
        ):
            if key in request.form:
                data[key] = request.form.get(key)

        update_state(data)

        with LOCK:
            STATE["image_received"] = True
            STATE["analysis"] = (
                "Screen frame received. Analysis data "
                "awaiting/using supplied values."
            )
            result = dict(STATE)

        return jsonify({
            "ok": True,
            "message": "Screen frame accepted",
            "state": result
        })

    return jsonify({
        "ok": False,
        "error": "No JSON data or image received"
    }), 400


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "version": VERSION
    })


HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>ALUCARD V2</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #050805;
    color: #eee;
    font-family: Arial, sans-serif;
}

header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #243024;
}

h1 {
    margin: 0;
    font-size: 28px;
    letter-spacing: 4px;
}

.sub {
    color: #888;
    margin-top: 5px;
    font-size: 12px;
}

nav {
    display: flex;
    overflow: auto;
    border-bottom: 1px solid #222;
}

nav button {
    flex: 1;
    min-width: 100px;
    background: #0b100b;
    color: #aaa;
    border: 0;
    padding: 14px;
    font-weight: bold;
}

nav button.active {
    color: #fff;
    background: #151d15;
}

main {
    padding: 14px;
    max-width: 1100px;
    margin: auto;
}

.status {
    padding: 12px;
    border: 1px solid #303a30;
    border-radius: 10px;
    margin-bottom: 12px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
}

.card {
    background: #0b100b;
    border: 1px solid #273127;
    border-radius: 12px;
    padding: 14px;
}

.label {
    color: #777;
    font-size: 11px;
    text-transform: uppercase;
}

.value {
    font-size: 24px;
    margin-top: 6px;
}

select {
    width: 100%;
    padding: 12px;
    background: #101610;
    color: #fff;
    border: 1px solid #344034;
    border-radius: 8px;
}

.signal {
    font-size: 36px;
    font-weight: bold;
    text-align: center;
    padding: 20px;
}

.wait {
    color: #aaa;
}

.call {
    color: #69e69a;
}

.put {
    color: #ff7777;
}

.small {
    font-size: 12px;
    color: #888;
}

@media (min-width: 700px) {
    .grid {
        grid-template-columns: repeat(4, 1fr);
    }
}
</style>
</head>

<body>

<header>
    <h1>ALUCARD</h1>
    <div class="sub">
        GOTHIC MARKET INTELLIGENCE — V2.1
    </div>
</header>

<nav>
    <button class="active">Signals</button>
    <button>Trades</button>
    <button>Performance</button>
    <button>Settings</button>
</nav>

<main>

<div class="status">
    <b>Feed:</b>
    <span id="feed">DISCONNECTED</span>

    &nbsp; | &nbsp;

    <b>Asset:</b>
    <span id="asset">UNKNOWN</span>

    <div class="small" id="health">
        Waiting for screen feed...
    </div>
</div>

<div class="card" style="margin-bottom:10px">
    <div class="label">Currency / Asset</div>

    <select id="assetSelect"></select>
</div>

<div class="grid">

<div class="card">
    <div class="label">Signal</div>
    <div id="signal" class="signal wait">WAIT</div>
</div>

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
    <div id="window" class="value">12s</div>
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
    <div class="label">Expiry</div>
    <div id="expiry" class="value">5m</div>
</div>

<div class="card">
    <div class="label">EMA 9</div>
    <div id="ema9" class="value">0</div>
</div>

<div class="card">
    <div class="label">EMA 20</div>
    <div id="ema20" class="value">0</div>
</div>

<div class="card">
    <div class="label">EMA 50</div>
    <div id="ema50" class="value">0</div>
</div>

<div class="card">
    <div class="label">RSI</div>
    <div id="rsi" class="value">0</div>
</div>

<div class="card">
    <div class="label">CCI</div>
    <div id="cci" class="value">0</div>
</div>

<div class="card">
    <div class="label">ATR</div>
    <div id="atr" class="value">0</div>
</div>

<div class="card">
    <div class="label">Payout</div>
    <div id="payout" class="value">0%</div>
</div>

<div class="card">
    <div class="label">Analysis</div>

    <div id="analysis"
         class="small"
         style="font-size:15px;margin-top:8px">
        Waiting for screen feed...
    </div>
</div>

</div>
</main>

<script>

function put(id, value) {
    const el = document.getElementById(id);

    if (el) {
        el.textContent = value;
    }
}


async function loadAssets() {
    try {
        const response = await fetch("/api/assets");
        const data = await response.json();

        const select = document.getElementById("assetSelect");

        select.innerHTML = "";

        data.assets.forEach(function(asset) {
            const option = document.createElement("option");

            option.value = asset;
            option.textContent = asset;

            select.appendChild(option);
        });

    } catch (error) {
        console.log("Asset list error:", error);
    }
}


async function refresh() {

    try {

        const response = await fetch(
            "/api/state",
            {cache: "no-store"}
        );

        const data = await response.json();

        put(
            "feed",
            data.feed || "DISCONNECTED"
        );

        put(
            "asset",
            data.asset || "UNKNOWN"
        );

        put(
            "price",
            Number(data.price || 0).toFixed(6)
        );

        put(
            "confidence",
            Math.round(data.confidence || 0) + "%"
        );

        put(
            "entry",
            Number(data.entry || 0).toFixed(6)
        );

        put(
            "window",
            (data.entry_window || 12) + "s"
        );

        put(
            "candles",
            data.candles || 0
        );

        put(
            "fractal",
            data.fractal || 2
        );

        put(
            "expiry",
            data.expiry || "5m"
        );

        put(
            "ema9",
            Number(data.ema9 || 0).toFixed(6)
        );

        put(
            "ema20",
            Number(data.ema20 || 0).toFixed(6)
        );

        put(
            "ema50",
            Number(data.ema50 || 0).toFixed(6)
        );

        put(
            "rsi",
            Number(data.rsi || 0).toFixed(2)
        );

        put(
            "cci",
            Number(data.cci || 0).toFixed(2)
        );

        put(
            "atr",
            Number(data.atr || 0).toFixed(6)
        );

        put(
            "payout",
            Math.round(data.payout || 0) + "%"
        );

        put(
            "analysis",
            data.analysis ||
            "Waiting for screen feed..."
        );

        const signal =
            document.getElementById("signal");

        signal.textContent =
            data.signal || "WAIT";

        signal.className =
            "signal " +
            String(data.signal || "WAIT").toLowerCase();

        const age =
            data.feed_age === null
                ? "none"
                : data.feed_age + "s ago";

        put(
            "health",
            (data.feed_health || "WAITING") +
            " — last frame: " +
            age
        );

        const assetSelect =
            document.getElementById("assetSelect");

        assetSelect.value =
            data.asset || "UNKNOWN";

    } catch (error) {

        put(
            "health",
            "Dashboard connection error"
        );
    }
}


loadAssets();
refresh();

setInterval(refresh, 2000);

</script>

</body>
</html>
"""


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000"))
    )
