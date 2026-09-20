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
# GOTHIC MARKET INTELLIGENCE
# LIVE SCREEN-FEED SIGNAL ENGINE
# ============================================================

TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

MIN_CONFIDENCE = 78
STALE_SECONDS = 8
ENTRY_SECONDS = 12
DEFAULT_TIMEFRAME = "30s"

STATE_LOCK = threading.Lock()

state = {
    "asset": "UNKNOWN",
    "price": 0.0,
    "previous_price": 0.0,

    "signal": "WAIT",
    "confidence": 0,

    "entry": 0.0,
    "entry_window": 0,
    "signal_started": 0,

    "candles": 0,
    "timeframe": DEFAULT_TIMEFRAME,
    "payout": "--",

    "feed": "WAITING",
    "image_received": False,
    "last_frame": 0,

    "screen_status": "WAITING",
    "analysis_status": "WAITING",

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "rsi": 50.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "cci": 0.0,
    "sar": 0.0,
    "atr": 0.0,
    "bb_upper": 0.0,
    "bb_middle": 0.0,
    "bb_lower": 0.0,

    "bull_score": 0,
    "bear_score": 0,

    "updated": "",
}

# Rolling close prices.
prices = []

# Detected screen colors / direction history.
direction_history = []

# ============================================================
# HELPERS
# ============================================================

def now_ts():
    return time.time()


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        result = float(value)

        if math.isfinite(result):
            return result

    except Exception:
        pass

    return default


def clamp(value, low, high):
    return max(low, min(high, value))


def check_token():
    if not TOKEN:
        return True

    supplied = (
        request.headers.get("X-RYU-TOKEN")
        or request.headers.get("X-RYU-FEED-TOKEN")
        or request.args.get("token")
        or ""
    )

    return supplied.strip() == TOKEN


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if not values:
        return 0.0

    if len(values) == 1:
        return values[-1]

    alpha = 2.0 / (period + 1.0)

    result = values[0]

    for value in values[1:]:
        result = (value * alpha) + (result * (1.0 - alpha))

    return result


def sma(values, period):
    if not values:
        return 0.0

    data = values[-period:]

    return sum(data) / len(data)


