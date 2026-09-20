import os
import io
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from PIL import Image

app = Flask(__name__)

TOKEN = os.getenv("ALUCARD_FEED_TOKEN", "")

state = {
    "asset": "UNKNOWN",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": 12,
    "candles": 0,
    "feed": "WAITING",
    "image_received": False,
    "last_frame": None,
    "analysis": "Waiting for Pocket Option screen feed...",
    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "rsi": 0.0,
    "macd": 0.0,
    "cci": 0.0,
    "atr": 0.0,
    "fractal": 2,
    "updated": None,
}

lock = threading.Lock()


def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def authorized():
    if not TOKEN:
        return True

    supplied = (
        request.headers.get("X-ALUCARD-TOKEN")
        or request.args.get("token")
    )

    return supplied == TOKEN


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def update_json(data):

    with lock:

        if "asset" in data:
            state["asset"] = str(data["asset"])

        if "price" in data:
            state["price"] = safe_float(data["price"])

        if "signal" in data:
            signal = str(data["signal"]).upper()

            if signal in ("CALL", "PUT", "WAIT"):
                state["signal"] = signal

        if "confidence" in data:
            state["confidence"] = max(
                0,
                min(100, safe_int(data["confidence"]))
            )

        if "entry" in data:
            state["entry"] = safe_float(data["entry"])

        if "entry_window" in data:
            state["entry_window"] = max(
                0,
                safe_int(data["entry_window"], 12)
            )

        if "candles" in data:
            state["candles"] = max(
                0,
                safe_int(data["candles"])
            )

        for key in (
            "ema9",
            "ema20",
            "ema50",
            "rsi",
            "macd",
            "cci",
            "atr",
        ):
            if key in data:
                state[key] = safe_float(data[key])

        if "fractal" in data:
            state["fractal"] = safe_int(
                data["fractal"],
                2
            )

        if "analysis" in data:
            state["analysis"] = str(
                data["analysis"]
            )

        state["feed"] = "LIVE"
        state["updated"] = now_utc()


def process_image(raw):

    try:

        image = Image.open(
            io.BytesIO(raw)
        )

        image.verify()

        timestamp = now_utc()

        with lock:

            state["image_received"] = True
            state["last_frame"] = timestamp
            state["feed"] = "LIVE"
            state["updated"] = timestamp
            state["analysis"] = (
                "Pocket Option screen received."
            )

        return jsonify({
            "ok": True,
            "message": "Screen frame accepted",
            "feed": "LIVE",
            "image_received": True,
            "timestamp": timestamp
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": "Invalid image: " + str(exc)
        }), 400


def current_state():

    with lock:
        result = dict(state)

    age = 999999

    if result["updated"]:

        try:

            last = datetime.strptime(
                result["updated"],
                "%Y-%m-%d %H:%M:%S UTC"
            ).replace(tzinfo=timezone.utc)

            age = int(
                (
                    datetime.now(timezone.utc)
                    - last
                ).total_seconds()
            )

        except Exception:
            age = 999999

    result["age_seconds"] = age

    if age > 20:

        result["feed"] = "DISCONNECTED"

        result["analysis"] = (
            "Pocket Option screen feed stopped."
        )

    return result


@app.get("/")
def dashboard():
    return render_template_string(HTML)


@app.get("/api/state")
def api_state():
    return jsonify(current_state())


@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1",
        "time": now_utc()
    })


@app.get("/api/health")
def api_health():

    data = current_state()

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1",
        "feed": data["feed"],
        "last_update": data["updated"],
        "age_seconds": data["age_seconds"]
    })


