import os
import io
import time
import math
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from PIL import Image

app = Flask(__name__)

# ============================================================
# ALUCARD V2.1
# Screen-feed compatible
# No OpenCV required
# ============================================================

RYU_FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

STATE_LOCK = threading.Lock()

STATE = {
    "feed": "DISCONNECTED",
    "asset": "UNKNOWN",
    "signal": "WAIT",
    "price": 0.0,
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
    "macd": 0.0,
    "macd_signal": 0.0,
    "sar": 0.0,

    "analysis": "Waiting for screen feed...",
    "last_frame": None,
    "image_received": False,
    "frame_bytes": 0,
    "updated": 0.0
}

LAST_IMAGE = None


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def valid_token(req):
    if not RYU_FEED_TOKEN:
        return True

    supplied = (
        req.headers.get("X-RYU-TOKEN")
        or req.headers.get("X-ALUCARD-TOKEN")
        or request.args.get("token")
        or ""
    )

    return supplied == RYU_FEED_TOKEN


def clean_float(value, default=0.0):
    try:
        if value is None:
            return default

        x = float(value)

        if not math.isfinite(x):
            return default

        return x
    except Exception:
        return default


def clean_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def calculate_ema(values, period):
    if not values:
        return 0.0

    if len(values) < period:
        period = len(values)

    if period <= 0:
        return 0.0

    multiplier = 2.0 / (period + 1.0)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calculate_rsi(values, period=14):
    if len(values) < 2:
        return 0.0

    if len(values) < period + 1:
        period = len(values) - 1

    if period <= 0:
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

    gains = gains[-period:]
    losses = losses[-period:]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def calculate_cci(candles, period=20):
    if len(candles) < 3:
        return 0.0

    period = min(period, len(candles))

    typical = []

    for c in candles[-period:]:
        h = clean_float(c.get("high"))
        l = clean_float(c.get("low"))
        close = clean_float(c.get("close"))

        typical.append((h + l + close) / 3.0)

    if not typical:
        return 0.0

    mean = sum(typical) / len(typical)

    deviation = sum(abs(x - mean) for x in typical) / len(typical)

    if deviation == 0:
        return 0.0

    return (typical[-1] - mean) / (0.015 * deviation)


def calculate_atr(candles, period=14):
    if len(candles) < 2:
        return 0.0

    trs = []

    previous_close = clean_float(candles[0].get("close"))

    for c in candles[1:]:
        high = clean_float(c.get("high"))
        low = clean_float(c.get("low"))
        close = clean_float(c.get("close"))

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)
        previous_close = close

    if not trs:
        return 0.0

    return sum(trs[-period:]) / min(period, len(trs))


def calculate_macd(values):
    if len(values) < 5:
        return 0.0, 0.0

    ema12 = calculate_ema(values, min(12, len(values)))
    ema26 = calculate_ema(values, min(26, len(values)))

    macd = ema12 - ema26

    # A compact signal approximation.
    signal = macd

    return macd, signal


def analyze_candles(candles):
    if not candles:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "analysis": "Screen feed received, but no structured candle data is available."
        }

    closes = [
        clean_float(c.get("close"))
        for c in candles
        if clean_float(c.get("close")) > 0
    ]

    if len(closes) < 3:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "analysis": "Not enough candle data for analysis."
        }

    ema9 = calculate_ema(closes, min(9, len(closes)))
    ema20 = calculate_ema(closes, min(20, len(closes)))
    ema50 = calculate_ema(closes, min(50, len(closes)))

    rsi = calculate_rsi(closes)
    cci = calculate_cci(candles)
    atr = calculate_atr(candles)
    macd, macd_signal = calculate_macd(closes)

    price = closes[-1]

    bullish = 0
    bearish = 0

    # EMA structure
    if ema9 > ema20:
        bullish += 1
    elif ema9 < ema20:
        bearish += 1

    if ema20 > ema50:
        bullish += 1
    elif ema20 < ema50:
        bearish += 1

    # RSI
    if 50 < rsi < 75:
        bullish += 1
    elif 25 < rsi < 50:
        bearish += 1

    # CCI
    if cci > 0:
        bullish += 1
    elif cci < 0:
        bearish += 1

    # MACD
    if macd > macd_signal:
        bullish += 1
    elif macd < macd_signal:
        bearish += 1

    total = bullish + bearish

    if total == 0:
        signal = "WAIT"
        confidence = 0
    elif bullish > bearish:
        signal = "CALL"
        confidence = int(55 + (bullish / 5.0) * 30)
    elif bearish > bullish:
        signal = "PUT"
        confidence = int(55 + (bearish / 5.0) * 30)
    else:
        signal = "WAIT"
        confidence = 50

    confidence = max(0, min(95, confidence))

    if signal != "WAIT" and confidence < 78:
        signal = "WAIT"

    if signal == "CALL":
        analysis = (
            "Bullish alignment detected: EMA structure, momentum and "
            "oscillator conditions are supporting CALL."
        )
    elif signal == "PUT":
        analysis = (
            "Bearish alignment detected: EMA structure, momentum and "
            "oscillator conditions are supporting PUT."
        )
    else:
        analysis = (
            "Conditions are mixed or below the 78% confirmation threshold. "
            "ALUCARD is waiting."
        )

    return {
        "signal": signal,
        "confidence": confidence,
        "price": price,
        "ema9": ema9,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "cci": cci,
        "atr": atr,
        "macd": macd,
        "macd_signal": macd_signal,
        "analysis": analysis
    }


