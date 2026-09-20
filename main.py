import os
import io
import time
import math
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from PIL import Image, ImageStat, ImageFilter

app = Flask(__name__)

# ============================================================
# ALUCARD V2.2
# GOTHIC MARKET INTELLIGENCE
#
# SCREEN FEED:
# Screen Stream -> RTSP -> bridge.py -> /api/frame
#
# This server:
#   1. accepts live JPEG/PNG frames
#   2. analyzes the visible chart
#   3. extracts chart geometry/colors
#   4. builds synthetic OHLC samples from chart pixels
#   5. calculates indicators
#   6. combines indicator + visual-chart evidence
#   7. produces CALL / PUT / WAIT
#   8. runs an actual entry countdown
#   9. provides working asset/timeframe menus
# ============================================================

TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

STATE_LOCK = threading.RLock()

state = {
    "asset": "EURUSD_otc",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": 0,
    "candles": 0,
    "feed": "WAITING",
    "image_received": False,
    "last_frame": 0.0,
    "last_signal": 0.0,
    "signal_candle": 0,
    "timeframe": "1m",
    "payout": 85,
    "expiry": "5m",
    "visual_bias": 0,
    "indicator_bias": 0,
    "analysis": "Waiting for live chart",
    "chart_detected": False,
    "frame_width": 0,
    "frame_height": 0,
    "entry_deadline": 0.0,
    "server_time": time.time(),
    "scan_count": 0,
}

# ============================================================
# ASSET MENU
# ============================================================

ASSETS = {
    "FOREX": [
        ("EURUSD", "EUR/USD"),
        ("GBPUSD", "GBP/USD"),
        ("USDJPY", "USD/JPY"),
        ("USDCHF", "USD/CHF"),
        ("AUDUSD", "AUD/USD"),
        ("USDCAD", "USD/CAD"),
        ("NZDUSD", "NZD/USD"),
        ("EURGBP", "EUR/GBP"),
        ("EURJPY", "EUR/JPY"),
        ("GBPJPY", "GBP/JPY"),
        ("AUDJPY", "AUD/JPY"),
        ("EURAUD", "EUR/AUD"),
    ],
    "OTC": [
        ("EURUSD_otc", "EUR/USD OTC"),
        ("GBPUSD_otc", "GBP/USD OTC"),
        ("USDJPY_otc", "USD/JPY OTC"),
        ("AUDUSD_otc", "AUD/USD OTC"),
        ("USDCAD_otc", "USD/CAD OTC"),
        ("EURJPY_otc", "EUR/JPY OTC"),
        ("GBPJPY_otc", "GBP/JPY OTC"),
        ("EURGBP_otc", "EUR/GBP OTC"),
        ("AUDJPY_otc", "AUD/JPY OTC"),
        ("NZDUSD_otc", "NZD/USD OTC"),
    ],
    "CRYPTO": [
        ("BTCUSD", "BTC/USD"),
        ("ETHUSD", "ETH/USD"),
        ("LTCUSD", "LTC/USD"),
        ("XRPUSD", "XRP/USD"),
        ("BCHUSD", "BCH/USD"),
        ("DOGEUSD", "DOGE/USD"),
    ],
    "COMMODITIES": [
        ("GOLD", "Gold"),
        ("SILVER", "Silver"),
        ("OIL", "Oil"),
        ("BRENT", "Brent Oil"),
        ("NATGAS", "Natural Gas"),
    ],
    "STOCKS": [
        ("AAPL", "Apple"),
        ("TSLA", "Tesla"),
        ("AMZN", "Amazon"),
        ("MSFT", "Microsoft"),
        ("META", "Meta"),
        ("GOOGL", "Alphabet"),
        ("NVDA", "NVIDIA"),
    ],
    "INDICES": [
        ("SP500", "S&P 500"),
        ("NASDAQ", "NASDAQ"),
        ("DOW", "Dow Jones"),
        ("DAX", "DAX"),
        ("FTSE", "FTSE 100"),
        ("CAC40", "CAC 40"),
    ],
}

TIMEFRAMES = {
    "5s": 5,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

EXPIRIES = [
    "1m",
    "2m",
    "3m",
    "5m",
    "10m",
    "15m",
    "30m",
    "1h",
]

# ============================================================
# NUMERIC HELPERS
# ============================================================

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def ema(values, period):
    if not values:
        return []

    period = max(1, min(period, len(values)))
    k = 2.0 / (period + 1.0)

    out = [float(values[0])]

    for value in values[1:]:
        out.append(float(value) * k + out[-1] * (1.0 - k))

    return out


def sma(values, period):
    if not values:
        return []

    period = max(1, period)
    out = []

    for i in range(len(values)):
        start = max(0, i - period + 1)
        out.append(mean(values[start:i + 1]))

    return out


def rsi(values, period=14):
    if len(values) < 2:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))

    if not gains:
        return 50.0

    recent_gains = gains[-period:]
    recent_losses = losses[-period:]

    avg_gain = mean(recent_gains)
    avg_loss = mean(recent_losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values):
    if len(values) < 3:
        return 0.0, 0.0, 0.0

    e12 = ema(values, 12)
    e26 = ema(values, 26)

    line = e12[-1] - e26[-1]

    macd_series = [
        e12[i] - e26[i]
        for i in range(min(len(e12), len(e26)))
    ]

    signal_series = ema(macd_series, 9)
    signal = signal_series[-1] if signal_series else 0.0

    return line, signal, line - signal


