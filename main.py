from flask import Flask, request, jsonify, Response
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone
import time
import threading
import math

app = Flask(__name__)

# ============================================================
# ALUCARD V2.1
# Screen-feed server
# ============================================================

state = {
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
    "payout": 0,
    "analysis": "Waiting for screen feed...",
    "image_received": False,
    "last_frame": None,
    "frame_bytes": 0,
    "updated": None,
}

last_image = None
state_lock = threading.Lock()


def now_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def mark_frame(size):
    global last_image

    with state_lock:
        state["feed"] = "LIVE"
        state["image_received"] = True
        state["last_frame"] = now_string()
        state["frame_bytes"] = int(size)
        state["updated"] = time.time()

        if state["asset"] == "UNKNOWN":
            state["analysis"] = (
                "Screen feed connected. Waiting for readable market data."
            )
        else:
            state["analysis"] = "Screen feed connected."


def validate_image(data):
    try:
        image = Image.open(BytesIO(data))
        image.verify()
        return True
    except Exception:
        return False


# ============================================================
# SCREEN FRAME ENDPOINT
# ============================================================

@app.route("/api/frame", methods=["POST"])
def api_frame():
    """
    Endpoint used by alucard_bridge.py

    Expected:
        multipart/form-data
        image=<jpg/png/webp>
    """

    if "image" not in request.files:
        return jsonify({
            "ok": False,
            "error": "No image field received"
        }), 400

    uploaded = request.files["image"]

    try:
        data = uploaded.read()

        if not data:
            return jsonify({
                "ok": False,
                "error": "Empty image"
            }), 400

        if not validate_image(data):
            return jsonify({
                "ok": False,
                "error": "Invalid image"
            }), 400

        mark_frame(len(data))

        return jsonify({
            "ok": True,
            "message": "Screen frame accepted",
            "bytes": len(data),
            "feed": "LIVE",
            "last_frame": state["last_frame"]
        }), 200

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ============================================================
# JSON FEED ENDPOINT
# ============================================================

@app.route("/api/feed", methods=["POST"])
def api_feed():
    global last_image

    # Accept JSON
    if request.is_json:
        data = request.get_json(silent=True) or {}

        with state_lock:
            if "asset" in data:
                state["asset"] = str(data["asset"])

            if "price" in data:
                try:
                    state["price"] = float(data["price"])
                except Exception:
                    pass

            if "signal" in data:
                signal = str(data["signal"]).upper()
                if signal in ("CALL", "PUT", "WAIT"):
                    state["signal"] = signal

            numeric_fields = [
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
                "atr",
                "payout",
            ]

            for key in numeric_fields:
                if key in data:
                    try:
                        state[key] = float(data[key])
                    except Exception:
                        pass

            if "expiry" in data:
                state["expiry"] = str(data["expiry"])

            if "analysis" in data:
                state["analysis"] = str(data["analysis"])

            state["feed"] = "LIVE"
            state["updated"] = time.time()
            state["last_frame"] = now_string()

        return jsonify({
            "ok": True,
            "message": "JSON feed accepted",
            "state": public_state()
        }), 200

    # Also accept image through /api/feed
    if "image" in request.files:
        uploaded = request.files["image"]

        try:
            data = uploaded.read()

            if not data:
                return jsonify({
                    "ok": False,
                    "error": "Empty image"
                }), 400

            if not validate_image(data):
                return jsonify({
                    "ok": False,
                    "error": "Invalid image"
                }), 400

            mark_frame(len(data))

            return jsonify({
                "ok": True,
                "message": "Image feed accepted",
                "bytes": len(data),
                "feed": "LIVE"
            }), 200

        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": str(exc)
            }), 500

    return jsonify({
        "ok": False,
        "error": "No JSON data or image received"
    }), 400


# ============================================================
# STATE
# ============================================================

def public_state():
    with state_lock:
        result = dict(state)

    # Convert integer-looking floats back to clean values
    for key in ["confidence", "candles", "fractal", "payout"]:
        try:
            result[key] = int(result[key])
        except Exception:
            pass

    return result


@app.route("/api/state", methods=["GET"])
def api_state():
    # Mark feed disconnected if nothing has arrived recently.
    with state_lock:
        updated = state["updated"]

    if updated is not None and time.time() - updated > 20:
        with state_lock:
            state["feed"] = "DISCONNECTED"

    return jsonify(public_state())


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1",
        "feed": state["feed"],
        "last_frame": state["last_frame"]
    })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top, #24152c 0%, #09070c 45%, #030305 100%);
    color: #eee;
    font-family: Arial, Helvetica, sans-serif;
}