def update_state_from_candles(candles, asset="UNKNOWN"):
    result = analyze_candles(candles)

    with STATE_LOCK:
        STATE["asset"] = asset or STATE["asset"]
        STATE["candles"] = len(candles)
        STATE["signal"] = result.get("signal", "WAIT")
        STATE["confidence"] = result.get("confidence", 0)
        STATE["price"] = clean_float(result.get("price"))

        STATE["ema9"] = clean_float(result.get("ema9"))
        STATE["ema20"] = clean_float(result.get("ema20"))
        STATE["ema50"] = clean_float(result.get("ema50"))
        STATE["rsi"] = clean_float(result.get("rsi"))
        STATE["cci"] = clean_float(result.get("cci"))
        STATE["atr"] = clean_float(result.get("atr"))
        STATE["macd"] = clean_float(result.get("macd"))
        STATE["macd_signal"] = clean_float(result.get("macd_signal"))

        STATE["entry"] = STATE["price"]
        STATE["analysis"] = result.get(
            "analysis",
            "Analysis waiting..."
        )

        STATE["feed"] = "LIVE"
        STATE["updated"] = time.time()


# ============================================================
# SCREEN FRAME RECEIVER
# ============================================================

@app.route("/api/frame", methods=["POST"])
def receive_frame():
    global LAST_IMAGE

    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    raw = request.get_data()

    # Also allow multipart uploads.
    if not raw and request.files:
        uploaded = next(iter(request.files.values()), None)

        if uploaded:
            raw = uploaded.read()

    if not raw:
        return jsonify({
            "ok": False,
            "error": "No image received"
        }), 400

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()

        width, height = image.size

        LAST_IMAGE = raw

        with STATE_LOCK:
            STATE["feed"] = "LIVE"
            STATE["image_received"] = True
            STATE["frame_bytes"] = len(raw)
            STATE["last_frame"] = now_utc()
            STATE["updated"] = time.time()

            # Keep existing structured values if available.
            if STATE["analysis"].startswith("Waiting for"):
                STATE["analysis"] = (
                    "LIVE screen feed received. "
                    "Waiting for structured candle/price data."
                )

        return jsonify({
            "ok": True,
            "message": "Frame accepted",
            "width": width,
            "height": height,
            "bytes": len(raw),
            "feed": "LIVE",
            "image_received": True,
            "state": public_state()
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": "Invalid image",
            "detail": str(exc)
        }), 400


# ============================================================
# JSON FEED RECEIVER
# ============================================================