def rsi(values, period=14):
    if len(values) < 2:
        return 50.0

    data = values[-(period + 1):]

    gains = []
    losses = []

    for i in range(1, len(data)):
        change = data[i] - data[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def bollinger(values, period=20, multiplier=2.0):
    if not values:
        return 0.0, 0.0, 0.0

    data = values[-period:]

    middle = sum(data) / len(data)

    variance = sum(
        (x - middle) ** 2 for x in data
    ) / len(data)

    std = math.sqrt(max(variance, 0.0))

    return (
        middle + multiplier * std,
        middle,
        middle - multiplier * std,
    )


def macd(values):
    if not values:
        return 0.0, 0.0

    fast = ema(values, 12)
    slow = ema(values, 26)

    line = fast - slow

    macd_values = []

    start = max(0, len(values) - 60)

    for i in range(start, len(values)):
        subset = values[:i + 1]

        macd_values.append(
            ema(subset, 12) - ema(subset, 26)
        )

    signal_line = ema(macd_values, 9) if macd_values else line

    return line, signal_line


def cci(values, period=20):
    if len(values) < 2:
        return 0.0

    data = values[-period:]

    middle = sum(data) / len(data)

    deviation = sum(abs(x - middle) for x in data) / len(data)

    if deviation == 0:
        return 0.0

    return (data[-1] - middle) / (0.015 * deviation)


def atr(values, period=14):
    if len(values) < 2:
        return 0.0

    changes = [
        abs(values[i] - values[i - 1])
        for i in range(1, len(values))
    ]

    return sum(changes[-period:]) / min(
        period,
        len(changes)
    )


def parabolic_sar_proxy(values):
    """
    Screenshot/price-feed compatible SAR proxy.

    When only close prices are supplied rather than complete
    OHLC candles, this gives a directional SAR-style reference.
    """

    if len(values) < 3:
        return values[-1] if values else 0.0

    recent = values[-14:]

    low = min(recent)
    high = max(recent)

    current = recent[-1]

    if current >= sma(recent, len(recent)):
        return low
    else:
        return high


def alligator_proxy(values):
    """
    Williams Alligator-style moving-average relationship.

    With close-only feed data we approximate:
    jaw   = EMA 13
    teeth = EMA 8
    lips  = EMA 5
    """

    return (
        ema(values, 13),
        ema(values, 8),
        ema(values, 5),
    )


def supertrend_proxy(values):
    """
    Close-only Supertrend approximation.
    """

    if len(values) < 2:
        return 0.0

    middle = ema(values, 10)
    volatility = atr(values, 10)

    current = values[-1]

    if current >= middle:
        return middle - (2.0 * volatility)

    return middle + (2.0 * volatility)


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal():
    global prices

    with STATE_LOCK:
        data = list(prices)

    if len(data) < 30:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "bull": 0,
            "bear": 0,
            "indicators": {},
        }

    current = data[-1]

    ema9_value = ema(data, 9)
    ema20_value = ema(data, 20)
    ema50_value = ema(data, 50)

    rsi_value = rsi(data, 14)

    macd_value, macd_signal_value = macd(data)

    cci_value = cci(data, 20)

    bb_upper, bb_middle, bb_lower = bollinger(
        data,
        20,
        2.0
    )

    atr_value = atr(data, 14)

    sar_value = parabolic_sar_proxy(data)

    jaw, teeth, lips = alligator_proxy(data)

    supertrend = supertrend_proxy(data)

    bull = 0
    bear = 0

    # --------------------------------------------------------
    # EMA TREND
    # --------------------------------------------------------

    if ema9_value > ema20_value:
        bull += 10
    elif ema9_value < ema20_value:
        bear += 10

    if ema20_value > ema50_value:
        bull += 10
    elif ema20_value < ema50_value:
        bear += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi_value <= 70:
        bull += 10
    elif 30 <= rsi_value <= 48:
        bear += 10

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd_value > macd_signal_value:
        bull += 12
    elif macd_value < macd_signal_value:
        bear += 12

    # --------------------------------------------------------
    # CCI
    # --------------------------------------------------------

    if cci_value > 50:
        bull += 10
    elif cci_value < -50:
        bear += 10

    # --------------------------------------------------------
    # BOLLINGER
    # --------------------------------------------------------

    if bb_middle > 0:

        if current > bb_middle:
            bull += 8

        elif current < bb_middle:
            bear += 8

    # --------------------------------------------------------
    # PARABOLIC SAR
    # --------------------------------------------------------

    if current > sar_value:
        bull += 10
    elif current < sar_value:
        bear += 10

    # --------------------------------------------------------
    # ALLIGATOR
    # --------------------------------------------------------

    if lips > teeth > jaw:
        bull += 12

    elif lips < teeth < jaw:
        bear += 12

    # --------------------------------------------------------
    # SUPERTREND
    # --------------------------------------------------------

    if current > supertrend:
        bull += 10
    elif current < supertrend:
        bear += 10

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if len(data) >= 5:

        momentum = current - data[-5]

        if momentum > 0:
            bull += 8
        elif momentum < 0:
            bear += 8

    total = bull + bear

    if total <= 0:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "bull": bull,
            "bear": bear,
            "indicators": {},
        }

    dominant = max(bull, bear)

    confidence = int(
        round((dominant / total) * 100)
    )

    # Prevent false confidence from a nearly balanced market.
    difference = abs(bull - bear)

    if difference < 12:
        signal = "WAIT"
        confidence = min(confidence, 65)

    elif bull > bear and confidence >= MIN_CONFIDENCE:
        signal = "CALL"

    elif bear > bull and confidence >= MIN_CONFIDENCE:
        signal = "PUT"

    else:
        signal = "WAIT"

    return {
        "signal": signal,
        "confidence": confidence,
        "bull": bull,
        "bear": bear,
        "indicators": {
            "ema9": ema9_value,
            "ema20": ema20_value,
            "ema50": ema50_value,
            "rsi": rsi_value,
            "macd": macd_value,
            "macd_signal": macd_signal_value,
            "cci": cci_value,
            "sar": sar_value,
            "atr": atr_value,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "alligator_jaw": jaw,
            "alligator_teeth": teeth,
            "alligator_lips": lips,
            "supertrend": supertrend,
        },
    }