@app.post("/api/feed")
def api_feed():

    if not authorized():

        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    # JSON
    if request.is_json:

        data = request.get_json(
            silent=True
        )

        if not isinstance(data, dict):

            return jsonify({
                "ok": False,
                "error": "Invalid JSON"
            }), 400

        update_json(data)

        return jsonify({
            "ok": True,
            "message": "ALUCARD JSON feed accepted",
            "state": current_state()
        })

    # Multipart image
    uploaded = (
        request.files.get("image")
        or request.files.get("frame")
        or request.files.get("file")
    )

    if uploaded:

        raw = uploaded.read()

        if not raw:

            return jsonify({
                "ok": False,
                "error": "Empty image"
            }), 400

        return process_image(raw)

    # Raw image
    raw = request.get_data()

    if raw:
        return process_image(raw)

    return jsonify({
        "ok": False,
        "error": "No JSON or image received"
    }), 400


@app.post("/api/frame")
def api_frame():

    if not authorized():

        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    # Multipart image
    uploaded = (
        request.files.get("image")
        or request.files.get("frame")
        or request.files.get("file")
    )

    if uploaded:

        raw = uploaded.read()

        if not raw:

            return jsonify({
                "ok": False,
                "error": "Empty image"
            }), 400

        return process_image(raw)

    # JSON
    if request.is_json:

        data = request.get_json(
            silent=True
        )

        if isinstance(data, dict):

            update_json(data)

            return jsonify({
                "ok": True,
                "message": "ALUCARD JSON frame accepted",
                "state": current_state()
            })

    # Raw image
    raw = request.get_data()

    if raw:
        return process_image(raw)

    return jsonify({
        "ok": False,
        "error": "No image or JSON data received"
    }), 400


