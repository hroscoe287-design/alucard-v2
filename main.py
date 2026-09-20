import os
import io
import time
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from PIL import Image

app = Flask(__name__)

# ============================================================
# ALUCARD V2.1 — GOTHIC MARKET INTELLIGENCE
# COMPLETE SCREEN-FEED COMPATIBLE VERSION
# ============================================================

TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

STATE_LOCK = threading.Lock()

state = {
    "asset": "UNKNOWN",
    "price": 0.0,

    "signal": "WAIT",
    "confidence": 0,

    "entry": 0.0,
    "entry_window": 12,

    "countdown": 0,
    "countdown_status": "WAITING",

    "candles": 0,

    "feed": "WAITING",
    "screen": "WAITING",
    "image_received": False,

    "timeframe": "1m",
    "payout": 0,

    "analysis": "Waiting for usable market data.",

    "last_update": 0,
    "last_frame": 0,

    "signal_started": 0,
    "signal_expires": 0,

    # Indicator values supplied by the feed.
    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "rsi": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "cci": 0.0,
    "sar": 0.0,
    "supertrend": 0.0,
    "atr": 0.0,
    "bollinger_upper": 0.0,
    "bollinger_middle": 0.0,
    "bollinger_lower": 0.0,
}


# ============================================================
# POCKET OPTION ASSET MENU
# ============================================================

ASSETS = {
    "Currency": [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "USD/CHF",
        "USD/CAD",
        "AUD/USD",
        "NZD/USD",
        "EUR/GBP",
        "EUR/JPY",
        "GBP/JPY",
        "AUD/JPY",
        "AUD/CAD",
        "AUD/CHF",
        "AUD/NZD",
        "CAD/JPY",
        "CAD/CHF",
        "CHF/JPY",
        "EUR/CHF",
        "EUR/NZD",
        "GBP/AUD",
        "GBP/CHF",
        "NZD/JPY"
    ],

    "OTC Currency": [
        "EUR/USD OTC",
        "GBP/USD OTC",
        "USD/JPY OTC",
        "USD/CHF OTC",
        "USD/CAD OTC",
        "AUD/USD OTC",
        "NZD/USD OTC",
        "EUR/GBP OTC",
        "EUR/JPY OTC",
        "GBP/JPY OTC",
        "AUD/JPY OTC",
        "AUD/CAD OTC",
        "AUD/CHF OTC",
        "AUD/NZD OTC",
        "CAD/JPY OTC",
        "CAD/CHF OTC",
        "CHF/JPY OTC",
        "EUR/CHF OTC",
        "EUR/NZD OTC",
        "GBP/AUD OTC",
        "NZD/JPY OTC",
        "EUR/TRY OTC",
        "EUR/HUF OTC",
        "EUR/RUB OTC",
        "USD/RUB OTC",
        "USD/CNH OTC",
        "USD/INR OTC",
        "USD/IDR OTC",
        "USD/MYR OTC",
        "USD/SGD OTC",
        "USD/THB OTC",
        "USD/VND OTC",
        "USD/PKR OTC",
        "USD/PHP OTC",
        "USD/BDT OTC",
        "USD/EGP OTC",
        "USD/DZD OTC",
        "USD/CLP OTC",
        "USD/COP OTC",
        "USD/MXN OTC",
        "USD/BRL OTC",
        "USD/ARS OTC",
        "KES/USD OTC",
        "NGN/USD OTC",
        "ZAR/USD OTC",
        "YER/USD OTC",
        "TND/USD OTC",
        "MAD/USD OTC",
        "UAH/USD OTC",
        "LBP/USD OTC",
        "BHD/CNY OTC",
        "AED/CNY OTC",
        "SAR/CNY OTC",
        "QAR/CNY OTC",
        "OMR/CNY OTC",
        "JOD/CNY OTC"
    ],

    "Commodities": [
        "Gold",
        "Silver",
        "Brent Oil",
        "WTI Crude Oil",
        "Natural Gas",
        "Platinum spot",
        "Palladium spot"
    ],

    "OTC Commodities": [
        "Gold OTC",
        "Silver OTC",
        "Brent Oil OTC",
        "WTI Crude Oil OTC",
        "Natural Gas OTC",
        "Platinum spot OTC",
        "Palladium spot OTC"
    ],

    "Stocks": [
        "Apple",
        "Microsoft",
        "Amazon",
        "Tesla",
        "Intel",
        "Cisco",
        "Netflix",
        "Alibaba",
        "VISA",
        "American Express",
        "Boeing Company",
        "ExxonMobil",
        "McDonald's",
        "Johnson & Johnson",
        "Pfizer Inc",
        "FedEx",
        "Citigroup Inc",
        "GameStop Corp",
        "FACEBOOK INC",
        "Advanced Micro Devices",
        "Palantir Technologies",
        "Coinbase Global",
        "Marathon Digital Holdings"
    ],

    "OTC Stocks": [
        "Apple OTC",
        "Microsoft OTC",
        "Amazon OTC",
        "Tesla OTC",
        "Intel OTC",
        "Cisco OTC",
        "Netflix OTC",
        "Alibaba OTC",
        "VISA OTC",
        "American Express OTC",
        "Boeing Company OTC",
        "ExxonMobil OTC",
        "McDonald's OTC",
        "Johnson & Johnson OTC",
        "Pfizer Inc OTC",
        "FedEx OTC",
        "Citigroup Inc OTC",
        "GameStop Corp OTC",
        "FACEBOOK INC OTC",
        "Advanced Micro Devices OTC",
        "Palantir Technologies OTC",
        "Coinbase Global OTC",
        "Marathon Digital Holdings OTC",
        "VIX OTC"
    ],

    "Indices": [
        "US100",
        "SP500",
        "DJI30",
        "D30/EUR",
        "E35EUR",
        "E50EUR",
        "F40EUR",
        "100GBP",
        "JPN225",
        "AUS 200",
        "CAC 40",
        "HONG KONG 33"
    ],

    "OTC Indices": [
        "US100 OTC",
        "SP500 OTC",
        "DJI30 OTC",
        "D30EUR OTC",
        "E35EUR OTC",
        "E50EUR OTC",
        "F40EUR OTC",
        "100GBP OTC",
        "JPN225 OTC",
        "AUS 200 OTC"
    ],

    "Cryptocurrencies": [
        "Bitcoin",
        "Ethereum",
        "Litecoin",
        "Bitcoin ETF",
        "BCH/EUR",
        "BCH/GBP",
        "BCH/JPY",
        "BTC/GBP",
        "BTC/JPY",
        "Chainlink",
        "Dash",
        "BNB",
        "Solana",
        "Cardano",
        "TRON",
        "Toncoin",
        "Avalanche",
        "Dogecoin",
        "Polkadot",
        "Polygon"
    ],

    "OTC Crypto": [
        "Bitcoin OTC",
        "Ethereum OTC",
        "Litecoin OTC",
        "Bitcoin ETF OTC",
        "BNB OTC",
        "Solana OTC",
        "Cardano OTC",
        "TRON OTC",
        "Dogecoin OTC",
        "Polkadot OTC",
        "Polygon OTC",
        "Chainlink OTC",
        "Avalanche OTC"
    ]
}