# ============================================================
# PRICE FEED
# ============================================================

def add_price(price):
    global prices

    price = safe_float(price)

    if price <= 0:
        return False

    with STATE_LOCK:

        state["previous_price"] = (
            prices[-1] if prices else price
        )

        prices.append(price)

        # Keep a rolling history.
        if len(prices) > 500:
            prices = prices[-500:]

        state["price"] = price
        state["candles"] = len(prices)
        state["last_frame"] = now_ts()
        state["feed"] = "LIVE"
        state["screen_status"] = "LIVE"
        state["updated"] = iso_now()

    return True


# ============================================================
# SIGNAL UPDATE
# ============================================================

def update_signal():

    result = calculate_signal()

    signal = result["signal"]
    confidence = result["confidence"]

    with STATE_LOCK:

        previous_signal = state["signal"]

        state["bull_score"] = result["bull"]
        state["bear_score"] = result["bear"]

        indicators = result["indicators"]

        for key, value in indicators.items():

            if key in state:
                state[key] = round(
                    safe_float(value),
                    8
                )

        # New valid signal.
        if signal in ("CALL", "PUT"):

            # Start/restart timer when signal direction changes
            # or the previous signal expired.
            expired = (
                state["signal_started"] <= 0
                or (
                    now_ts()
                    - state["signal_started"]
                    > ENTRY_SECONDS
                )
            )

            if (
                previous_signal != signal
                or expired
            ):
                state["signal_started"] = now_ts()
                state["entry"] = state["price"]

            state["signal"] = signal
            state["confidence"] = confidence
            state["analysis_status"] = "SIGNAL ACTIVE"

        else:

            # Don't leave a dead CALL/PUT displayed indefinitely.
            state["signal"] = "WAIT"
            state["confidence"] = confidence
            state["entry"] = 0.0
            state["signal_started"] = 0
            state["entry_window"] = 0
            state["analysis_status"] = "ANALYZING"

        state["updated"] = iso_now()


# ============================================================
# SCREEN IMAGE ANALYSIS
# ============================================================