@app.route("/api/feed", methods=["POST"])
def receive_feed():
    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    asset = (
        data.get("asset")
        or data.get("symbol")
        or data.get("pair")
        or "UNKNOWN"
    )

    # --------------------------------------------------------
    # Direct values
    # --------------------------------------------------------

    price = clean_float(
        data.get("price")
        or data.get("close")
    )

    signal = str(
        data.get("signal")
        or data.get("direction")
        or "WAIT"
    ).upper()

    if signal not in ("CALL", "PUT", "WAIT"):
        signal = "WAIT"

    confidence = clean_int(
        data.get("confidence"),
        0
    )

    candles = data.get("candles")

    # --------------------------------------------------------
    # Structured candle list
    # --------------------------------------------------------

    if isinstance(candles, list) and candles:

        normalized = []

        for c in candles:
            if not isinstance(c, dict):
                continue

            normalized.append({
                "open": clean_float(c.get("open")),
                "high": clean_float(c.get("high")),
                "low": clean_float(c.get("low")),
                "close": clean_float(c.get("close"))
            })

        if normalized:
            update_state_from_candles(
                normalized,
                asset
            )

    # --------------------------------------------------------
    # Direct feed values override / supplement analysis.
    # --------------------------------------------------------

    with STATE_LOCK:
        STATE["feed"] = "LIVE"
        STATE["asset"] = asset

        if price > 0:
            STATE["price"] = price
            STATE["entry"] = clean_float(
                data.get("entry"),
                price
            )

        if "confidence" in data:
            STATE["confidence"] = max(
                0,
                min(100, confidence)
            )

        if "signal" in data or "direction" in data:
            STATE["signal"] = signal

        if "entry_window" in data:
            STATE["entry_window"] = clean_int(
                data.get("entry_window"),
                12
            )

        if "fractal" in data:
            STATE["fractal"] = clean_int(
                data.get("fractal"),
                2
            )

        if "expiry" in data:
            STATE["expiry"] = str(
                data.get("expiry") or "5m"
            )

        # Direct indicator values if supplied.
        indicator_map = {
            "ema9": "ema9",
            "ema20": "ema20",
            "ema50": "ema50",
            "rsi": "rsi",
            "cci": "cci",
            "atr": "atr",
            "macd": "macd",
            "macd_signal": "macd_signal",
            "sar": "sar"
        }

        for incoming, state_key in indicator_map.items():
            if incoming in data:
                STATE[state_key] = clean_float(
                    data.get(incoming)
                )

        if "analysis" in data:
            STATE["analysis"] = str(
                data.get("analysis") or ""
            )

        STATE["last_frame"] = now_utc()
        STATE["image_received"] = bool(
            data.get("image_received", STATE["image_received"])
        )
        STATE["updated"] = time.time()

        if not STATE["analysis"]:
            STATE["analysis"] = (
                "Live market data received."
            )

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": public_state()
    })


# ============================================================
# OPTIONAL COMBINED ENDPOINT
# ============================================================

@app.route("/api/frame-json", methods=["POST"])
def receive_frame_json():
    """
    Allows a bridge to send:
    {
        asset: "...",
        price: ...,
        candles: [...],
        image: optional base64 data
    }

    This endpoint primarily handles JSON.
    """

    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    # Reuse normal feed processing.
    asset = data.get("asset", "UNKNOWN")

    candles = data.get("candles", [])

    if isinstance(candles, list) and candles:
        normalized = []

        for c in candles:
            if isinstance(c, dict):
                normalized.append({
                    "open": clean_float(c.get("open")),
                    "high": clean_float(c.get("high")),
                    "low": clean_float(c.get("low")),
                    "close": clean_float(c.get("close"))
                })

        if normalized:
            update_state_from_candles(
                normalized,
                asset
            )

    with STATE_LOCK:
        if data.get("price") is not None:
            STATE["price"] = clean_float(
                data.get("price")
            )

        if data.get("signal"):
            s = str(data.get("signal")).upper()
            if s in ("CALL", "PUT", "WAIT"):
                STATE["signal"] = s

        if data.get("confidence") is not None:
            STATE["confidence"] = max(
                0,
                min(
                    100,
                    clean_int(data.get("confidence"))
                )
            )

        STATE["feed"] = "LIVE"
        STATE["last_frame"] = now_utc()
        STATE["updated"] = time.time()

    return jsonify({
        "ok": True,
        "message": "Combined feed accepted",
        "state": public_state()
    })


# ============================================================
# STATE
# ============================================================

def public_state():
    with STATE_LOCK:
        state = dict(STATE)

    # Never expose internal timestamp.
    state.pop("updated", None)

    return state