TIMEFRAMES = {
    "5s": 5,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400
}


# ============================================================
# HELPERS
# ============================================================

def now():
    return time.time()


def clean_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def token_valid(req):
    if not TOKEN:
        return True

    supplied = (
        req.headers.get("X-RYU-TOKEN")
        or req.headers.get("X-ALUCARD-TOKEN")
        or req.args.get("token")
    )

    return supplied == TOKEN


def normalize_asset(asset):
    """
    Converts common Pocket Option naming formats into a
    readable dashboard name.
    """

    if not asset:
        return "UNKNOWN"

    text = str(asset).strip()

    replacements = {
        "EURUSD_otc": "EUR/USD OTC",
        "EURUSD OTC": "EUR/USD OTC",
        "GBPUSD_otc": "GBP/USD OTC",
        "GBPUSD OTC": "GBP/USD OTC",
        "USDJPY_otc": "USD/JPY OTC",
        "USDJPY OTC": "USD/JPY OTC",
        "USDCHF_otc": "USD/CHF OTC",
        "USDCHF OTC": "USD/CHF OTC",
        "USDCAD_otc": "USD/CAD OTC",
        "USDCAD OTC": "USD/CAD OTC",
        "AUDUSD_otc": "AUD/USD OTC",
        "AUDUSD OTC": "AUD/USD OTC",
        "NZDUSD_otc": "NZD/USD OTC",
        "NZDUSD OTC": "NZD/USD OTC",
        "EURGBP_otc": "EUR/GBP OTC",
        "EURGBP OTC": "EUR/GBP OTC",
        "EURJPY_otc": "EUR/JPY OTC",
        "EURJPY OTC": "EUR/JPY OTC",
        "GBPJPY_otc": "GBP/JPY OTC",
        "GBPJPY OTC": "GBP/JPY OTC",
        "AUDJPY_otc": "AUD/JPY OTC",
        "AUDJPY OTC": "AUD/JPY OTC",
    }

    if text in replacements:
        return replacements[text]

    # Normal forex symbols.
    compact = text.replace("/", "").replace("_otc", "").replace("_OTC", "")

    forex_map = {
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "USDCHF": "USD/CHF",
        "USDCAD": "USD/CAD",
        "AUDUSD": "AUD/USD",
        "NZDUSD": "NZD/USD",
        "EURGBP": "EUR/GBP",
        "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY",
        "AUDJPY": "AUD/JPY",
        "AUDCAD": "AUD/CAD",
        "AUDCHF": "AUD/CHF",
        "AUDNZD": "AUD/NZD",
        "CADJPY": "CAD/JPY",
        "CADCHF": "CAD/CHF",
        "CHFJPY": "CHF/JPY",
        "EURCHF": "EUR/CHF",
        "EURNZD": "EUR/NZD",
        "GBPAUD": "GBP/AUD",
        "GBPCHF": "GBP/CHF",
        "NZDJPY": "NZD/JPY"
    }

    if compact.upper() in forex_map:
        result = forex_map[compact.upper()]

        if "otc" in text.lower():
            result += " OTC"

        return result

    return text


def update_signal_timing():
    current = now()

    with STATE_LOCK:
        expires = float(
            state.get("signal_expires", 0) or 0
        )

        if expires > current:

            remaining = max(
                0,
                int(expires - current)
            )

            state["countdown"] = remaining
            state["countdown_status"] = "ENTRY OPEN"

        elif expires > 0:

            state["countdown"] = 0
            state["countdown_status"] = "EXPIRED"

            if state["signal"] in ("CALL", "PUT"):

                state["signal"] = "WAIT"

                state["analysis"] = (
                    "Entry window expired. "
                    "Waiting for next confirmed signal."
                )

        else:

            state["countdown"] = 0
            state["countdown_status"] = "WAITING"