def analyze_screen_image(image):
    """
    Extract directional information from a Pocket Option
    screenshot.

    This intentionally does NOT invent an exact price or asset.

    It looks for green/red candle pixels and converts their
    relative balance into directional price observations.
    """

    try:

        image = image.convert("RGB")

        width, height = image.size

        if width < 50 or height < 50:
            return None

        # Chart is normally in the middle/right portion of the
        # Pocket Option interface.
        left = int(width * 0.20)
        right = int(width * 0.95)

        top = int(height * 0.20)
        bottom = int(height * 0.85)

        crop = image.crop(
            (left, top, right, bottom)
        )

        cw, ch = crop.size

        green = 0
        red = 0

        # Sample pixels rather than processing every pixel.
        step_x = max(1, cw // 180)
        step_y = max(1, ch // 120)

        for y in range(0, ch, step_y):

            for x in range(0, cw, step_x):

                r, g, b = crop.getpixel((x, y))

                # Green candle/body/wick.
                if (
                    g > r * 1.18
                    and g > b * 1.08
                    and g > 70
                ):
                    green += 1

                # Red candle/body/wick.
                elif (
                    r > g * 1.18
                    and r > b * 1.10
                    and r > 70
                ):
                    red += 1

        total = green + red

        if total < 5:
            return {
                "direction": "UNKNOWN",
                "strength": 0.0,
            }

        if green > red:
            direction = "UP"
            strength = green / total
        else:
            direction = "DOWN"
            strength = red / total

        return {
            "direction": direction,
            "strength": float(strength),
            "green": green,
            "red": red,
        }

    except Exception:
        return None


def image_to_price_observation(analysis):
    """
    Converts detected screen direction into a small synthetic
    observation only when the image feed does not provide an
    actual price.

    This is deliberately kept separate from actual price data.
    """

    if not analysis:
        return None

    direction = analysis.get("direction")

    strength = safe_float(
        analysis.get("strength"),
        0.0
    )

    if direction == "UNKNOWN":
        return None

    # If no actual price exists, use a normalized internal series.
    with STATE_LOCK:
        current = (
            prices[-1]
            if prices
            else 100.0
        )

    movement = 0.0005 * max(
        0.25,
        strength
    )

    if direction == "UP":
        return current * (1.0 + movement)

    return current * (1.0 - movement)


# ============================================================
# FEED ENDPOINT
# ============================================================

@app.route("/api/feed", methods=["POST"])
def api_feed():

    if not check_token():
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

    asset = (
        data.get("asset")
        or data.get("symbol")
        or data.get("pair")
    )

    price = (
        data.get("price")
        or data.get("current_price")
        or data.get("last")
    )

    timeframe = (
        data.get("timeframe")
        or state["timeframe"]
    )

    payout = (
        data.get("payout")
        or state["payout"]
    )

    # --------------------------------------------------------
    # Accept supplied candle closes if available.
    # --------------------------------------------------------

    candle_values = (
        data.get("prices")
        or data.get("closes")
        or data.get("candles")
    )

    added = False

    if isinstance(candle_values, list):

        for value in candle_values[-100:]:

            value = safe_float(value)

            if value > 0:
                add_price(value)
                added = True

    # --------------------------------------------------------
    # Accept current price.
    # --------------------------------------------------------

    if price is not None:

        if add_price(price):
            added = True

    with STATE_LOCK:

        if asset:
            state["asset"] = str(asset)

        state["timeframe"] = str(timeframe)
        state["payout"] = str(payout)

        state["feed"] = "LIVE"
        state["screen_status"] = "LIVE"
        state["last_frame"] = now_ts()
        state["updated"] = iso_now()

    if added:
        update_signal()

    with STATE_LOCK:
        result = dict(state)

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "state": result
    })


# ============================================================
# IMAGE FRAME ENDPOINT
# ============================================================

@app.route("/api/frame", methods=["POST"])
def api_frame():

    if not check_token():
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    image_data = None

    # Multipart upload.
    if request.files:

        for key in (
            "frame",
            "image",
            "file",
            "screenshot"
        ):

            if key in request.files:

                image_data = request.files[
                    key
                ].read()

                break

        if image_data is None:

            first = next(
                iter(request.files.values()),
                None
            )

            if first:
                image_data = first.read()

    # Raw JPEG/PNG body.
    if image_data is None:

        raw = request.get_data()

        if raw:
            image_data = raw

    if not image_data:

        return jsonify({
            "ok": False,
            "error": "No image received"
        }), 400

    try:

        image = Image.open(
            io.BytesIO(image_data)
        )

        image.load()

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": "Invalid image",
            "detail": str(exc)
        }), 400

    analysis = analyze_screen_image(
        image
    )

    with STATE_LOCK:

        state["image_received"] = True
        state["last_frame"] = now_ts()
        state["feed"] = "LIVE"
        state["screen_status"] = "LIVE"
        state["updated"] = iso_now()

    # If an actual JSON price has already been supplied,
    # don't replace it with an image-derived fake price.
    with STATE_LOCK:
        have_real_price = (
            state["price"] > 0
        )

    if not have_real_price:

        observed = image_to_price_observation(
            analysis
        )

        if observed:
            add_price(observed)

    update_signal()

    with STATE_LOCK:
        result = dict(state)

    return jsonify({
        "ok": True,
        "message": "Screen frame accepted",
        "image_analysis": analysis,
        "state": result
    })