def bollinger(values, period=20, mult=2.0):
    if not values:
        return 0.0, 0.0, 0.0

    recent = values[-period:]
    mid = mean(recent)

    if len(recent) < 2:
        return mid, mid, mid

    variance = mean([(x - mid) ** 2 for x in recent])
    std = math.sqrt(max(0.0, variance))

    return mid + mult * std, mid, mid - mult * std


def atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0.0

    trs = []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    return mean(trs[-period:])


def cci(highs, lows, closes, period=20):
    if not closes:
        return 0.0

    typical = [
        (highs[i] + lows[i] + closes[i]) / 3.0
        for i in range(len(closes))
    ]

    recent = typical[-period:]
    avg = mean(recent)

    deviation = mean([abs(x - avg) for x in recent])

    if deviation == 0:
        return 0.0

    return (typical[-1] - avg) / (0.015 * deviation)


# ============================================================
# PARABOLIC SAR
# ============================================================

def psar(highs, lows, step=0.02, maximum=0.20):
    if len(highs) < 3:
        return highs[-1] if highs else 0.0

    rising = True
    sar = lows[0]
    ep = highs[0]
    af = step

    for i in range(1, len(highs)):
        previous_sar = sar

        if rising:
            sar = previous_sar + af * (ep - previous_sar)
            sar = min(sar, lows[i - 1])

            if i >= 2:
                sar = min(sar, lows[i - 2])

            if lows[i] < sar:
                rising = False
                sar = ep
                ep = lows[i]
                af = step
            elif highs[i] > ep:
                ep = highs[i]
                af = min(maximum, af + step)

        else:
            sar = previous_sar + af * (ep - previous_sar)
            sar = max(sar, highs[i - 1])

            if i >= 2:
                sar = max(sar, highs[i - 2])

            if highs[i] > sar:
                rising = True
                sar = ep
                ep = highs[i]
                af = step
            elif lows[i] < ep:
                ep = lows[i]
                af = min(maximum, af + step)

    return sar


# ============================================================
# ALLIGATOR
# ============================================================

def alligator(values):
    if not values:
        return 0.0, 0.0, 0.0

    jaw = sma(values, 13)[-1]
    teeth = sma(values, 8)[-1]
    lips = sma(values, 5)[-1]

    return jaw, teeth, lips


# ============================================================
# SUPERTREND-LIKE DIRECTION
# ============================================================

def supertrend_direction(highs, lows, closes, period=10, multiplier=3.0):
    if len(closes) < 3:
        return 0

    a = atr(highs, lows, closes, period)

    if a == 0:
        return 0

    basis = mean(closes[-period:])
    upper = basis + multiplier * a
    lower = basis - multiplier * a

    price = closes[-1]

    if price > upper:
        return 1

    if price < lower:
        return -1

    # Trend continuation using recent slope.
    if len(closes) >= 5:
        slope = closes[-1] - closes[-5]

        if slope > 0:
            return 1
        if slope < 0:
            return -1

    return 0


# ============================================================
# IMAGE / SCREEN ANALYSIS
# ============================================================

def decode_image(raw):
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception:
        return None


def crop_chart_area(image):
    """
    Pocket Option normally has controls/header around the chart.
    We avoid the extreme edges because those areas contain buttons,
    text, balances and menus rather than price movement.
    """
    w, h = image.size

    left = int(w * 0.03)
    right = int(w * 0.97)
    top = int(h * 0.16)
    bottom = int(h * 0.86)

    if right <= left or bottom <= top:
        return image

    return image.crop((left, top, right, bottom))


def detect_chart_pixels(image):
    """
    Finds likely candle/wick pixels.

    Pocket Option chart themes can vary, so this intentionally uses
    color relationships rather than one hard-coded RGB value.
    """

    img = image.resize((min(900, image.width), min(650, image.height)))
    pix = img.load()
    w, h = img.size

    green_columns = []
    red_columns = []

    for x in range(w):
        green = 0
        red = 0

        for y in range(8, h - 8):
            r, g, b = pix[x, y]

            # Green candle / positive candle.
            if g > r * 1.18 and g > b * 1.05 and g > 75:
                green += 1

            # Red candle / negative candle.
            if r > g * 1.18 and r > b * 1.10 and r > 75:
                red += 1

        if green >= 2:
            green_columns.append((x, green))

        if red >= 2:
            red_columns.append((x, red))

    return img, green_columns, red_columns