@app.route("/api/state", methods=["GET"])
def api_state():
    # Feed timeout.
    with STATE_LOCK:
        last_update = STATE.get("updated", 0)

    if last_update:
        age = time.time() - last_update

        if age > 15:
            with STATE_LOCK:
                STATE["feed"] = "DISCONNECTED"

    return jsonify(public_state())


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1",
        "feed": public_state()["feed"],
        "time": now_utc()
    })


@app.route("/health", methods=["GET"])
def health_short():
    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1"
    })


# ============================================================
# SCREEN IMAGE
# ============================================================

@app.route("/api/latest-frame", methods=["GET"])
def latest_frame():
    global LAST_IMAGE

    if LAST_IMAGE is None:
        return jsonify({
            "ok": False,
            "error": "No frame available"
        }), 404

    return (
        LAST_IMAGE,
        200,
        {
            "Content-Type": "image/jpeg",
            "Cache-Control": "no-store"
        }
    )


# ============================================================
# MAIN DASHBOARD
# ============================================================

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top, #24152c 0%, #09080d 55%, #030306 100%);
    color: #eee;
    font-family: Arial, Helvetica, sans-serif;
}

.header {
    padding: 18px 14px 10px;
    text-align: center;
    border-bottom: 1px solid #3d2947;
}

.title {
    font-size: 28px;
    font-weight: 900;
    letter-spacing: 5px;
    color: #eee;
}

.subtitle {
    margin-top: 5px;
    font-size: 11px;
    letter-spacing: 2px;
    color: #a68caf;
}

.status {
    margin: 12px auto;
    width: 94%;
    padding: 11px;
    border-radius: 9px;
    background: #151118;
    border: 1px solid #3d2947;
    font-size: 13px;
}

.live {
    color: #7dffb2;
    font-weight: 900;
}

.dead {
    color: #ff6d7d;
    font-weight: 900;
}

.tabs {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 5px;
    padding: 8px;
}

.tab {
    background: #161119;
    border: 1px solid #38243f;
    border-radius: 7px;
    padding: 10px 3px;
    text-align: center;
    font-size: 11px;
}

.tab:first-child {
    border-color: #9d54c6;
}

.assetbox {
    padding: 8px 14px;
}

select {
    width: 100%;
    padding: 12px;
    background: #111016;
    color: white;
    border: 1px solid #59366a;
    border-radius: 8px;
    font-size: 15px;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 9px;
    padding: 10px 14px;
}

.card {
    background: rgba(17,15,21,.96);
    border: 1px solid #302438;
    border-radius: 10px;
    padding: 13px;
    min-height: 75px;
}

.label {
    font-size: 10px;
    color: #967d9f;
    letter-spacing: 1px;
    margin-bottom: 7px;
}

.value {
    font-size: 21px;
    font-weight: 900;
}

.signal {
    grid-column: span 2;
    text-align: center;
    min-height: 100px;
}

.signal .value {
    font-size: 34px;
    letter-spacing: 3px;
}

.wait {
    color: #d0b9d7;
}

.call {
    color: #69ffad;
}

.put {
    color: #ff6575;
}

.analysis {
    margin: 5px 14px 15px;
    padding: 14px;
    background: #100d13;
    border: 1px solid #302438;
    border-radius: 10px;
    line-height: 1.45;
    font-size: 13px;
    color: #cbbbd0;
}