# ============================================================
# STATE
# ============================================================

@app.route("/api/state", methods=["GET"])
def api_state():

    with STATE_LOCK:

        current = dict(state)

        last = state["last_frame"]

        if last:
            age = now_ts() - last
        else:
            age = 999999

        if age > STALE_SECONDS:

            current["feed"] = "STALE"
            current["screen_status"] = "DISCONNECTED"
            current["signal"] = "WAIT"
            current["confidence"] = 0
            current["entry_window"] = 0
            current["analysis_status"] = "WAITING FOR LIVE FEED"

        else:

            current["feed"] = "LIVE"

            started = state[
                "signal_started"
            ]

            if (
                state["signal"]
                in ("CALL", "PUT")
                and started > 0
            ):

                remaining = int(
                    max(
                        0,
                        ENTRY_SECONDS
                        - (
                            now_ts()
                            - started
                        )
                    )
                )

                current[
                    "entry_window"
                ] = remaining

                if remaining <= 0:
                    current["signal"] = "WAIT"
                    current["analysis_status"] = (
                        "ENTRY EXPIRED"
                    )

            else:

                current["entry_window"] = 0

        current["feed_age"] = round(
            age,
            2
        )

        return jsonify(current)


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():

    with STATE_LOCK:

        age = (
            now_ts() - state["last_frame"]
            if state["last_frame"]
            else 999999
        )

        return jsonify({
            "ok": True,
            "service": "ALUCARD V2.1",
            "feed": (
                "LIVE"
                if age <= STALE_SECONDS
                else "STALE"
            ),
            "feed_age": round(age, 2),
            "candles": len(prices),
            "asset": state["asset"],
            "signal": state["signal"],
        })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!doctype html>
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
    background:
        radial-gradient(circle at top,#182719,#050805 65%);
    color: #d9ffd9;
    font-family: Arial, sans-serif;
}

header {
    padding: 18px;
    border-bottom: 1px solid #2e642e;
    background: rgba(0,0,0,.55);
}

.logo {
    font-size: 27px;
    font-weight: 900;
    letter-spacing: 4px;
}

.subtitle {
    color: #79a879;
    font-size: 11px;
    letter-spacing: 2px;
    margin-top: 4px;
}

.status {
    margin-top: 10px;
    display: inline-block;
    padding: 6px 10px;
    border: 1px solid #397a39;
    border-radius: 5px;
    font-size: 11px;
}

nav {
    display: flex;
    overflow-x: auto;
    gap: 5px;
    padding: 10px;
    background: #071007;
}

nav button {
    flex: 1;
    min-width: 100px;
    padding: 11px;
    background: #0b160b;
    border: 1px solid #284d28;
    color: #9ac69a;
    border-radius: 5px;
}

main {
    padding: 12px;
    max-width: 1100px;
    margin: auto;
}

.hero {
    border: 1px solid #356635;
    border-radius: 10px;
    padding: 18px;
    background: rgba(0,0,0,.45);
    box-shadow: 0 0 25px rgba(0,0,0,.45);
}

.signal {
    text-align: center;
    font-size: 54px;
    font-weight: 900;
    letter-spacing: 5px;
    margin: 8px 0;
}

.call {
    color: #67ff67;
    text-shadow: 0 0 18px #39ff39;
}

.put {
    color: #ff5b5b;
    text-shadow: 0 0 18px #ff2020;
}

.wait {
    color: #c6c6c6;
}

.confidence {
    text-align: center;
    font-size: 18px;
}

.timer {
    text-align: center;
    font-size: 36px;
    margin-top: 8px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit,minmax(145px,1fr));
    gap: 9px;
    margin-top: 12px;
}

.card {
    padding: 12px;
    border: 1px solid #294d29;
    border-radius: 7px;
    background: rgba(4,12,4,.8);
}