def feed_is_alive():
    current = now()

    with STATE_LOCK:
        last = float(
            state.get("last_update", 0) or 0
        )

    return (
        last > 0
        and (current - last) <= 15
    )


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(data):
    """
    Uses supplied indicator values.

    The engine requires multiple confirmations rather than
    generating a signal from a screenshot alone.

    If an upstream feed already supplies CALL/PUT with a
    confidence value, that signal is preserved.

    If enough indicator values are supplied, ALUCARD can
    calculate a signal.
    """

    supplied_signal = str(
        data.get("signal", "")
    ).upper().strip()

    supplied_confidence = clean_int(
        data.get("confidence", 0)
    )

    # --------------------------------------------------------
    # Preserve a legitimate upstream signal.
    # --------------------------------------------------------

    if supplied_signal in ("CALL", "PUT"):

        return (
            supplied_signal,
            max(
                0,
                min(100, supplied_confidence)
            ),
            "Signal received from market feed."
        )

    # --------------------------------------------------------
    # Gather indicators.
    # --------------------------------------------------------

    price = clean_number(data.get("price"))

    ema9 = clean_number(data.get("ema9"))
    ema20 = clean_number(data.get("ema20"))
    ema50 = clean_number(data.get("ema50"))

    rsi = clean_number(data.get("rsi"))
    macd = clean_number(data.get("macd"))
    macd_signal = clean_number(
        data.get("macd_signal")
    )

    cci = clean_number(data.get("cci"))
    sar = clean_number(data.get("sar"))
    supertrend = clean_number(
        data.get("supertrend")
    )

    upper = clean_number(
        data.get("bollinger_upper")
    )

    middle = clean_number(
        data.get("bollinger_middle")
    )

    lower = clean_number(
        data.get("bollinger_lower")
    )

    # Need enough information to calculate anything.
    available = sum([
        price > 0,
        ema9 > 0,
        ema20 > 0,
        ema50 > 0,
        rsi > 0,
        macd != 0,
        macd_signal != 0,
        cci != 0,
        sar > 0,
        supertrend > 0,
        middle > 0
    ])

    if available < 4:

        return (
            "WAIT",
            0,
            "Waiting for enough market indicators."
        )

    call_score = 0
    put_score = 0
    total = 0

    # EMA trend.
    if ema9 > 0 and ema20 > 0:
        total += 1

        if ema9 > ema20:
            call_score += 1
        elif ema9 < ema20:
            put_score += 1

    if ema20 > 0 and ema50 > 0:
        total += 1

        if ema20 > ema50:
            call_score += 1
        elif ema20 < ema50:
            put_score += 1

    # RSI.
    if rsi > 0:
        total += 1

        if 52 <= rsi <= 70:
            call_score += 1
        elif 30 <= rsi <= 48:
            put_score += 1

    # MACD.
    if macd != 0 or macd_signal != 0:
        total += 1

        if macd > macd_signal:
            call_score += 1
        elif macd < macd_signal:
            put_score += 1

    # CCI.
    if cci != 0:
        total += 1

        if cci > 50:
            call_score += 1
        elif cci < -50:
            put_score += 1

    # Parabolic SAR.
    if price > 0 and sar > 0:
        total += 1

        if price > sar:
            call_score += 1
        elif price < sar:
            put_score += 1

    # Supertrend.
    if price > 0 and supertrend > 0:
        total += 1

        if price > supertrend:
            call_score += 1
        elif price < supertrend:
            put_score += 1

    # Bollinger position.
    if (
        price > 0
        and upper > middle > 0
        and lower > 0
    ):
        total += 1

        if price > middle:
            call_score += 1
        elif price < middle:
            put_score += 1

    if total <= 0:
        return (
            "WAIT",
            0,
            "Waiting for indicator confirmation."
        )

    call_percent = (
        call_score / total
    ) * 100

    put_percent = (
        put_score / total
    ) * 100

    # Require strong agreement.
    if call_percent >= 78 and call_score > put_score:

        return (
            "CALL",
            int(call_percent),
            "Multiple bullish indicators confirmed."
        )

    if put_percent >= 78 and put_score > call_score:

        return (
            "PUT",
            int(put_percent),
            "Multiple bearish indicators confirmed."
        )

    return (
        "WAIT",
        int(max(call_percent, put_percent)),
        "Indicators are not sufficiently aligned."
    )


# ============================================================
# API — STATE
# ============================================================

@app.route("/api/state", methods=["GET"])
def api_state():

    update_signal_timing()

    with STATE_LOCK:
        result = dict(state)

    result["feed_alive"] = feed_is_alive()

    result["server_time"] = (
        datetime.now(timezone.utc).isoformat()
    )

    if result["feed_alive"]:

        result["feed"] = "LIVE"

        # Screen can remain LIVE when a recent frame exists.
        if (
            result.get("last_frame", 0)
            and now() - float(result["last_frame"]) <= 15
        ):
            result["screen"] = "LIVE"

    else:

        if result["last_update"] == 0:

            result["feed"] = "WAITING"
            result["screen"] = "WAITING"

        else:

            result["feed"] = "DISCONNECTED"
            result["screen"] = "OFFLINE"

    return jsonify(result)


