import os
import io
import time
import base64
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string
from PIL import Image, ImageStat, ImageFilter

app = Flask(__name__)

VERSION = "ALUCARD-V2-CURRENCIES-FEED-4.0"

FEED_TOKEN = os.environ.get("RYU_FEED_TOKEN", "").strip()

# ============================================================
# CURRENCY MENU
# ============================================================

CURRENCIES = [
    # MAJORS
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",

    # EUR CROSSES
    "EUR/GBP",
    "EUR/JPY",
    "EUR/CHF",
    "EUR/AUD",
    "EUR/CAD",
    "EUR/NZD",

    # GBP CROSSES
    "GBP/JPY",
    "GBP/CHF",
    "GBP/AUD",
    "GBP/CAD",
    "GBP/NZD",

    # AUD CROSSES
    "AUD/JPY",
    "AUD/CHF",
    "AUD/CAD",
    "AUD/NZD",

    # CAD CROSSES
    "CAD/JPY",
    "CAD/CHF",

    # NZD CROSSES
    "NZD/JPY",
    "NZD/CHF",

    # CHF / JPY
    "CHF/JPY",

    # USD CROSSES
    "USD/SGD",
    "USD/HKD",
    "USD/SEK",
    "USD/NOK",
    "USD/DKK",
    "USD/PLN",
    "USD/TRY",
    "USD/MXN",
    "USD/ZAR",

    # EUR ADDITIONAL
    "EUR/SEK",
    "EUR/NOK",
    "EUR/PLN",
    "EUR/TRY",
    "EUR/ZAR",

    # GBP ADDITIONAL
    "GBP/SGD",
    "GBP/ZAR",

    # ASIAN
    "SGD/JPY",
    "HKD/JPY",

    # OTC COMMON NAMES
    "EUR/USD OTC",
    "GBP/USD OTC",
    "USD/JPY OTC",
    "USD/CHF OTC",
    "AUD/USD OTC",
    "USD/CAD OTC",
    "NZD/USD OTC",
    "EUR/GBP OTC",
    "EUR/JPY OTC",
    "GBP/JPY OTC",
    "AUD/JPY OTC",
    "EUR/AUD OTC",
    "GBP/AUD OTC",
    "USD/SGD OTC",
    "USD/HKD OTC",
    "USD/MXN OTC",
]


# ============================================================
# GLOBAL STATE
# ============================================================

STATE = {
    "connected": False,
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

    "analysis": "Waiting for screen feed...",

    "last_frame": 0.0,
    "last_update": "",

    "image_received": False,
    "frame_bytes": 0,
    "frame_width": 0,
    "frame_height": 0,

    "selected_currency": "EUR/USD",
}


# ============================================================
# HELPERS
# ============================================================

def now_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def token_ok(req):
    if not FEED_TOKEN:
        return True

    supplied = (
        req.headers.get("X-RYU-TOKEN")
        or req.headers.get("X-ALUCARD-TOKEN")
        or req.args.get("token")
        or ""
    )

    return supplied == FEED_TOKEN


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def image_from_request(req):

    # Multipart uploads
    for name in ("image", "file", "frame", "screenshot"):

        uploaded = req.files.get(name)

        if uploaded:
            data = uploaded.read()

            if data:
                return data

    # Raw image POST
    raw = req.get_data(cache=True)

    if raw:

        content_type = (req.content_type or "").lower()

        if (
            content_type.startswith("image/")
            or raw.startswith(b"\xff\xd8")
            or raw.startswith(b"\x89PNG")
            or raw.startswith(b"RIFF")
            or raw.startswith(b"GIF8")
        ):
            return raw

    # JSON/base64 image
    try:

        data = req.get_json(silent=True)

        if isinstance(data, dict):

            for key in (
                "image",
                "frame",
                "screenshot",
                "data",
                "image_base64",
            ):

                value = data.get(key)

                if not value:
                    continue

                if isinstance(value, str):

                    if value.startswith("data:") and "," in value:
                        value = value.split(",", 1)[1]

                    try:
                        decoded = base64.b64decode(value)

                        if decoded:
                            return decoded

                    except Exception:
                        pass

    except Exception:
        pass

    return None


# ============================================================
# SCREEN ANALYSIS
# ============================================================

def analyze_screen(image_bytes):

    try:

        image = Image.open(io.BytesIO(image_bytes))
        image.load()

        width, height = image.size

        preview = image.convert("RGB")

        if width > 800:

            new_width = 800
            new_height = max(
                1,
                int(height * new_width / width)
            )

            preview = preview.resize(
                (new_width, new_height)
            )

        preview = preview.filter(
            ImageFilter.MedianFilter(size=3)
        )

        stat = ImageStat.Stat(preview)

        mean_r, mean_g, mean_b = stat.mean[:3]

        brightness = (
            mean_r +
            mean_g +
            mean_b
        ) / 3.0

        green_bias = (
            mean_g -
            ((mean_r + mean_b) / 2.0)
        )

        if green_bias > 2:

            description = (
                "Live screen feed received. "
                "Chart detected."
            )

        elif brightness < 25:

            description = (
                "Live screen feed received. "
                "Screen appears dark."
            )

        else:

            description = (
                "Live screen feed received. "
                "Analyzing chart."
            )

        return {
            "width": width,
            "height": height,
            "brightness": round(brightness, 2),
            "green_bias": round(green_bias, 2),
            "analysis": description,
        }

    except Exception as exc:

        raise ValueError(
            "Invalid image: " + str(exc)
        )