.label {
    font-size: 10px;
    color: #729772;
    letter-spacing: 1px;
}

.value {
    margin-top: 5px;
    font-size: 17px;
    font-weight: bold;
}

.section {
    margin-top: 12px;
    border: 1px solid #294d29;
    border-radius: 8px;
    padding: 13px;
    background: rgba(0,0,0,.3);
}

.section h3 {
    margin-top: 0;
    font-size: 13px;
    letter-spacing: 2px;
}

.indicators {
    display: grid;
    grid-template-columns:
        repeat(auto-fit,minmax(125px,1fr));
    gap: 7px;
}

.ind {
    border-bottom: 1px solid #203820;
    padding: 7px;
}

.small {
    font-size: 11px;
    color: #759075;
}

</style>
</head>

<body>

<header>

<div class="logo">ALUCARD</div>

<div class="subtitle">
GOTHIC MARKET INTELLIGENCE — V2.1
</div>

<div id="feedStatus"
     class="status">
FEED: WAITING
</div>

</header>

<nav>
<button>Signals</button>
<button>Trades</button>
<button>Performance</button>
<button>Settings</button>
</nav>

<main>

<div class="hero">

<div class="label"
     style="text-align:center">
CURRENT SIGNAL
</div>

<div id="signal"
     class="signal wait">
WAIT
</div>

<div id="confidence"
     class="confidence">
Confidence: 0%
</div>

<div id="timer"
     class="timer">
--
</div>

</div>

<div class="grid">

<div class="card">
<div class="label">ASSET</div>
<div id="asset"
     class="value">
UNKNOWN
</div>
</div>

<div class="card">
<div class="label">PRICE</div>
<div id="price"
     class="value">
0.000000
</div>
</div>

<div class="card">
<div class="label">ENTRY</div>
<div id="entry"
     class="value">
0.000000
</div>
</div>

<div class="card">
<div class="label">CANDLES</div>
<div id="candles"
     class="value">
0
</div>
</div>

<div class="card">
<div class="label">TIMEFRAME</div>
<div id="timeframe"
     class="value">
30s
</div>
</div>

<div class="card">
<div class="label">PAYOUT</div>
<div id="payout"
     class="value">
--
</div>
</div>

</div>

<div class="section">

<h3>MARKET ANALYSIS</h3>

<div id="analysisStatus"
     class="small">
Waiting for live feed...
</div>

<div class="indicators">

<div class="ind">
<div class="label">EMA 9</div>
<div id="ema9">--</div>
</div>

<div class="ind">
<div class="label">EMA 20</div>
<div id="ema20">--</div>
</div>

<div class="ind">
<div class="label">EMA 50</div>
<div id="ema50">--</div>
</div>

<div class="ind">
<div class="label">RSI</div>
<div id="rsi">--</div>
</div>

<div class="ind">
<div class="label">MACD</div>
<div id="macd">--</div>
</div>

<div class="ind">
<div class="label">CCI</div>
<div id="cci">--</div>
</div>

<div class="ind">
<div class="label">SAR</div>
<div id="sar">--</div>
</div>

<div class="ind">
<div class="label">ATR</div>
<div id="atr">--</div>
</div>

<div class="ind">
<div class="label">BOLLINGER</div>
<div id="bb">--</div>
</div>

</div>

</div>

<div class="section">

<h3>SCREEN FEED</h3>

<div class="grid">

<div class="card">
<div class="label">SCREEN</div>
<div id="screen"
     class="value">
WAITING
</div>
</div>

<div class="card">
<div class="label">FEED AGE</div>
<div id="age"
     class="value">
--
</div>
</div>

<div class="card">
<div class="label">BULL SCORE</div>
<div id="bull"
     class="value">
0
</div>
</div>

<div class="card">
<div class="label">BEAR SCORE</div>
<div id="bear"
     class="value">
0
</div>
</div>

</div>

</div>

</main>

<script>