# ============================================================
# API — JSON MARKET FEED
# ============================================================

@app.route("/api/feed", methods=["POST"])
def api_feed():

    if not token_valid(request):

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

    asset = normalize_asset(
        data.get(
            "asset",
            state["asset"]
        )
    )

    price = clean_number(
        data.get(
            "price",
            state["price"]
        )
    )

    candles = max(
        0,
        clean_int(
            data.get(
                "candles",
                state["candles"]
            )
        )
    )

    timeframe = str(
        data.get(
            "timeframe",
            state["timeframe"]
        ) or "1m"
    )

    if timeframe not in TIMEFRAMES:
        timeframe = "1m"

    signal, confidence, signal_analysis = (
        calculate_signal(data)
    )

    entry = clean_number(
        data.get(
            "entry",
            price
        )
    )

    payout = clean_int(
        data.get(
            "payout",
            state["payout"]
        )
    )

    current = now()

    with STATE_LOCK:

        state["asset"] = asset
        state["price"] = price

        state["signal"] = signal
        state["confidence"] = confidence

        state["entry"] = entry

        state["candles"] = candles

        state["feed"] = "LIVE"
        state["screen"] = (
            "LIVE"
            if state.get("last_frame", 0)
            and current - float(
                state.get("last_frame", 0)
            ) <= 15
            else state.get("screen", "LIVE")
        )

        state["image_received"] = bool(
            state.get("last_frame", 0)
        )

        state["timeframe"] = timeframe

        state["payout"] = payout

        state["analysis"] = str(
            data.get(
                "analysis",
                signal_analysis
            )
        )

        # Store indicators.
        for key in (
            "ema9",
            "ema20",
            "ema50",
            "rsi",
            "macd",
            "macd_signal",
            "cci",
            "sar",
            "supertrend",
            "atr",
            "bollinger_upper",
            "bollinger_middle",
            "bollinger_lower"
        ):
            if key in data:
                state[key] = clean_number(
                    data.get(key)
                )

        state["last_update"] = current

        # ----------------------------------------------------
        # Start a fresh entry countdown only for a new
        # confirmed CALL or PUT.
        # ----------------------------------------------------

        if signal in ("CALL", "PUT"):

            state["signal_started"] = current

            state["signal_expires"] = (
                current
                + state["entry_window"]
            )

            state["countdown"] = (
                state["entry_window"]
            )

            state["countdown_status"] = (
                "ENTRY OPEN"
            )

        else:

            state["signal_started"] = 0
            state["signal_expires"] = 0
            state["countdown"] = 0
            state["countdown_status"] = (
                "WAITING"
            )

        result_state = dict(state)

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": result_state
    })


# ============================================================
# API — SCREENSHOT / IMAGE FEED
# ============================================================

@app.route("/api/frame", methods=["POST"])
def api_frame():

    if not token_valid(request):

        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    image_bytes = None

    # Multipart file.
    if "file" in request.files:

        image_bytes = (
            request.files["file"].read()
        )

    elif "image" in request.files:

        image_bytes = (
            request.files["image"].read()
        )

    # Raw image.
    elif request.data:

        image_bytes = request.data

    if not image_bytes:

        return jsonify({
            "ok": False,
            "error": "No image received"
        }), 400

    try:

        image = Image.open(
            io.BytesIO(image_bytes)
        )

        image.verify()

        # Re-open because verify() consumes the stream.
        image = Image.open(
            io.BytesIO(image_bytes)
        )

        width, height = image.size

    except Exception:

        return jsonify({
            "ok": False,
            "error": "Invalid image"
        }), 400

    current = now()

    with STATE_LOCK:

        state["image_received"] = True

        state["last_frame"] = current

        state["last_update"] = current

        state["feed"] = "LIVE"

        state["screen"] = "LIVE"

        # IMPORTANT:
        # Do NOT reset asset, price, signal, confidence,
        # entry, or candles when an image arrives.

        if state["analysis"] in (
            "Waiting for usable market data.",
            "Waiting for screen feed."
        ):

            state["analysis"] = (
                "Pocket Option screen received "
                f"({width}x{height}). "
                "Waiting for market-data feed."
            )

    return jsonify({
        "ok": True,
        "message": "Screen frame accepted",
        "width": width,
        "height": height,
        "image_received": True
    })


# ============================================================
# SCREENSHOT ALIAS
# ============================================================

@app.route("/api/screenshot", methods=["POST"])
def api_screenshot():
    return api_frame()


# ============================================================
# API — SETTINGS
# ============================================================

@app.route("/api/settings", methods=["GET"])
def get_settings():

    with STATE_LOCK:

        return jsonify({
            "entry_window": state["entry_window"],
            "timeframe": state["timeframe"],
            "timeframes": list(
                TIMEFRAMES.keys()
            )
        })


@app.route("/api/settings", methods=["POST"])
def set_settings():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):

        return jsonify({
            "ok": False,
            "error": "Invalid JSON"
        }), 400

    timeframe = str(
        data.get(
            "timeframe",
            state["timeframe"]
        )
    )

    if timeframe not in TIMEFRAMES:

        return jsonify({
            "ok": False,
            "error": "Invalid timeframe"
        }), 400

    with STATE_LOCK:

        state["timeframe"] = timeframe

    return jsonify({
        "ok": True,
        "timeframe": timeframe
    })