.header {
    padding: 18px 14px 10px;
    text-align: center;
    border-bottom: 1px solid #3a263f;
}

.title {
    font-size: 30px;
    font-weight: 900;
    letter-spacing: 4px;
}

.subtitle {
    color: #a991ad;
    font-size: 12px;
    letter-spacing: 2px;
    margin-top: 5px;
}

.nav {
    display: flex;
    justify-content: center;
    gap: 8px;
    padding: 12px;
    flex-wrap: wrap;
}

.nav button {
    background: #120d16;
    border: 1px solid #47334c;
    color: #cdbbd2;
    padding: 9px 14px;
    border-radius: 7px;
}

.status {
    margin: 8px auto;
    width: calc(100% - 24px);
    max-width: 1100px;
    padding: 12px;
    background: #100c13;
    border: 1px solid #35253b;
    border-radius: 8px;
    text-align: center;
}

.live {
    color: #65ff9b;
}

.dead {
    color: #ff5d6c;
}

.container {
    width: calc(100% - 24px);
    max-width: 1100px;
    margin: auto;
}

.assetbox {
    background: #0e0b11;
    border: 1px solid #3a2b40;
    border-radius: 10px;
    padding: 14px;
    margin: 12px 0;
}

.assetbox label {
    display: block;
    color: #9e8ba3;
    font-size: 12px;
    margin-bottom: 6px;
}

select {
    width: 100%;
    padding: 12px;
    background: #17111a;
    color: white;
    border: 1px solid #54415b;
    border-radius: 7px;
    font-size: 16px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
}

.card {
    background: #0d0a10;
    border: 1px solid #342638;
    border-radius: 9px;
    padding: 14px;
    min-height: 92px;
}

.label {
    color: #9a879f;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.value {
    margin-top: 9px;
    font-size: 23px;
    font-weight: 800;
}

.signal {
    font-size: 30px;
    letter-spacing: 2px;
}

.analysis {
    margin-top: 12px;
    background: #0d0a10;
    border: 1px solid #342638;
    border-radius: 9px;
    padding: 16px;
}

.analysis-title {
    color: #a993ad;
    font-size: 12px;
    letter-spacing: 2px;
    margin-bottom: 9px;
}

#analysis {
    line-height: 1.5;
}

.footer {
    text-align: center;
    color: #66586a;
    font-size: 11px;
    padding: 25px;
}