# ============================================================
# UPDATE STATE
# ============================================================

def update_live_state(extra=None, image_info=None):

    with STATE_LOCK:

        STATE["connected"] = True
        STATE["feed"] = "LIVE"

        STATE["last_frame"] = time.time()
        STATE["last_update"] = now_string()

        if image_info:

            STATE["image_received"] = True

            STATE["frame_width"] = image_info["width"]
            STATE["frame_height"] = image_info["height"]

            STATE["analysis"] = image_info["analysis"]

        if extra:

            for key in (
                "asset",
                "price",
                "signal",
                "confidence",
                "entry",
                "entry_window",
                "candles",
                "fractal",
                "ema9",
                "ema20",
                "ema50",
                "rsi",
                "macd",
                "cci",
            ):

                if key not in extra:
                    continue

                value = extra[key]

                if key in (
                    "price",
                    "entry",
                    "ema9",
                    "ema20",
                    "ema50",
                    "rsi",
                    "macd",
                    "cci",
                ):

                    value = safe_float(value)

                elif key in (
                    "confidence",
                    "entry_window",
                    "candles",
                    "fractal",
                ):

                    value = safe_int(value)

                elif key == "signal":

                    value = str(value).upper()

                elif key == "asset":

                    value = str(value)

                STATE[key] = value

        if STATE["signal"] not in (
            "CALL",
            "PUT",
            "WAIT",
        ):

            STATE["signal"] = "WAIT"

        STATE["confidence"] = clamp(
            safe_int(STATE["confidence"]),
            0,
            100
        )

        # User requested Fractal 2.
        STATE["fractal"] = 2


STATE_LOCK = __import__("threading").Lock()


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2",
        "version": VERSION,
        "feed_endpoint": "/api/feed",
        "currencies": len(CURRENCIES),
    })


@app.route("/api/health")
def api_health():

    with STATE_LOCK:

        return jsonify({
            "ok": True,
            "service": "ALUCARD V2",
            "version": VERSION,
            "connected": STATE["connected"],
            "feed": STATE["feed"],
            "image_received": STATE["image_received"],
        })


# ============================================================
# STATE
# ============================================================

@app.route("/api/state")
def api_state():

    with STATE_LOCK:

        age = time.time() - STATE["last_frame"]

        if (
            STATE["last_frame"] > 0
            and age > 15
        ):

            STATE["connected"] = False
            STATE["feed"] = "DISCONNECTED"

            if STATE["image_received"]:

                STATE["analysis"] = (
                    "Screen feed stopped. "
                    "Waiting for next frame..."
                )

        return jsonify(dict(STATE))


# ============================================================
# CURRENCY API
# ============================================================

@app.route("/api/currencies")
def api_currencies():

    return jsonify({
        "ok": True,
        "count": len(CURRENCIES),
        "currencies": CURRENCIES,
    })


@app.route("/api/currency", methods=["POST"])
def api_currency():

    data = request.get_json(silent=True) or {}

    currency = str(
        data.get("currency", "")
    ).strip()

    if currency not in CURRENCIES:

        return jsonify({
            "ok": False,
            "error": "Currency not found",
        }), 400

    with STATE_LOCK:

        STATE["selected_currency"] = currency

        # Only change asset if the live feed has not supplied one.
        if (
            not STATE["asset"]
            or STATE["asset"] == "UNKNOWN"
        ):

            STATE["asset"] = currency

    return jsonify({
        "ok": True,
        "selected_currency": currency,
    })


# ============================================================
# FEED
# ============================================================

@app.route("/api/feed", methods=["POST"])
def api_feed():

    if not token_ok(request):

        return jsonify({
            "ok": False,
            "error": "Invalid feed token",
        }), 401

    image_bytes = image_from_request(request)

    # --------------------------------------------------------
    # SCREEN IMAGE
    # --------------------------------------------------------

    if image_bytes:

        try:

            image_info = analyze_screen(
                image_bytes
            )

            update_live_state(
                image_info=image_info
            )

            with STATE_LOCK:

                STATE["frame_bytes"] = len(
                    image_bytes
                )

                state_copy = dict(STATE)

            return jsonify({
                "ok": True,
                "message": "Screen frame accepted",
                "state": state_copy,
            }), 200

        except Exception as exc:

            return jsonify({
                "ok": False,
                "error": str(exc),
            }), 400

    # --------------------------------------------------------
    # JSON MARKET DATA
    # --------------------------------------------------------

    data = request.get_json(silent=True)

    if isinstance(data, dict):

        update_live_state(
            extra=data
        )

        with STATE_LOCK:

            state_copy = dict(STATE)

        return jsonify({
            "ok": True,
            "message": "JSON feed accepted",
            "state": state_copy,
        }), 200

    return jsonify({
        "ok": False,
        "error": "No image or JSON feed data received",
    }), 400