# ============================================================
# API — ASSETS
# ============================================================

@app.route("/api/assets", methods=["GET"])
def api_assets():

    return jsonify(ASSETS)


@app.route("/api/assets/<path:category>", methods=["GET"])
def api_asset_category(category):

    if category not in ASSETS:

        return jsonify({
            "ok": False,
            "error": "Unknown asset category"
        }), 404

    return jsonify({
        "ok": True,
        "category": category,
        "assets": ASSETS[category]
    })


# ============================================================
# API — HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():

    update_signal_timing()

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.1",
        "status": "online",
        "feed_alive": feed_is_alive(),
        "timestamp": (
            datetime.now(timezone.utc).isoformat()
        )
    })


# ============================================================
# API — RESET
# ============================================================

@app.route("/api/reset", methods=["POST"])
def reset_state():

    with STATE_LOCK:

        old_timeframe = state.get(
            "timeframe",
            "1m"
        )

        state.clear()

        state.update({

            "asset": "UNKNOWN",
            "price": 0.0,

            "signal": "WAIT",
            "confidence": 0,

            "entry": 0.0,
            "entry_window": 12,

            "countdown": 0,
            "countdown_status": "WAITING",

            "candles": 0,

            "feed": "WAITING",
            "screen": "WAITING",
            "image_received": False,

            "timeframe": old_timeframe,
            "payout": 0,

            "analysis": (
                "Waiting for usable market data."
            ),

            "last_update": 0,
            "last_frame": 0,

            "signal_started": 0,
            "signal_expires": 0,

            "ema9": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "rsi": 0.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "cci": 0.0,
            "sar": 0.0,
            "supertrend": 0.0,
            "atr": 0.0,
            "bollinger_upper": 0.0,
            "bollinger_middle": 0.0,
            "bollinger_lower": 0.0
        })

    return jsonify({
        "ok": True,
        "message": "ALUCARD state reset"
    })


# ============================================================
# DASHBOARD HTML
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>ALUCARD V2.1</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    background:
        radial-gradient(
            circle at top,
            #18351e 0%,
            #07100a 45%,
            #020403 100%
        );

    color: #d9ffe0;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    min-height: 100vh;
}

.header {

    padding:
        18px
        14px
        10px;

    text-align: center;

    border-bottom:
        1px solid #284d30;
}

.logo {

    font-size: 30px;

    font-weight: 900;

    letter-spacing: 5px;

    color: #d8ffdf;

    text-shadow:
        0 0 14px #39ff65;
}

.subtitle {

    margin-top: 5px;

    color: #78a981;

    font-size: 11px;

    letter-spacing: 3px;
}

.feed-status {

    display: inline-block;

    margin-top: 12px;

    padding:
        7px
        14px;

    border:
        1px solid #3d7a4b;

    border-radius: 20px;

    font-size: 12px;

    letter-spacing: 1px;
}

.live {

    color: #70ff8a;

    box-shadow:
        0 0 15px
        rgba(60,255,100,.2);
}

.dead {
    color: #ff6565;
}

.nav {

    display: flex;

    overflow-x: auto;

    border-bottom:
        1px solid #284d30;

    background:
        rgba(0,0,0,.35);
}

.nav button {

    flex: 1;

    min-width: 90px;

    padding: 14px 8px;

    background: transparent;

    border: 0;

    color: #7ea487;

    font-weight: bold;
}

.nav button.active {

    color: #8dff9f;

    border-bottom:
        2px solid #54ff73;
}

.page {

    max-width: 1100px;

    margin: auto;

    padding: 14px;
}

.grid {

    display: grid;

    grid-template-columns:
        repeat(
            2,
            minmax(0, 1fr)
        );

    gap: 10px;
}

.card {

    background:
        rgba(8,20,11,.86);

    border:
        1px solid #23492c;

    border-radius: 10px;

    padding: 15px;

    box-shadow:
        inset
        0 0 25px
        rgba(60,255,100,.025);
}

.label {

    color: #6e9878;

    font-size: 10px;

    letter-spacing: 2px;
}

.value {

    margin-top: 7px;

    font-size: 21px;

    font-weight: 800;

    word-break: break-word;
}

.call {
    color: #62ff7c;
}

.put {
    color: #ff6262;
}

.wait {
    color: #d9d9d9;
}

.countdown {

    font-size: 38px;

    font-weight: 900;

    color: #8dff9f;
}

.expired {
    color: #ff5555;
}

.entry-open {
    color: #6cff88;
}

.signal-panel {

    margin-top: 12px;

    padding: 20px;

    text-align: center;

    border:
        1px solid #2d6338;

    border-radius: 12px;

    background:
        linear-gradient(
            135deg,
            rgba(25,65,31,.8),
            rgba(3,9,5,.9)
        );
}

.signal {

    font-size: 42px;

    font-weight: 900;

    letter-spacing: 3px;
}

.confidence {

    margin-top: 8px;

    font-size: 16px;
}

.select-wrap {
    margin-top: 15px;
}

select {

    width: 100%;

    padding: 13px;

    background: #08130a;

    color: #d9ffe0;

    border:
        1px solid #315c39;

    border-radius: 7px;
}

.category {
    margin-top: 14px;
}

.category-title {

    margin-bottom: 7px;

    color: #8bb592;

    font-size: 11px;

    letter-spacing: 2px;
}