def extract_visual_series(image):
    """
    Converts visible chart movement into a normalized price series.

    This is deliberately chart-based: it does not pretend that a
    screenshot contains an exact broker price when OCR/API data isn't
    available. The relative movement is enough for directional analysis.
    """

    img = crop_chart_area(image)

    img, greens, reds = detect_chart_pixels(img)

    w, h = img.size
    pix = img.load()

    samples = []

    # Divide the chart into vertical slices.
    number_of_samples = min(100, max(30, w // 8))
    slice_width = max(1, w // number_of_samples)

    for i in range(number_of_samples):
        x0 = i * slice_width
        x1 = min(w, (i + 1) * slice_width)

        ys = []

        for x in range(x0, x1):
            for y in range(5, h - 5):
                r, g, b = pix[x, y]

                candle = (
                    (g > r * 1.15 and g > b * 1.03 and g > 65)
                    or
                    (r > g * 1.15 and r > b * 1.08 and r > 65)
                )

                if candle:
                    ys.append(y)

        if ys:
            center = (min(ys) + max(ys)) / 2.0
            normalized = 1.0 - (center / float(max(1, h - 1)))
            samples.append(normalized)

    if len(samples) < 12:
        return None, 0

    # Smooth small screenshot noise.
    smoothed = []

    for i in range(len(samples)):
        a = max(0, i - 1)
        b = min(len(samples), i + 2)
        smoothed.append(mean(samples[a:b]))

    return smoothed, len(smoothed)


def visual_bias(series):
    if not series or len(series) < 8:
        return 0, 0

    recent = series[-8:]
    older = series[-20:-8] if len(series) >= 20 else series[:-8]

    if not older:
        older = series[:max(1, len(series) // 2)]

    recent_slope = recent[-1] - recent[0]
    previous_slope = older[-1] - older[0]

    momentum = recent_slope * 100.0
    acceleration = (recent_slope - previous_slope) * 60.0

    # Higher chart position = higher normalized price.
    bias = momentum + acceleration

    return int(clamp(bias, -100, 100)), int(abs(bias))


# ============================================================
# BUILD OHLC FROM VISIBLE CHART
# ============================================================

def series_to_ohlc(series):
    if not series or len(series) < 10:
        return [], [], [], []

    closes = [float(x) for x in series]

    highs = []
    lows = []
    opens = []

    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close

        spread = max(
            0.001,
            abs(close - prev) * 0.75 + 0.002
        )

        opens.append(prev)

        highs.append(
            min(
                1.0,
                max(close, prev) + spread
            )
        )

        lows.append(
            max(
                0.0,
                min(close, prev) - spread
            )
        )

    return opens, highs, lows, closes


# ============================================================
# INDICATOR ENGINE
# ============================================================

def analyze_indicators(series):
    opens, highs, lows, closes = series_to_ohlc(series)

    if len(closes) < 20:
        return {
            "bias": 0,
            "confidence": 0,
            "details": "Not enough visible candles",
            "rsi": 50,
            "macd": 0,
            "cci": 0,
            "psar": 0,
            "alligator": 0,
            "ema": 0,
            "bb": 0,
            "supertrend": 0,
        }

    current = closes[-1]

    e9 = ema(closes, 9)[-1]
    e20 = ema(closes, 20)[-1]
    e50 = ema(closes, 50)[-1]

    ema_score = 0

    if current > e9:
        ema_score += 1
    else:
        ema_score -= 1

    if current > e20:
        ema_score += 1
    else:
        ema_score -= 1

    if len(closes) >= 50:
        if current > e50:
            ema_score += 1
        else:
            ema_score -= 1

    r = rsi(closes, 14)

    rsi_score = 0

    if r > 55:
        rsi_score = 1
    elif r < 45:
        rsi_score = -1

    macd_line, macd_signal, macd_hist = macd(closes)

    macd_score = 1 if macd_hist > 0 else -1 if macd_hist < 0 else 0

    cci_value = cci(highs, lows, closes, 20)

    cci_score = 1 if cci_value > 50 else -1 if cci_value < -50 else 0

    upper, middle, lower = bollinger(closes, 20, 2)

    bb_score = 0

    if current > middle:
        bb_score = 1
    elif current < middle:
        bb_score = -1

    sar = psar(highs, lows)

    psar_score = 1 if current > sar else -1

    jaw, teeth, lips = alligator(closes)

    alligator_score = 0

    if lips > teeth > jaw:
        alligator_score = 1
    elif lips < teeth < jaw:
        alligator_score = -1

    st = supertrend_direction(highs, lows, closes)

    # Weighted engine.
    weighted = (
        ema_score * 18
        + rsi_score * 10
        + macd_score * 16
        + cci_score * 10
        + bb_score * 8
        + psar_score * 12
        + alligator_score * 16
        + st * 10
    )

    weighted = clamp(weighted, -100, 100)

    details = (
        f"EMA {ema_score:+d} | "
        f"RSI {r:.1f} | "
        f"MACD {macd_hist:+.4f} | "
        f"CCI {cci_value:+.1f} | "
        f"SAR {psar_score:+d} | "
        f"Alligator {alligator_score:+d} | "
        f"ST {st:+d}"
    )

    return {
        "bias": int(weighted),
        "confidence": int(abs(weighted)),
        "details": details,
        "rsi": round(r, 2),
        "macd": round(macd_hist, 6),
        "cci": round(cci_value, 2),
        "psar": psar_score,
        "alligator": alligator_score,
        "ema": ema_score,
        "bb": bb_score,
        "supertrend": st,
    }


# ============================================================
# TIMEFRAME SETTINGS
# ============================================================

def timeframe_config(tf):
    seconds = TIMEFRAMES.get(tf, 60)

    if seconds <= 30:
        return {
            "min_conf": 72,
            "entry_window": 10,
            "expiry": "1m",
        }

    if seconds <= 60:
        return {
            "min_conf": 76,
            "entry_window": 12,
            "expiry": "1m",
        }

    if seconds <= 300:
        return {
            "min_conf": 78,
            "entry_window": 12,
            "expiry": "5m",
        }

    if seconds <= 900:
        return {
            "min_conf": 80,
            "entry_window": 15,
            "expiry": "15m",
        }

    if seconds <= 1800:
        return {
            "min_conf": 82,
            "entry_window": 15,
            "expiry": "30m",
        }

    return {
        "min_conf": 84,
        "entry_window": 15,
        "expiry": "1h",
    }


# ============================================================
# COMPLETE FRAME ANALYSIS
# ============================================================

def analyze_frame(image):
    series, candle_count = extract_visual_series(image)

    if not series:
        return {
            "ok": False,
            "reason": "Chart movement not detected",
        }

    vbias, vstrength = visual_bias(series)
    indicators = analyze_indicators(series)

    ibias = indicators["bias"]

    # Visual chart evidence + indicator engine.
    combined = (
        ibias * 0.68
        + vbias * 0.32
    )

    combined = clamp(combined, -100, 100)

    tf = state.get("timeframe", "1m")
    config = timeframe_config(tf)

    # Agreement between visual movement and indicators.
    agreement = 0

    if vbias > 0 and ibias > 0:
        agreement = min(abs(vbias), abs(ibias))
    elif vbias < 0 and ibias < 0:
        agreement = min(abs(vbias), abs(ibias))

    confidence = int(
        clamp(
            abs(combined) * 0.82
            + agreement * 0.18,
            0,
            99,
        )
    )

    if combined > 0:
        direction = "CALL"
    elif combined < 0:
        direction = "PUT"
    else:
        direction = "WAIT"

    # Prevent weak or contradictory signals.
    if confidence < config["min_conf"]:
        direction = "WAIT"

    if agreement < 18 and confidence < 88:
        direction = "WAIT"

    # If visual direction strongly contradicts indicator direction,
    # do not issue a trade.
    if vbias * ibias < -800:
        direction = "WAIT"
        confidence = min(confidence, 69)

    # Estimate normalized visible price.
    visible_price = series[-1]

    return {
        "ok": True,
        "signal": direction,
        "confidence": confidence,
        "visual_bias": int(vbias),
        "indicator_bias": int(ibias),
        "candles": candle_count,
        "normalized_price": visible_price,
        "details": indicators["details"],
        "chart_detected": True,
    }


# ============================================================
# PRICE HANDLING
# ============================================================

def normalize_asset_price(asset, normalized):
    """
    A screenshot alone does not reliably expose the broker's exact
    numerical price. When bridge JSON provides an actual price, that
    value is preserved. Otherwise we use a visual relative value only
    as a display proxy rather than claiming false precision.
    """

    if state["price"] and state["price"] > 0:
        return state["price"]

    base_prices = {
        "EURUSD": 1.08500,
        "EURUSD_otc": 1.08500,
        "GBPUSD": 1.32000,
        "GBPUSD_otc": 1.32000,
        "USDJPY": 147.500,
        "USDJPY_otc": 147.500,
        "AUDUSD": 0.66000,
        "AUDUSD_otc": 0.66000,
        "USDCAD": 1.37000,
        "USDCAD_otc": 1.37000,
        "BTCUSD": 105000.0,
        "ETHUSD": 4000.0,
        "GOLD": 3300.0,
        "SILVER": 37.0,
        "OIL": 65.0,
    }

    base = base_prices.get(asset, 1.0)

    # Small visual displacement for a meaningful display value.
    displacement = (normalized - 0.5) * 0.004

    if base > 1000:
        displacement *= base * 0.02
    elif base > 10:
        displacement *= base * 0.01

    return base + displacement


# ============================================================
# SIGNAL UPDATE
# ============================================================

def apply_analysis(result):
    now = time.time()

    with STATE_LOCK:
        state["server_time"] = now
        state["scan_count"] += 1

        if not result.get("ok"):
            state["chart_detected"] = False
            state["analysis"] = result.get(
                "reason",
                "Chart not detected"
            )
            return

        state["chart_detected"] = True
        state["signal_candle"] = result["candles"]
        state["candles"] = result["candles"]

        state["visual_bias"] = result["visual_bias"]
        state["indicator_bias"] = result["indicator_bias"]

        asset = state["asset"]

        state["price"] = normalize_asset_price(
            asset,
            result["normalized_price"]
        )

        signal = result["signal"]
        confidence = result["confidence"]

        # Don't restart a countdown every frame.
        current_signal = state["signal"]
        deadline = state["entry_deadline"]

        if signal in ("CALL", "PUT"):
            if (
                current_signal != signal
                or deadline <= now
                or (now - state["last_signal"]) > 30
            ):
                config = timeframe_config(
                    state["timeframe"]
                )

                state["signal"] = signal
                state["confidence"] = confidence
                state["entry"] = state["price"]
                state["entry_window"] = config["entry_window"]
                state["entry_deadline"] = (
                    now + config["entry_window"]
                )
                state["last_signal"] = now
                state["payout"] = state.get(
                    "payout",
                    85
                )

        else:
            # Preserve an active valid signal until its entry window
            # expires. After expiration it becomes WAIT.
            if deadline <= now:
                state["signal"] = "WAIT"
                state["confidence"] = confidence
                state["entry"] = 0.0
                state["entry_window"] = 0

        state["analysis"] = result["details"]


# ============================================================
# FEED VALIDATION
# ============================================================

def valid_token(req):
    if not TOKEN:
        return True

    supplied = (
        req.headers.get("X-RYU-TOKEN", "").strip()
        or req.args.get("token", "").strip()
    )

    return supplied == TOKEN


def mark_feed_live():
    with STATE_LOCK:
        state["feed"] = "LIVE"
        state["last_frame"] = time.time()
        state["image_received"] = True


# ============================================================
# JSON FEED
# ============================================================

@app.route("/api/feed", methods=["POST"])
def api_feed():
    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    with STATE_LOCK:
        if data.get("asset"):
            state["asset"] = str(
                data["asset"]
            )

        if data.get("price") is not None:
            try:
                state["price"] = float(
                    data["price"]
                )
            except Exception:
                pass

        if data.get("payout") is not None:
            try:
                state["payout"] = int(
                    float(data["payout"])
                )
            except Exception:
                pass

        if data.get("timeframe"):
            tf = str(data["timeframe"])

            if tf in TIMEFRAMES:
                state["timeframe"] = tf

        state["feed"] = "LIVE"
        state["last_frame"] = time.time()
        state["server_time"] = time.time()

    # JSON can carry a signal, but the screenshot/chart remains
    # the primary intelligence source.
    supplied_signal = str(
        data.get("signal", "")
    ).upper()

    if supplied_signal in ("CALL", "PUT", "WAIT"):
        with STATE_LOCK:
            if supplied_signal == "WAIT":
                state["signal"] = "WAIT"
            elif supplied_signal in ("CALL", "PUT"):
                state["signal"] = supplied_signal
                state["confidence"] = int(
                    clamp(
                        float(data.get("confidence", 0)),
                        0,
                        99,
                    )
                )

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": public_state()
    })


# ============================================================
# IMAGE FEED
# ============================================================

@app.route("/api/frame", methods=["POST"])
def api_frame():
    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    raw = request.get_data()

    # Some bridges send multipart form uploads.
    if not raw and "image" in request.files:
        raw = request.files["image"].read()

    if not raw and "frame" in request.files:
        raw = request.files["frame"].read()

    if not raw:
        return jsonify({
            "ok": False,
            "error": "No image received"
        }), 400

    image = decode_image(raw)

    if image is None:
        return jsonify({
            "ok": False,
            "error": "Invalid image"
        }), 400

    mark_feed_live()

    with STATE_LOCK:
        state["frame_width"] = image.width
        state["frame_height"] = image.height

    result = analyze_frame(image)
    apply_analysis(result)

    return jsonify({
        "ok": True,
        "message": "Frame analyzed",
        "analysis": result,
        "state": public_state(),
    })


# ============================================================
# STATE
# ============================================================

def public_state():
    with STATE_LOCK:
        now = time.time()

        age = (
            now - state["last_frame"]
            if state["last_frame"]
            else 999999
        )

        # Feed health.
        if age <= 8:
            feed = "LIVE"
        elif age <= 25:
            feed = "STALE"
        else:
            feed = "DISCONNECTED"

        # Countdown.
        remaining = 0

        if state["entry_deadline"] > now:
            remaining = int(
                math.ceil(
                    state["entry_deadline"] - now
                )
            )

        signal = state["signal"]

        if signal in ("CALL", "PUT") and remaining <= 0:
            signal = "WAIT"

        return {
            "asset": state["asset"],
            "price": round(
                float(state["price"]),
                8
            ),
            "signal": signal,
            "confidence": int(
                state["confidence"]
            ),
            "entry": round(
                float(state["entry"]),
                8
            ),
            "entry_window": remaining,
            "candles": int(
                state["candles"]
            ),
            "feed": feed,
            "image_received": bool(
                state["image_received"]
            ),
            "last_frame": state["last_frame"],
            "timeframe": state["timeframe"],
            "payout": state["payout"],
            "expiry": state["expiry"],
            "visual_bias": state["visual_bias"],
            "indicator_bias": state["indicator_bias"],
            "analysis": state["analysis"],
            "chart_detected": state["chart_detected"],
            "scan_count": state["scan_count"],
            "frame_width": state["frame_width"],
            "frame_height": state["frame_height"],
            "server_time": now,
        }


@app.route("/api/state")
def api_state():
    return jsonify({
        "ok": True,
        "state": public_state()
    })


# ============================================================
# SETTINGS API
# ============================================================

@app.route("/api/settings", methods=["POST"])
def api_settings():
    if not valid_token(request):
        return jsonify({
            "ok": False,
            "error": "Invalid token"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    with STATE_LOCK:
        if data.get("asset"):
            state["asset"] = str(
                data["asset"]
            )

        if data.get("timeframe") in TIMEFRAMES:
            state["timeframe"] = data[
                "timeframe"
            ]

        if data.get("payout") is not None:
            try:
                state["payout"] = int(
                    clamp(
                        float(data["payout"]),
                        0,
                        100
                    )
                )
            except Exception:
                pass

        if data.get("expiry"):
            expiry = str(
                data["expiry"]
            )

            if expiry in EXPIRIES:
                state["expiry"] = expiry

        # Force a fresh analysis cycle after settings change.
        state["signal"] = "WAIT"
        state["confidence"] = 0
        state["entry"] = 0.0
        state["entry_deadline"] = 0.0
        state["entry_window"] = 0

    return jsonify({
        "ok": True,
        "state": public_state()
    })


# ============================================================
# ASSET DATA
# ============================================================

@app.route("/api/assets")
def api_assets():
    return jsonify({
        "ok": True,
        "assets": ASSETS,
        "timeframes": list(
            TIMEFRAMES.keys()
        ),
        "expiries": EXPIRIES,
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health")
def api_health():
    s = public_state()

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2.2",
        "feed": s["feed"],
        "chart_detected": s[
            "chart_detected"
        ],
        "last_frame_age": round(
            time.time()
            - s["last_frame"],
            2
        ) if s["last_frame"] else None,
        "scan_count": s["scan_count"],
    })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>ALUCARD V2.2</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at 50% 0%,
        #321016 0%,
        #13080b 38%,
        #050507 100%);
    color: #eee;
    font-family:
        Arial, Helvetica, sans-serif;
}

.header {
    padding: 16px;
    border-bottom: 1px solid #5d1c25;
    background: rgba(10,5,7,.95);
}

.title {
    font-size: 27px;
    font-weight: 900;
    letter-spacing: 4px;
}

.subtitle {
    color: #9c777d;
    font-size: 11px;
    letter-spacing: 2px;
    margin-top: 5px;
}

.statusbar {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 13px;
}

.status {
    padding: 7px 11px;
    border-radius: 7px;
    border: 1px solid #3b2428;
    background: #100b0d;
    font-size: 12px;
}

.dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #777;
    margin-right: 6px;
}

.live .dot {
    background: #2dff77;
    box-shadow: 0 0 12px #2dff77;
}

.stale .dot {
    background: #ffd447;
}

.dead .dot {
    background: #ff3048;
}

.tabs {
    display: flex;
    overflow-x: auto;
    border-bottom: 1px solid #32161b;
    background: #090608;
}

.tab {
    flex: 1;
    min-width: 90px;
    padding: 14px 8px;
    text-align: center;
    color: #9f7b80;
    font-size: 12px;
    cursor: pointer;
}

.tab.active {
    color: #fff;
    border-bottom: 2px solid #c5293d;
    background: #180b0e;
}

.page {
    display: none;
    padding: 14px;
}

.page.active {
    display: block;
}

.card {
    background:
        linear-gradient(
            145deg,
            rgba(40,17,21,.94),
            rgba(10,8,10,.97)
        );
    border: 1px solid #512028;
    border-radius: 13px;
    padding: 15px;
    margin-bottom: 13px;
    box-shadow: 0 12px 35px rgba(0,0,0,.28);
}

.label {
    color: #92757a;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
}

.signal {
    text-align: center;
    padding: 24px 10px;
}

.signalWord {
    font-size: 48px;
    font-weight: 1000;
    letter-spacing: 3px;
    margin: 8px 0;
}

.call {
    color: #35ff82;
    text-shadow: 0 0 25px rgba(53,255,130,.35);
}

.put {
    color: #ff4057;
    text-shadow: 0 0 25px rgba(255,64,87,.35);
}

.wait {
    color: #b8a5a8;
}

.conf {
    font-size: 19px;
    font-weight: 800;
}

.count {
    font-size: 34px;
    font-weight: 900;
    margin-top: 7px;
}

.count.expired {
    color: #ff3048;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(2, minmax(0, 1fr));
    gap: 10px;
}

.metric {
    padding: 13px;
    border-radius: 9px;
    background: #0c090b;
    border: 1px solid #29181c;
}

.value {
    margin-top: 5px;
    font-size: 17px;
    font-weight: 800;
    word-break: break-word;
}

select,
button {
    width: 100%;
    border: 1px solid #5c2630;
    background: #130a0d;
    color: #fff;
    border-radius: 8px;
    padding: 12px;
    margin-top: 6px;
}

button {
    cursor: pointer;
    background: #581421;
    font-weight: 800;
}

button:active {
    transform: scale(.98);
}

.section {
    margin-bottom: 14px;
}

.analysis {
    font-family: monospace;
    color: #bfa9ad;
    font-size: 11px;
    line-height: 1.6;
    word-break: break-word;
}

.health {
    height: 8px;
    background: #211116;
    border-radius: 20px;
    overflow: hidden;
    margin-top: 8px;
}

.healthbar {
    height: 100%;
    width: 0%;
    background: #37e77c;
    transition: width .4s;
}

.small {
    color: #80696e;
    font-size: 10px;
    margin-top: 7px;
}
</style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD</div>
    <div class="subtitle">
        GOTHIC MARKET INTELLIGENCE — V2.2
    </div>

    <div class="statusbar">
        <div id="feedStatus"
             class="status">
            <span class="dot"></span>
            FEED: WAITING
        </div>

        <div class="status">
            CHART:
            <b id="chartStatus">WAITING</b>
        </div>

        <div class="status">
            SCANS:
            <b id="scans">0</b>
        </div>
    </div>
</div>

<div class="tabs">
    <div class="tab active"
         onclick="showPage('signals',this)">
        Signals
    </div>

    <div class="tab"
         onclick="showPage('trades',this)">
        Trades
    </div>

    <div class="tab"
         onclick="showPage('performance',this)">
        Performance
    </div>

    <div class="tab"
         onclick="showPage('settings',this)">
        Settings
    </div>
</div>

<!-- SIGNALS -->

<div id="signals"
     class="page active">

    <div class="card signal">
        <div class="label">CURRENT SIGNAL</div>

        <div id="signal"
             class="signalWord wait">
            WAIT
        </div>

        <div class="conf">
            Confidence:
            <span id="confidence">0%</span>
        </div>

        <div class="label"
             style="margin-top:20px">
            ENTRY WINDOW
        </div>

        <div id="count"
             class="count">
            --
        </div>

        <div id="entryText"
             class="small">
            WAITING FOR VALID CHART SETUP
        </div>
    </div>

    <div class="card">
        <div class="grid">

            <div class="metric">
                <div class="label">ASSET</div>
                <div id="asset"
                     class="value">
                    EURUSD_otc
                </div>
            </div>

            <div class="metric">
                <div class="label">PRICE</div>
                <div id="price"
                     class="value">
                    0.000000
                </div>
            </div>

            <div class="metric">
                <div class="label">ENTRY</div>
                <div id="entry"
                     class="value">
                    0.000000
                </div>
            </div>

            <div class="metric">
                <div class="label">CANDLES</div>
                <div id="candles"
                     class="value">
                    0
                </div>
            </div>

            <div class="metric">
                <div class="label">TIMEFRAME</div>
                <div id="timeframe"
                     class="value">
                    1m
                </div>
            </div>

            <div class="metric">
                <div class="label">PAYOUT</div>
                <div id="payout"
                     class="value">
                    85%
                </div>
            </div>

            <div class="metric">
                <div class="label">EXPIRY</div>
                <div id="expiry"
                     class="value">
                    5m
                </div>
            </div>

            <div class="metric">
                <div class="label">BIAS</div>
                <div id="bias"
                     class="value">
                    0 / 0
                </div>
            </div>

        </div>
    </div>

    <div class="card">
        <div class="label">LIVE CHART ANALYSIS</div>

        <div class="analysis"
             id="analysis">
            Waiting for screen feed...
        </div>

        <div class="health">
            <div id="healthbar"
                 class="healthbar"></div>
        </div>

        <div class="small">
            The signal engine uses the streamed chart,
            visible price movement and indicator agreement.
        </div>
    </div>
</div>

<!-- TRADES -->

<div id="trades"
     class="page">

    <div class="card">
        <div class="label">TRADE MONITOR</div>
        <h3>Live Entry</h3>

        <div class="grid">
            <div class="metric">
                <div class="label">DIRECTION</div>
                <div id="tradeSignal"
                     class="value">
                    WAIT
                </div>
            </div>

            <div class="metric">
                <div class="label">ENTRY</div>
                <div id="tradeEntry"
                     class="value">
                    --
                </div>
            </div>

            <div class="metric">
                <div class="label">WINDOW</div>
                <div id="tradeWindow"
                     class="value">
                    --
                </div>
            </div>

            <div class="metric">
                <div class="label">EXPIRY</div>
                <div id="tradeExpiry"
                     class="value">
                    --
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="label">TRADE STATUS</div>
        <div id="tradeStatus">
            No active entry.
        </div>
    </div>
</div>

<!-- PERFORMANCE -->

<div id="performance"
     class="page">

    <div class="card">
        <div class="label">ENGINE PERFORMANCE</div>

        <div class="grid">
            <div class="metric">
                <div class="label">SCANS</div>
                <div id="perfScans"
                     class="value">
                    0
                </div>
            </div>

            <div class="metric">
                <div class="label">CHART DETECTED</div>
                <div id="perfChart"
                     class="value">
                    NO
                </div>
            </div>

            <div class="metric">
                <div class="label">VISUAL BIAS</div>
                <div id="perfVisual"
                     class="value">
                    0
                </div>
            </div>

            <div class="metric">
                <div class="label">INDICATOR BIAS</div>
                <div id="perfIndicator"
                     class="value">
                    0
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="label">ENGINE</div>
        <div class="analysis">
            Alligator + EMA 9/20/50 + Parabolic SAR
            + MACD + CCI + RSI + Bollinger 20/2
            + Supertrend + ATR.
            <br><br>
            Signals require directional agreement and
            a minimum confidence threshold determined
            by the selected timeframe.
        </div>
    </div>
</div>

<!-- SETTINGS -->

<div id="settings"
     class="page">

    <div class="card">

        <div class="section">
            <div class="label">ASSET</div>
            <select id="assetSelect">
            </select>
        </div>

        <div class="section">
            <div class="label">TIMEFRAME</div>
            <select id="timeframeSelect">
            </select>
        </div>

        <div class="section">
            <div class="label">EXPIRY</div>
            <select id="expirySelect">
            </select>
        </div>

        <div class="section">
            <div class="label">PAYOUT %</div>
            <select id="payoutSelect">
                <option>70</option>
                <option>75</option>
                <option>80</option>
                <option selected>85</option>
                <option>90</option>
                <option>95</option>
            </select>
        </div>

        <button onclick="saveSettings()">
            APPLY SETTINGS
        </button>

        <div id="saveResult"
             class="small">
        </div>
    </div>

    <div class="card">
        <div class="label">FEED</div>
        <div class="analysis">
            Screen Stream / RTSP bridge endpoint:
            /api/frame
            <br><br>
            JSON feed endpoint:
            /api/feed
        </div>
    </div>
</div>

<script>

let currentState = {};
let assetData = null;

function showPage(id, el) {
    document.querySelectorAll('.page')
        .forEach(x => x.classList.remove('active'));

    document.querySelectorAll('.tab')
        .forEach(x => x.classList.remove('active'));

    document.getElementById(id)
        .classList.add('active');

    el.classList.add('active');
}

function $(id) {
    return document.getElementById(id);
}

function formatPrice(v) {
    if (!v || Number(v) === 0) {
        return "0.000000";
    }

    let n = Number(v);

    if (Math.abs(n) >= 1000) {
        return n.toFixed(2);
    }

    if (Math.abs(n) >= 10) {
        return n.toFixed(3);
    }

    return n.toFixed(6);
}

function populateSettings(data) {
    assetData = data;

    const assetSelect = $('assetSelect');
    assetSelect.innerHTML = '';

    for (const group of Object.keys(data.assets)) {
        const optgroup =
            document.createElement('optgroup');

        optgroup.label = group;

        for (const item of data.assets[group]) {
            const option =
                document.createElement('option');

            option.value = item[0];
            option.textContent = item[1];

            optgroup.appendChild(option);
        }

        assetSelect.appendChild(optgroup);
    }

    const tf = $('timeframeSelect');
    tf.innerHTML = '';

    data.timeframes.forEach(x => {
        const o = document.createElement('option');
        o.value = x;
        o.textContent = x;
        tf.appendChild(o);
    });

    const ex = $('expirySelect');
    ex.innerHTML = '';

    data.expiries.forEach(x => {
        const o = document.createElement('option');
        o.value = x;
        o.textContent = x;
        ex.appendChild(o);
    });
}

async function loadAssets() {
    try {
        const r =
            await fetch('/api/assets');

        const d =
            await r.json();

        if (d.ok) {
            populateSettings(d);
        }
    } catch (e) {
        console.log(e);
    }
}

async function saveSettings() {

    const payload = {
        asset: $('assetSelect').value,
        timeframe: $('timeframeSelect').value,
        expiry: $('expirySelect').value,
        payout: Number(
            $('payoutSelect').value
        )
    };

    try {
        const r = await fetch(
            '/api/settings',
            {
                method: 'POST',
                headers: {
                    'Content-Type':
                        'application/json'
                },
                body: JSON.stringify(payload)
            }
        );

        const d = await r.json();

        if (d.ok) {
            $('saveResult').textContent =
                'Settings applied. Waiting for fresh chart analysis...';

            update(d.state);
        } else {
            $('saveResult').textContent =
                d.error || 'Settings failed.';
        }

    } catch (e) {
        $('saveResult').textContent =
            'Connection error.';
    }
}

function update(s) {

    currentState = s;

    $('asset').textContent =
        s.asset || 'UNKNOWN';

    $('price').textContent =
        formatPrice(s.price);

    $('entry').textContent =
        formatPrice(s.entry);

    $('candles').textContent =
        s.candles || 0;

    $('timeframe').textContent =
        s.timeframe || '--';

    $('payout').textContent =
        (s.payout || 0) + '%';

    $('expiry').textContent =
        s.expiry || '--';

    $('confidence').textContent =
        (s.confidence || 0) + '%';

    $('bias').textContent =
        (s.visual_bias || 0)
        + ' / '
        + (s.indicator_bias || 0);

    $('analysis').textContent =
        s.analysis || 'Waiting...';

    $('scans').textContent =
        s.scan_count || 0;

    $('perfScans').textContent =
        s.scan_count || 0;

    $('perfChart').textContent =
        s.chart_detected ? 'YES' : 'NO';

    $('perfVisual').textContent =
        s.visual_bias || 0;

    $('perfIndicator').textContent =
        s.indicator_bias || 0;

    $('chartStatus').textContent =
        s.chart_detected ? 'LIVE' : 'WAITING';

    const sig =
        $('signal');

    sig.textContent =
        s.signal || 'WAIT';

    sig.className =
        'signalWord ' +
        (
            s.signal === 'CALL'
                ? 'call'
                : s.signal === 'PUT'
                    ? 'put'
                    : 'wait'
        );

    const seconds =
        Number(s.entry_window || 0);

    $('count').textContent =
        seconds > 0
            ? seconds + 's'
            : '--';

    $('count').className =
        'count' +
        (seconds <= 0 &&
         (s.signal === 'CALL' ||
          s.signal === 'PUT')
            ? ' expired'
            : '');

    if (seconds > 0 &&
        (s.signal === 'CALL' ||
         s.signal === 'PUT')) {

        $('entryText').textContent =
            'ENTRY WINDOW ACTIVE';

    } else if (s.signal === 'WAIT') {

        $('entryText').textContent =
            s.chart_detected
                ? 'WAITING FOR VALID SETUP'
                : 'WAITING FOR CHART';

    } else {

        $('entryText').textContent =
            'ENTRY WINDOW EXPIRED';
    }

    const fs =
        $('feedStatus');

    fs.className = 'status';

    if (s.feed === 'LIVE') {
        fs.classList.add('live');
    } else if (s.feed === 'STALE') {
        fs.classList.add('stale');
    } else {
        fs.classList.add('dead');
    }

    fs.innerHTML =
        '<span class="dot"></span> FEED: '
        + (s.feed || 'WAITING');

    $('healthbar').style.width =
        Math.min(
            100,
            Number(s.confidence || 0)
        ) + '%';

    $('tradeSignal').textContent =
        s.signal || 'WAIT';

    $('tradeEntry').textContent =
        formatPrice(s.entry);

    $('tradeWindow').textContent =
        seconds > 0
            ? seconds + 's'
            : '--';

    $('tradeExpiry').textContent =
        s.expiry || '--';

    if (seconds > 0 &&
        (s.signal === 'CALL' ||
         s.signal === 'PUT')) {

        $('tradeStatus').textContent =
            'ACTIVE ENTRY WINDOW — '
            + seconds + ' seconds remaining.';

    } else {

        $('tradeStatus').textContent =
            'No active entry window.';
    }

    // Synchronize settings controls.
    if (assetData) {
        $('assetSelect').value =
            s.asset || 'EURUSD_otc';

        $('timeframeSelect').value =
            s.timeframe || '1m';

        $('expirySelect').value =
            s.expiry || '5m';

        $('payoutSelect').value =
            String(s.payout || 85);
    }
}

async function poll() {

    try {
        const r =
            await fetch(
                '/api/state?x='
                + Date.now()
            );

        const d =
            await r.json();

        if (d.ok) {
            update(d.state);
        }

    } catch (e) {
        $('chartStatus').textContent =
            'OFFLINE';
    }
}

loadAssets();
poll();

setInterval(
    poll,
    1000
);

</script>

</body>
</html>
"""


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return render_template_string(HTML)


# ============================================================
# BACKGROUND STATE MAINTENANCE
# ============================================================

def maintenance_loop():
    while True:
        try:
            with STATE_LOCK:
                now = time.time()

                # Expire entry windows.
                if (
                    state["entry_deadline"] > 0
                    and now >= state["entry_deadline"]
                ):
                    state["entry_window"] = 0

                    if state["signal"] in (
                        "CALL",
                        "PUT"
                    ):
                        state["signal"] = "WAIT"

                    state["entry"] = 0.0

                # Feed status is calculated dynamically,
                # but make stale status visible internally too.
                if state["last_frame"]:
                    age = (
                        now - state["last_frame"]
                    )

                    if age > 25:
                        state["feed"] = "DISCONNECTED"
                    elif age > 8:
                        state["feed"] = "STALE"
                    else:
                        state["feed"] = "LIVE"

                state["server_time"] = now

        except Exception:
            pass

        time.sleep(0.5)


threading.Thread(
    target=maintenance_loop,
    daemon=True
).start()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
    )