HTML = """
<!DOCTYPE html>

<html>

<head>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #070709;
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    background: #0d0d10;
    border-bottom: 1px solid #292929;
}

.title {
    font-size: 28px;
    font-weight: bold;
    letter-spacing: 4px;
}

.subtitle {
    margin-top: 5px;
    color: #777;
    font-size: 11px;
    letter-spacing: 2px;
}

.feed {
    margin-top: 12px;
    font-weight: bold;
}

.live {
    color: #00ff88;
}

.dead {
    color: #ff4444;
}

.wait {
    color: #ffaa00;
}

.tabs {
    display: flex;
    gap: 5px;
    padding: 10px;
    background: #101014;
    overflow-x: auto;
}

.tab {
    padding: 10px 15px;
    border: 1px solid #292929;
    border-radius: 6px;
    color: #aaa;
    white-space: nowrap;
}

.tab:first-child {
    color: white;
    border-color: #555;
}

.container {
    max-width: 1000px;
    margin: auto;
    padding: 14px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit,minmax(150px,1fr));
    gap: 10px;
}

.card {
    background: #101014;
    border: 1px solid #28282d;
    border-radius: 8px;
    padding: 16px;
    min-height: 105px;
}

.label {
    color: #777;
    font-size: 11px;
    letter-spacing: 1px;
}

.value {
    margin-top: 9px;
    font-size: 25px;
    font-weight: bold;
}

.call {
    color: #00ff88;
}

.put {
    color: #ff4055;
}

.waiting {
    color: #ffaa00;
}

.panel {
    margin-top: 12px;
    padding: 16px;
    background: #101014;
    border: 1px solid #28282d;
    border-radius: 8px;
}

.small {
    color: #888;
    font-size: 12px;
    line-height: 1.8;
}

#analysis {
    margin-top: 8px;
    color: #ddd;
}

</style>

</head>

<body>

<div class="header">

<div class="title">
ALUCARD
</div>

<div class="subtitle">
GOTHIC MARKET INTELLIGENCE — V2.1
</div>

<div id="feed" class="feed wait">
FEED: CONNECTING...
</div>

</div>

<div class="tabs">

<div class="tab">Signals</div>
<div class="tab">Trades</div>
<div class="tab">Performance</div>
<div class="tab">Settings</div>

</div>

<div class="container">

<div class="grid">

<div class="card">
<div class="label">ASSET</div>
<div id="asset" class="value">UNKNOWN</div>
</div>

<div class="card">
<div class="label">SIGNAL</div>
<div id="signal" class="value waiting">WAIT</div>
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
<div class="label">SCREEN</div>
<div id="screen" class="value waiting">
WAITING
</div>
</div>

</div>

<div class="panel">

<div class="label">
MARKET ANALYSIS
</div>

<div id="analysis">
Waiting for Pocket Option screen feed...
</div>

</div>

<div class="panel">

<div class="label">
INDICATORS
</div>

<div class="small">

EMA 9:
<span id="ema9">0</span>
&nbsp; | &nbsp;

EMA 20:
<span id="ema20">0</span>
&nbsp; | &nbsp;

EMA 50:
<span id="ema50">0</span>
&nbsp; | &nbsp;

RSI:
<span id="rsi">0</span>
&nbsp; | &nbsp;

MACD:
<span id="macd">0</span>
&nbsp; | &nbsp;

CCI:
<span id="cci">0</span>
&nbsp; | &nbsp;

ATR:
<span id="atr">0</span>

</div>

</div>

<div class="panel">

<div class="label">
LAST FRAME
</div>

<div id="lastframe" class="small">
No frame received.
</div>

</div>

</div>

<script>

function fmt(value, digits=6) {

    let n = Number(value || 0);

    return n.toFixed(digits);

}


function update(data) {

    document.getElementById("asset").textContent =
        data.asset || "UNKNOWN";

    document.getElementById("price").textContent =
        fmt(data.price);

    document.getElementById("entry").textContent =
        fmt(data.entry);

    document.getElementById("confidence").textContent =
        (data.confidence || 0) + "%";

    document.getElementById("window").textContent =
        (data.entry_window || 0) + "s";

    document.getElementById("candles").textContent =
        data.candles || 0;

    document.getElementById("analysis").textContent =
        data.analysis || "Waiting...";


    let signal =
        String(data.signal || "WAIT").toUpperCase();

    let signalEl =
        document.getElementById("signal");

    signalEl.textContent = signal;

    signalEl.className = "value";

    if (signal === "CALL") {
        signalEl.classList.add("call");
    }
    else if (signal === "PUT") {
        signalEl.classList.add("put");
    }
    else {
        signalEl.classList.add("waiting");
    }


    document.getElementById("ema9").textContent =
        fmt(data.ema9,5);

    document.getElementById("ema20").textContent =
        fmt(data.ema20,5);

    document.getElementById("ema50").textContent =
        fmt(data.ema50,5);

    document.getElementById("rsi").textContent =
        fmt(data.rsi,2);

    document.getElementById("macd").textContent =
        fmt(data.macd,5);

    document.getElementById("cci").textContent =
        fmt(data.cci,2);

    document.getElementById("atr").textContent =
        fmt(data.atr,5);


    let feed =
        document.getElementById("feed");

    let screen =
        document.getElementById("screen");

    let age =
        Number(data.age_seconds || 999999);


    if (data.feed === "LIVE" && age <= 20) {

        feed.className = "feed live";
        feed.textContent = "FEED: LIVE";

        screen.textContent =
            data.image_received
            ? "LIVE"
            : "DATA LIVE";

        screen.className = "value call";

    }
    else if (data.feed === "DISCONNECTED") {

        feed.className = "feed dead";
        feed.textContent = "FEED: DISCONNECTED";

        screen.textContent = "OFFLINE";
        screen.className = "value put";

    }
    else {

        feed.className = "feed wait";
        feed.textContent = "FEED: WAITING";

        screen.textContent = "WAITING";
        screen.className = "value waiting";

    }


    document.getElementById("lastframe").textContent =
        data.last_frame || "No frame received.";

}


async function refresh() {

    try {

        const response =
            await fetch(
                "/api/state?ts=" +
                Date.now(),
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                "HTTP " + response.status
            );
        }

        const data =
            await response.json();

        update(data);

    }
    catch (error) {

        const feed =
            document.getElementById("feed");

        feed.className = "feed dead";
        feed.textContent = "FEED: SERVER ERROR";

    }

}


refresh();

setInterval(
    refresh,
    2000
);

</script>

</body>

</html>
"""


if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "5000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