.asset-list {

    display: grid;

    grid-template-columns:
        repeat(
            2,
            1fr
        );

    gap: 6px;
}

.asset {

    padding: 9px;

    background: #09160b;

    border:
        1px solid #1c3b23;

    color: #b9d8bf;

    border-radius: 5px;

    font-size: 11px;

    cursor: pointer;

    transition: .15s;
}

.asset:hover {

    border-color: #5aff76;

    color: #7cff91;
}

.asset.selected {

    border-color: #5aff76;

    color: #7cff91;

    box-shadow:
        0 0 8px
        rgba(90,255,118,.2);
}

.small {

    font-size: 11px;

    color: #75947b;

    line-height: 1.5;
}

.hidden {
    display: none;
}

.asset-header {

    display: flex;

    justify-content: space-between;

    align-items: center;

    gap: 10px;

    margin-bottom: 12px;
}

.asset-search {

    width: 100%;

    padding: 12px;

    background: #08130a;

    color: #d9ffe0;

    border:
        1px solid #315c39;

    border-radius: 7px;

    outline: none;
}

.asset-search:focus {

    border-color:
        #5aff76;
}

@media (max-width: 600px) {

    .grid {

        grid-template-columns:
            1fr 1fr;
    }

    .logo {

        font-size: 25px;
    }

    .signal {

        font-size: 35px;
    }
}

</style>

</head>

<body>


<div class="header">

    <div class="logo">
        ALUCARD
    </div>

    <div class="subtitle">
        GOTHIC MARKET INTELLIGENCE — V2.1
    </div>

    <div id="feedStatus"
         class="feed-status">

        FEED: WAITING

    </div>

</div>


<div class="nav">

    <button
        class="active"
        onclick="showTab('signals', this)">

        Signals

    </button>

    <button
        onclick="showTab('trades', this)">

        Trades

    </button>

    <button
        onclick="showTab('performance', this)">

        Performance

    </button>

    <button
        onclick="showTab('settings', this)">

        Settings

    </button>

</div>


<div class="page">


<!-- ======================================================
     SIGNALS
     ====================================================== -->

<section id="signals">

    <div class="signal-panel">

        <div class="label">
            CURRENT SIGNAL
        </div>

        <div id="signal"
             class="signal wait">

            WAIT

        </div>

        <div class="confidence">

            Confidence:
            <strong id="confidence">
                0%
            </strong>

        </div>

        <div style="margin-top:14px">

            <div class="label">
                ENTRY WINDOW
            </div>

            <div id="countdown"
                 class="countdown">

                --

            </div>

            <div id="countdownStatus"
                 class="small">

                WAITING

            </div>

        </div>

    </div>


    <div class="grid"
         style="margin-top:12px">


        <div class="card">

            <div class="label">
                ASSET
            </div>

            <div id="asset"
                 class="value">

                UNKNOWN

            </div>

        </div>


        <div class="card">

            <div class="label">
                PRICE
            </div>

            <div id="price"
                 class="value">

                0.000000

            </div>

        </div>


        <div class="card">

            <div class="label">
                ENTRY
            </div>

            <div id="entry"
                 class="value">

                0.000000

            </div>

        </div>


        <div class="card">

            <div class="label">
                CANDLES
            </div>

            <div id="candles"
                 class="value">

                0

            </div>

        </div>


        <div class="card">

            <div class="label">
                TIMEFRAME
            </div>

            <div id="timeframe"
                 class="value">

                1m

            </div>

        </div>


        <div class="card">

            <div class="label">
                PAYOUT
            </div>

            <div id="payout"
                 class="value">

                --

            </div>

        </div>

    </div>


    <div class="card"
         style="margin-top:12px">

        <div class="label">
            SCREEN FEED
        </div>

        <div id="screen"
             class="value">

            WAITING

        </div>

        <p id="analysis"
           class="small">

            Waiting for usable market data.

        </p>

    </div>


    <!-- CURRENCY MENU ALSO VISIBLE ON SIGNAL PAGE -->

    <div class="card"
         style="margin-top:12px">

        <div class="asset-header">

            <div class="label">
                POCKET OPTION ASSETS
            </div>

        </div>

        <input
            id="assetSearchSignals"
            class="asset-search"
            type="search"
            placeholder="Search currency, OTC, crypto, stock..."
            oninput="filterAssets('assetSearchSignals','signalAssetMenu')">

        <div id="signalAssetMenu"></div>

    </div>

</section>


<!-- ======================================================
     TRADES
     ====================================================== -->

<section id="trades"
         class="hidden">

    <div class="card">

        <div class="label">
            TRADE WINDOW
        </div>

        <h2>
            Manual Trade Monitor
        </h2>

        <p class="small">

            ALUCARD displays the incoming signal and
            entry countdown. Confirm the market and
            platform details yourself before placing
            any trade.

        </p>

        <div class="grid">

            <div>

                <div class="label">
                    SIGNAL
                </div>

                <div id="tradeSignal"
                     class="value">

                    WAIT

                </div>

            </div>

            <div>

                <div class="label">
                    COUNTDOWN
                </div>

                <div id="tradeCountdown"
                     class="value">

                    --

                </div>

            </div>

        </div>

    </div>

</section>


<!-- ======================================================
     PERFORMANCE
     ====================================================== -->