@media(max-width:800px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media(max-width:450px) {
    .grid {
        grid-template-columns: 1fr 1fr;
    }

    .title {
        font-size: 23px;
    }
}
</style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE — V2.1</div>
</div>

<div class="nav">
    <button>Signals</button>
    <button>Trades</button>
    <button>Performance</button>
    <button>Settings</button>
</div>

<div class="status">
    Feed:
    <strong id="feed" class="dead">DISCONNECTED</strong>
    &nbsp; | &nbsp;
    Asset:
    <strong id="asset">UNKNOWN</strong>
    <br>
    <span id="frameStatus">WAITING — last frame: none</span>
</div>

<div class="container">

<div class="assetbox">
    <label>Currency / Asset</label>

    <select id="assetSelect" onchange="changeAsset()">

        <optgroup label="FOREX">
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
            <option>AUDJPY</option>
            <option>CADJPY</option>
            <option>CHFJPY</option>
            <option>EURCHF</option>
            <option>GBPCHF</option>
            <option>AUDCAD</option>
            <option>EURCAD</option>
            <option>GBPCAD</option>
        </optgroup>

        <optgroup label="OTC">
            <option>EURUSD_otc</option>
            <option>GBPUSD_otc</option>
            <option>USDJPY_otc</option>
            <option>EURJPY_otc</option>
            <option>GBPJPY_otc</option>
            <option>AUDUSD_otc</option>
            <option>USDCAD_otc</option>
            <option>USDCHF_otc</option>
            <option>EURGBP_otc</option>
        </optgroup>

        <optgroup label="CRYPTO">
            <option>BTCUSD</option>
            <option>BTCUSD_otc</option>
            <option>ETHUSD</option>
            <option>ETHUSD_otc</option>
            <option>LTCUSD</option>
            <option>XRPUSD</option>
            <option>ADAUSD</option>
            <option>BNBUSD</option>
            <option>SOLUSD</option>
        </optgroup>

        <optgroup label="COMMODITIES">
            <option>GOLD</option>
            <option>GOLD_otc</option>
            <option>SILVER</option>
            <option>OIL</option>
            <option>BRENT</option>
            <option>NATURALGAS</option>
        </optgroup>

        <optgroup label="INDICES">
            <option>SP500</option>
            <option>NASDAQ</option>
            <option>DOW</option>
            <option>RUSSELL</option>
            <option>FTSE</option>
            <option>DAX</option>
            <option>ASIA</option>
        </optgroup>

        <optgroup label="STOCKS">
            <option>AAPL</option>
            <option>MSFT</option>
            <option>TSLA</option>
            <option>AMZN</option>
            <option>GOOGL</option>
            <option>META</option>
            <option>NVDA</option>
            <option>NFLX</option>
        </optgroup>

    </select>
</div>

<div class="grid">

    <div class="card">
        <div class="label">Signal</div>
        <div class="value signal" id="signal">WAIT</div>
    </div>

    <div class="card">
        <div class="label">Price</div>
        <div class="value" id="price">0.000000</div>
    </div>

    <div class="card">
        <div class="label">Confidence</div>
        <div class="value" id="confidence">0%</div>
    </div>

    <div class="card">
        <div class="label">Entry</div>
        <div class="value" id="entry">0.000000</div>
    </div>

    <div class="card">
        <div class="label">Entry Window</div>
        <div class="value" id="entry_window">12s</div>
    </div>

    <div class="card">
        <div class="label">Candles</div>
        <div class="value" id="candles">0</div>
    </div>

    <div class="card">
        <div class="label">Fractal</div>
        <div class="value" id="fractal">2</div>
    </div>

    <div class="card">
        <div class="label">Expiry</div>
        <div class="value" id="expiry">5m</div>
    </div>

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
        <div class="label">CCI</div>
        <div class="value" id="cci">0.00</div>
    </div>

    <div class="card">
        <div class="label">ATR</div>
        <div class="value" id="atr">0.000000</div>
    </div>

    <div class="card">
        <div class="label">Payout</div>
        <div class="value" id="payout">0%</div>
    </div>

</div>

<div class="analysis">
    <div class="analysis-title">ANALYSIS</div>
    <div id="analysis">Waiting for screen feed...</div>
</div>

</div>

<div class="footer">
ALUCARD V2.1 • SCREEN FEED INTELLIGENCE
</div>

<script>

function set(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function fmt(value, digits) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "0";
    return n.toFixed(digits);
}

async function refresh() {

    try {

        const response = await fetch("/api/state", {
            cache: "no-store"
        });

        if (!response.ok) return;

        const d = await response.json();

        set("feed", d.feed || "DISCONNECTED");
        set("asset", d.asset || "UNKNOWN");

        const feed = document.getElementById("feed");

        if ((d.feed || "").toUpperCase() === "LIVE") {
            feed.className = "live";
        } else {
            feed.className = "dead";
        }

        if (d.last_frame) {
            set(
                "frameStatus",
                "LIVE — last frame: " + d.last_frame
            );
        } else {
            set(
                "frameStatus",
                "WAITING — last frame: none"
            );
        }

        set("signal", d.signal || "WAIT");
        set("price", fmt(d.price, 6));
        set("confidence", Math.round(Number(d.confidence) || 0) + "%");
        set("entry", fmt(d.entry, 6));
        set("entry_window",
            Math.round(Number(d.entry_window) || 12) + "s"
        );
        set("candles",
            Math.round(Number(d.candles) || 0)
        );
        set("fractal",
            Math.round(Number(d.fractal) || 2)
        );
        set("expiry", d.expiry || "5m");

        set("ema9", fmt(d.ema9, 6));
        set("ema20", fmt(d.ema20, 6));
        set("ema50", fmt(d.ema50, 6));

        set("rsi", fmt(d.rsi, 2));
        set("cci", fmt(d.cci, 2));
        set("atr", fmt(d.atr, 6));

        set("payout",
            Math.round(Number(d.payout) || 0) + "%"
        );

        set(
            "analysis",
            d.analysis || "Waiting for screen feed..."
        );

    } catch (error) {
        set("feed", "DISCONNECTED");
        document.getElementById("feed").className = "dead";
    }
}

async function changeAsset() {

    const asset =
        document.getElementById("assetSelect").value;

    try {

        await fetch("/api/feed", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                asset: asset
            })
        });

    } catch (error) {
        // Feed may be offline; ignore.
    }
}

refresh();

setInterval(refresh, 1000);

</script>

</body>
</html>
"""


@app.route("/", methods=["GET"])
def dashboard():
    return Response(HTML, mimetype="text/html")


# ============================================================
# FALLBACK / INFO
# ============================================================

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "ok": False,
        "error": "Endpoint not found"
    }), 404


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