function setText(id,value) {

    const el =
        document.getElementById(id);

    if (el) {
        el.textContent = value;
    }
}


function number(value,digits=5) {

    if (
        value === undefined ||
        value === null ||
        value === 0
    ) {
        return "--";
    }

    const n = Number(value);

    if (!Number.isFinite(n)) {
        return "--";
    }

    return n.toFixed(digits);
}


async function update() {

    try {

        const response =
            await fetch(
                "/api/state",
                {cache:"no-store"}
            );

        const s =
            await response.json();

        const signal =
            s.signal || "WAIT";

        const signalEl =
            document.getElementById(
                "signal"
            );

        signalEl.textContent =
            signal;

        signalEl.className =
            "signal " +
            (
                signal === "CALL"
                    ? "call"
                    : signal === "PUT"
                        ? "put"
                        : "wait"
            );

        setText(
            "confidence",
            "Confidence: " +
            (s.confidence || 0) +
            "%"
        );

        setText(
            "asset",
            s.asset || "UNKNOWN"
        );

        setText(
            "price",
            number(s.price,6)
        );

        setText(
            "entry",
            number(s.entry,6)
        );

        setText(
            "candles",
            s.candles || 0
        );

        setText(
            "timeframe",
            s.timeframe || "30s"
        );

        setText(
            "payout",
            s.payout || "--"
        );

        setText(
            "screen",
            s.screen_status || "WAITING"
        );

        setText(
            "age",
            s.feed_age !== undefined
                ? s.feed_age + "s"
                : "--"
        );

        setText(
            "bull",
            s.bull_score || 0
        );

        setText(
            "bear",
            s.bear_score || 0
        );

        setText(
            "analysisStatus",
            s.analysis_status ||
            "Analyzing..."
        );

        const timer =
            Number(
                s.entry_window || 0
            );

        setText(
            "timer",
            (
                signal === "CALL" ||
                signal === "PUT"
            )
                ? timer + "s"
                : "--"
        );

        setText(
            "feedStatus",
            "FEED: " +
            (s.feed || "WAITING")
        );

        setText(
            "ema9",
            number(s.ema9)
        );

        setText(
            "ema20",
            number(s.ema20)
        );

        setText(
            "ema50",
            number(s.ema50)
        );

        setText(
            "rsi",
            number(s.rsi,2)
        );

        setText(
            "macd",
            number(s.macd,6)
        );

        setText(
            "cci",
            number(s.cci,2)
        );

        setText(
            "sar",
            number(s.sar)
        );

        setText(
            "atr",
            number(s.atr,6)
        );

        if (
            s.bb_upper &&
            s.bb_lower
        ) {

            setText(
                "bb",
                number(s.bb_lower) +
                " / " +
                number(s.bb_upper)
            );

        } else {

            setText(
                "bb",
                "--"
            );
        }

    } catch(error) {

        setText(
            "feedStatus",
            "FEED: OFFLINE"
        );

        setText(
            "analysisStatus",
            "Dashboard cannot reach feed"
        );
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
    return render_template_string(
        HTML
    )


# ============================================================
# BACKGROUND STALE-FEED WATCHDOG
# ============================================================

def watchdog():

    while True:

        try:

            with STATE_LOCK:

                if state["last_frame"]:

                    age = (
                        now_ts()
                        - state["last_frame"]
                    )

                    if age > STALE_SECONDS:

                        state["feed"] = "STALE"
                        state["screen_status"] = (
                            "DISCONNECTED"
                        )

                        state["signal"] = "WAIT"
                        state["confidence"] = 0
                        state["entry"] = 0.0
                        state["entry_window"] = 0
                        state["signal_started"] = 0

                        state["analysis_status"] = (
                            "WAITING FOR LIVE FEED"
                        )

        except Exception:
            pass

        time.sleep(1)


watchdog_thread = threading.Thread(
    target=watchdog,
    daemon=True
)

watchdog_thread.start()


# ============================================================
# LOCAL START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "5000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