<section id="performance"
         class="hidden">

    <div class="card">

        <div class="label">
            PERFORMANCE
        </div>

        <h2>
            Session Monitor
        </h2>

        <p class="small">

            No historical win/loss statistics are fabricated.
            This section reflects only data actually received
            by the dashboard.

        </p>

        <div class="grid">

            <div>

                <div class="label">
                    FEED
                </div>

                <div id="performanceFeed"
                     class="value">

                    WAITING

                </div>

            </div>

            <div>

                <div class="label">
                    CANDLES
                </div>

                <div id="performanceCandles"
                     class="value">

                    0

                </div>

            </div>

        </div>

    </div>

</section>


<!-- ======================================================
     SETTINGS
     ====================================================== -->

<section id="settings"
         class="hidden">


    <div class="card">

        <div class="label">
            TIMEFRAME
        </div>

        <div class="select-wrap">

            <select
                id="timeframeSelect"
                onchange="changeTimeframe()">

                <option value="5s">
                    5 seconds
                </option>

                <option value="15s">
                    15 seconds
                </option>

                <option value="30s">
                    30 seconds
                </option>

                <option value="1m">
                    1 minute
                </option>

                <option value="2m">
                    2 minutes
                </option>

                <option value="3m">
                    3 minutes
                </option>

                <option value="5m">
                    5 minutes
                </option>

                <option value="15m">
                    15 minutes
                </option>

                <option value="30m">
                    30 minutes
                </option>

                <option value="1h">
                    1 hour
                </option>

                <option value="4h">
                    4 hours
                </option>

                <option value="1d">
                    1 day
                </option>

            </select>

        </div>

    </div>


    <div class="card"
         style="margin-top:12px">

        <div class="label">
            POCKET OPTION ASSETS
        </div>

        <input
            id="assetSearchSettings"
            class="asset-search"
            type="search"
            placeholder="Search assets..."
            oninput="filterAssets('assetSearchSettings','assetMenu')">

        <div id="assetMenu"></div>

    </div>

</section>


</div>


<script>

let currentState = {};

let selectedAsset = "";


/* ========================================================
   TAB CONTROL
   ======================================================== */

function showTab(tab, button) {

    const sections = [
        "signals",
        "trades",
        "performance",
        "settings"
    ];

    sections.forEach(id => {

        document
            .getElementById(id)
            .classList
            .toggle(
                "hidden",
                id !== tab
            );

    });

    document
        .querySelectorAll(".nav button")
        .forEach(btn => {

            btn.classList.remove("active");

        });

    button.classList.add("active");
}


/* ========================================================
   SIGNAL COLOR
   ======================================================== */

function signalClass(signal) {

    if (signal === "CALL")
        return "call";

    if (signal === "PUT")
        return "put";

    return "wait";
}


/* ========================================================
   FORMAT ASSET
   ======================================================== */

function displayAsset(asset) {

    if (!asset)
        return "UNKNOWN";

    return asset;
}


/* ========================================================
   UPDATE UI
   ======================================================== */

function updateUI(data) {

    currentState = data || {};

    const signal =
        data.signal || "WAIT";

    const confidence =
        Number(
            data.confidence || 0
        );


    document
        .getElementById("asset")
        .textContent =
            displayAsset(
                selectedAsset ||
                data.asset
            );


    document
        .getElementById("price")
        .textContent =
            Number(
                data.price || 0
            ).toFixed(6);


    document
        .getElementById("entry")
        .textContent =
            Number(
                data.entry || 0
            ).toFixed(6);


    document
        .getElementById("candles")
        .textContent =
            data.candles || 0;


    document
        .getElementById("timeframe")
        .textContent =
            data.timeframe || "1m";


    document
        .getElementById("confidence")
        .textContent =
            confidence + "%";


    document
        .getElementById("payout")
        .textContent =
            Number(data.payout || 0) > 0
                ? data.payout + "%"
                : "--";


    document
        .getElementById("analysis")
        .textContent =
            data.analysis ||
            "Waiting for usable market data.";


    document
        .getElementById("screen")
        .textContent =
            data.screen || "WAITING";


    const signalElement =
        document.getElementById(
            "signal"
        );


    signalElement.textContent =
        signal;


    signalElement.className =
        "signal " +
        signalClass(signal);


    let countdown =
        Number(
            data.countdown || 0
        );


    const countdownElement =
        document.getElementById(
            "countdown"
        );


    const countdownStatus =
        document.getElementById(
            "countdownStatus"
        );


    countdownElement.textContent =
        countdown > 0
            ? countdown + "s"
            : "--";


    countdownStatus.textContent =
        data.countdown_status ||
        "WAITING";


    if (
        data.countdown_status ===
        "EXPIRED"
    ) {

        countdownElement.className =
            "countdown expired";

    } else {

        countdownElement.className =
            "countdown " +
            (
                countdown > 0
                    ? "entry-open"
                    : "expired"
            );
    }


    document
        .getElementById("tradeSignal")
        .textContent =
            signal;


    document
        .getElementById("tradeCountdown")
        .textContent =
            countdown > 0
                ? countdown + "s"
                : (
                    data.countdown_status ===
                    "WAITING"
                        ? "--"
                        : "EXPIRED"
                );


    document
        .getElementById("performanceFeed")
        .textContent =
            data.feed || "WAITING";


    document
        .getElementById("performanceCandles")
        .textContent =
            data.candles || 0;


    const feedStatus =
        document.getElementById(
            "feedStatus"
        );


    if (data.feed_alive) {

        feedStatus.textContent =
            "FEED: LIVE";

        feedStatus.className =
            "feed-status live";

    } else {

        feedStatus.textContent =
            "FEED: " +
            (
                data.feed ||
                "WAITING"
            );

        feedStatus.className =
            "feed-status dead";
    }


    const select =
        document.getElementById(
            "timeframeSelect"
        );


    if (
        data.timeframe &&
        select.value !== data.timeframe
    ) {

        select.value =
            data.timeframe;
    }


    highlightSelectedAsset();
}