.footer {
    padding: 14px;
    text-align: center;
    color: #66556c;
    font-size: 10px;
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

<div class="status">
    Feed:
    <span id="feed" class="dead">DISCONNECTED</span>
    &nbsp; | &nbsp;
    Asset:
    <span id="asset">UNKNOWN</span>
    <br>
    <small>
        Last frame:
        <span id="lastFrame">Waiting...</span>
    </small>
</div>

<div class="tabs">
    <div class="tab">Signals</div>
    <div class="tab">Trades</div>
    <div class="tab">Performance</div>
    <div class="tab">Settings</div>
</div>

<div class="assetbox">
    <select id="assetSelect">
        <option>EURUSD</option>
        <option>GBPUSD</option>
        <option>USDJPY</option>
        <option>USDCHF</option>
        <option>AUDUSD</option>
        <option>USDCAD</option>
        <option>NZDUSD</option>

        <option>EURGBP</option>
        <option>EURJPY</option>
        <option>GBPJPY</option>
        <option>GBPCHF</option>
        <option>AUDJPY</option>
        <option>CADJPY</option>

        <option>EURUSD OTC</option>
        <option>GBPUSD OTC</option>
        <option>USDJPY OTC</option>
        <option>EURJPY OTC</option>
        <option>GBPJPY OTC</option>
        <option>AUDUSD OTC</option>

        <option>BTCUSD</option>
        <option>ETHUSD</option>
        <option>LTCUSD</option>
        <option>XRPUSD</option>

        <option>GOLD</option>
        <option>SILVER</option>
        <option>OIL</option>
        <option>NATURAL GAS</option>

        <option>AAPL</option>
        <option>TSLA</option>
        <option>AMZN</option>
        <option>MSFT</option>
        <option>GOOGL</option>
        <option>NVDA</option>

        <option>US30</option>
        <option>NAS100</option>
        <option>SP500</option>
    </select>
</div>

<div class="grid">

    <div class="card signal">
        <div class="label">SIGNAL</div>
        <div id="signal" class="value wait">WAIT</div>
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
        <div id="entryWindow" class="value">12s</div>
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
        <div id="atr" class="value">0.00</div>
    </div>

    <div class="card">
        <div class="label">MACD</div>
        <div id="macd" class="value">0.00</div>
    </div>

    <div class="card">
        <div class="label">SAR</div>
        <div id="sar" class="value">0.00</div>
    </div>

</div>

<div class="analysis">
    <b>ALUCARD ANALYSIS</b>
    <br><br>
    <span id="analysis">
        Waiting for screen feed...
    </span>
</div>

<div class="footer">
    ALUCARD V2.1 • SCREEN FEED INTELLIGENCE
</div>

<script>

function fmt(x, digits=6) {
    let n = Number(x || 0);

    if (!Number.isFinite(n)) {
        n = 0;
    }

    return n.toFixed(digits);
}

function setText(id, value) {
    const el = document.getElementById(id);

    if (el) {
        el.textContent = value;
    }
}

async function update() {

    try {

        const response = await fetch(
            "/api/state?ts=" + Date.now(),
            {
                cache: "no-store"
            }
        );

        const s = await response.json();

        const feed = String(
            s.feed || "DISCONNECTED"
        ).toUpperCase();

        setText("feed", feed);

        const feedEl = document.getElementById("feed");

        feedEl.className =
            feed === "LIVE"
            ? "live"
            : "dead";

        setText(
            "asset",
            s.asset || "UNKNOWN"
        );

        setText(
            "lastFrame",
            s.last_frame || "Waiting..."
        );

        const signal =
            String(s.signal || "WAIT").toUpperCase();

        const signalEl =
            document.getElementById("signal");

        signalEl.textContent = signal;

        signalEl.className =
            "value " +
            (
                signal === "CALL"
                ? "call"
                : signal === "PUT"
                ? "put"
                : "wait"
            );

        setText(
            "price",
            fmt(s.price)
        );

        setText(
            "confidence",
            Math.round(Number(s.confidence || 0)) + "%"
        );

        setText(
            "entry",
            fmt(s.entry)
        );

        setText(
            "entryWindow",
            (s.entry_window || 12) + "s"
        );

        setText(
            "candles",
            s.candles || 0
        );

        setText(
            "fractal",
            s.fractal || 2
        );

        setText(
            "expiry",
            s.expiry || "5m"
        );

        setText(
            "ema9",
            fmt(s.ema9)
        );

        setText(
            "ema20",
            fmt(s.ema20)
        );

        setText(
            "ema50",
            fmt(s.ema50)
        );

        setText(
            "rsi",
            fmt(s.rsi, 2)
        );

        setText(
            "cci",
            fmt(s.cci, 2)
        );

        setText(
            "atr",
            fmt(s.atr, 6)
        );

        setText(
            "macd",
            fmt(s.macd, 6)
        );

        setText(
            "sar",
            fmt(s.sar, 6)
        );

        setText(
            "analysis",
            s.analysis || "Waiting for analysis..."
        );

    } catch (error) {

        setText(
            "feed",
            "DISCONNECTED"
        );

        document.getElementById(
            "feed"
        ).className = "dead";
    }
}

update();

setInterval(
    update,
    1000
);

</script>

</body>
</html>
"""


@app.route("/", methods=["GET"])
def dashboard():
    return render_template_string(HTML)


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