# ============================================================
# ALIASES
# ============================================================

@app.route("/api/screenshot", methods=["POST"])
def screenshot():

    return api_feed()


@app.route("/feed", methods=["POST"])
def feed():

    return api_feed()


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>ALUCARD V2</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    background:
        radial-gradient(
            circle at top,
            #242424 0%,
            #080808 55%,
            #000000 100%
        );

    color: #eeeeee;

    font-family:
        Arial,
        Helvetica,
        sans-serif;
}

.header {

    padding: 18px;

    text-align: center;

    background: #090909;

    border-bottom: 1px solid #333;
}

.title {

    font-size: 30px;

    font-weight: 900;

    letter-spacing: 5px;
}

.subtitle {

    margin-top: 5px;

    color: #888;

    font-size: 12px;

    letter-spacing: 3px;
}

.status {

    margin-top: 12px;

    font-weight: bold;
}

.live {
    color: #55ff88;
}

.dead {
    color: #ff5555;
}

.tabs {

    display: flex;

    justify-content: center;

    gap: 4px;

    padding: 10px;

    background: #101010;

    border-bottom: 1px solid #292929;

    overflow-x: auto;
}

.tab {

    padding: 10px 18px;

    border: 1px solid #292929;

    color: #888;

    white-space: nowrap;
}

.tab.active {

    background: #1d1d1d;

    color: white;
}

.container {

    max-width: 1150px;

    margin: auto;

    padding: 15px;
}

.grid {

    display: grid;

    grid-template-columns:
        repeat(3, 1fr);

    gap: 10px;
}

.card {

    padding: 15px;

    min-height: 105px;

    background: rgba(15,15,15,.96);

    border: 1px solid #303030;
}

.label {

    color: #777;

    font-size: 11px;

    letter-spacing: 2px;

    text-transform: uppercase;
}

.value {

    margin-top: 9px;

    font-size: 25px;

    font-weight: bold;

    overflow-wrap: anywhere;
}

.signal {

    font-size: 34px;

    letter-spacing: 3px;
}

.analysis {

    grid-column: 1 / -1;

    min-height: 125px;
}

.analysisText {

    margin-top: 12px;

    font-size: 18px;
}

.small {

    color: #777;

    font-size: 12px;

    margin-top: 7px;
}

.metrics {

    grid-column: 1 / -1;
}

.metric-grid {

    display: grid;

    grid-template-columns:
        repeat(6, 1fr);

    gap: 8px;

    margin-top: 12px;
}

.metric {

    padding: 10px;

    background: #111;

    border: 1px solid #292929;
}

.metric .name {

    color: #777;

    font-size: 10px;
}

.metric .number {

    margin-top: 6px;

    font-weight: bold;
}


/* ========================================================
   CURRENCY MENU
   ======================================================== */

.currency-card {

    grid-column: 1 / -1;

    padding: 15px;

    background: #0c0c0c;

    border: 1px solid #343434;
}

.currency-header {

    display: flex;

    justify-content: space-between;

    align-items: center;

    gap: 10px;

    flex-wrap: wrap;
}

.currency-title {

    font-size: 16px;

    font-weight: bold;

    letter-spacing: 2px;
}

.currency-search {

    width: 100%;

    max-width: 300px;

    padding: 11px;

    border: 1px solid #444;

    background: #050505;

    color: white;

    outline: none;
}

.currency-list {

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 6px;

    margin-top: 12px;

    max-height: 310px;

    overflow-y: auto;

    padding-right: 3px;
}

.currency-button {

    padding: 10px 6px;

    border: 1px solid #292929;

    background: #111;

    color: #aaa;

    cursor: pointer;

    text-align: center;

    font-size: 12px;
}

.currency-button:hover {

    background: #222;

    color: white;
}

.currency-button.selected {

    background: #292929;

    color: white;

    border-color: #777;
}

.selected-currency {

    margin-top: 12px;

    font-size: 13px;

    color: #888;
}

.selected-currency strong {

    color: white;
}


/* ========================================================
   FEED
   ======================================================== */

.feedbox {

    grid-column: 1 / -1;

    padding: 14px;

    background: #0c0c0c;

    border: 1px solid #303030;
}


/* ========================================================
   MOBILE
   ======================================================== */

@media(max-width:850px) {

    .grid {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .metric-grid {

        grid-template-columns:
            repeat(3, 1fr);
    }

    .currency-list {

        grid-template-columns:
            repeat(2, 1fr);
    }
}

@media(max-width:500px) {

    .grid {

        grid-template-columns:
            1fr;
    }

    .metric-grid {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .currency-list {

        grid-template-columns:
            repeat(2, 1fr);
    }
}

</style>

</head>


<body>


<!-- ======================================================
     HEADER
     ====================================================== -->

<div class="header">

    <div class="title">
       