/* ========================================================
   LOAD STATE
   ======================================================== */

async function loadState() {

    try {

        const response =
            await fetch(
                "/api/state",
                {
                    cache: "no-store"
                }
            );


        if (!response.ok)
            throw new Error(
                "State request failed"
            );


        const data =
            await response.json();


        updateUI(data);


    } catch (error) {

        const status =
            document.getElementById(
                "feedStatus"
            );


        status.textContent =
            "FEED: ERROR";

        status.className =
            "feed-status dead";
    }
}


/* ========================================================
   BUILD ASSET MENU
   ======================================================== */

function buildAssetMenu(
    targetId
) {

    fetch("/api/assets", {
        cache: "no-store"
    })

    .then(response => {

        if (!response.ok)
            throw new Error(
                "Asset request failed"
            );

        return response.json();

    })

    .then(assets => {

        const menu =
            document.getElementById(
                targetId
            );


        if (!menu)
            return;


        menu.innerHTML = "";


        Object.keys(assets)
            .forEach(category => {

                const wrapper =
                    document.createElement(
                        "div"
                    );

                wrapper.className =
                    "category";


                const title =
                    document.createElement(
                        "div"
                    );

                title.className =
                    "category-title";

                title.textContent =
                    category;


                wrapper.appendChild(
                    title
                );


                const list =
                    document.createElement(
                        "div"
                    );

                list.className =
                    "asset-list";


                assets[category]
                    .forEach(asset => {

                        const item =
                            document
                                .createElement(
                                    "div"
                                );


                        item.className =
                            "asset";


                        item.textContent =
                            asset;


                        item.dataset.asset =
                            asset.toLowerCase();


                        item.onclick =
                            function() {

                                selectAsset(
                                    asset
                                );

                            };


                        list.appendChild(
                            item
                        );

                    });


                wrapper.appendChild(
                    list
                );

                menu.appendChild(
                    wrapper
                );

            });


        highlightSelectedAsset();

    })

    .catch(error => {

        console.log(
            "Asset menu error:",
            error
        );

        const menu =
            document.getElementById(
                targetId
            );

        if (menu) {

            menu.innerHTML =
                '<div class="small">' +
                'Unable to load asset menu.' +
                '</div>';

        }

    });
}


/* ========================================================
   SELECT ASSET
   ======================================================== */

function selectAsset(asset) {

    selectedAsset = asset;


    document
        .getElementById("asset")
        .textContent =
            asset;


    highlightSelectedAsset();
}


/* ========================================================
   HIGHLIGHT SELECTED ASSET
   ======================================================== */

function highlightSelectedAsset() {

    document
        .querySelectorAll(".asset")
        .forEach(item => {

            if (
                selectedAsset &&
                item.textContent ===
                selectedAsset
            ) {

                item.classList.add(
                    "selected"
                );

            } else {

                item.classList.remove(
                    "selected"
                );

            }

        });
}


/* ========================================================
   ASSET SEARCH
   ======================================================== */

function filterAssets(
    searchId,
    menuId
) {

    const search =
        document.getElementById(
            searchId
        );


    const query =
        (
            search.value || ""
        )
        .toLowerCase()
        .trim();


    const menu =
        document.getElementById(
            menuId
        );


    if (!menu)
        return;


    menu
        .querySelectorAll(".asset")
        .forEach(item => {

            const name =
                item.dataset.asset ||
                item.textContent
                    .toLowerCase();


            item.style.display =
                !query ||
                name.includes(query)
                    ? ""
                    : "none";

        });


    menu
        .querySelectorAll(".category")
        .forEach(category => {

            const visible =
                Array.from(
                    category.querySelectorAll(
                        ".asset"
                    )
                )
                .some(
                    item =>
                        item.style.display !==
                        "none"
                );


            category.style.display =
                visible
                    ? ""
                    : "none";

        });
}


/* ========================================================
   CHANGE TIMEFRAME
   ======================================================== */

async function changeTimeframe() {

    const timeframe =
        document
            .getElementById(
                "timeframeSelect"
            )
            .value;


    try {

        const response =
            await fetch(
                "/api/settings",
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        timeframe:
                            timeframe
                    })

                }
            );


        if (!response.ok)
            throw new Error(
                "Settings update failed"
            );


        await loadState();


    } catch (error) {

        console.log(error);

    }
}


/* ========================================================
   INITIALIZATION
   ======================================================== */

buildAssetMenu(
    "assetMenu"
);

buildAssetMenu(
    "signalAssetMenu"
);

loadState();


/* ========================================================
   LIVE STATE REFRESH
   ======================================================== */

setInterval(
    loadState,
    1000
);

</script>

</body>

</html>
"""


# ============================================================
# MAIN DASHBOARD ROUTE
# ============================================================

@app.route("/", methods=["GET"])
def dashboard():

    return render_template_string(
        HTML
    )


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
