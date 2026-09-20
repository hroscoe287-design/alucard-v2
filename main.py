import os
import io
import math
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from PIL import Image
import numpy as np

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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def ema(values, period):
    values = np.asarray(values, dtype=float)

    if len(values) == 0:
        return 0.0

    alpha = 2.0 / (period + 1.0)
    result = float(values[0])

    for value in values[1:]:
        result = (
            alpha * float(value)
            + (1.0 - alpha) * result
        )

    return result


def rsi_value(values, period=14):
    values = np.asarray(values, dtype=float)

    if len(values) < period + 1:
        return 50.0

    changes = np.diff(values)

    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)

    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))

    if avg_loss == 0:
        if avg_gain > 0:
            return 100.0
        return 50.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def macd_value(values):
    return ema(values, 12) - ema(values, 26)


def atr_proxy(values, period=14):
    values = np.asarray(values, dtype=float)

    if len(values) < 2:
        return 0.0

    differences = np.abs(np.diff(values))

    if len(differences) == 0:
        return 0.0

    return float(np.mean(differences[-period:]))


def cci_proxy(values, period=20):
    values = np.asarray(values, dtype=float)

    if len(values) < period:
        return 0.0

    window = values[-period:]

    mean_value = float(np.mean(window))

    mean_deviation = float(
        np.mean(np.abs(window - mean_value))
    )

    if mean_deviation == 0:
        return 0.0

    return float(
        (window[-1] - mean_value)
        / (0.015 * mean_deviation)
    )


def detect_chart_series(image):
    """
    Best-effort chart-pixel extraction.

    A screenshot does not reliably expose the numeric market price,
    so this function creates a normalized price series from visible
    chart pixels instead of pretending the pixel position is a real
    market price.
    """

    rgb = np.asarray(image.convert("RGB"))

    height, width, _ = rgb.shape

    # Focus on the central chart area.
    y0 = int(height * 0.15)
    y1 = int(height * 0.78)

    x0 = int(width * 0.05)
    x1 = int(width * 0.95)

    crop = rgb[y0:y1, x0:x1].astype(np.int16)

    red = crop[:, :, 0]
    green = crop[:, :, 1]
    blue = crop[:, :, 2]

    bullish = (
        (green > red + 25)
        & (green > blue + 10)
        & (green > 70)
    )

    bearish = (
        (red > green + 35)
        & (red > blue + 20)
        & (red > 80)
    )

    points = []

    bullish_count = 0
    bearish_count = 0

    for x in range(crop.shape[1]):

        green_y = np.where(bullish[:, x])[0]
        red_y = np.where(bearish[:, x])[0]

        all_y = np.concatenate(
            (green_y, red_y)
        )

        if len(all_y) < 2:
            continue

        y = float(np.median(all_y))

        if len(green_y) >= len(red_y):
            bullish_count += 1
        else:
            bearish_count += 1

        points.append((x, y))

    if len(points) < 25:
        return None

    points.sort(key=lambda item: item[0])

    xs = np.array(
        [item[0] for item in points],
        dtype=float
    )

    ys = np.array(
        [item[1] for item in points],
        dtype=float
    )

    bins = min(
        120,
        max(40, len(points) // 2)
    )

    edges = np.linspace(
        xs.min(),
        xs.max() + 1,
        bins + 1
    )

    closes = []

    for i in range(bins):

        mask = (
            (xs >= edges[i])
            & (xs < edges[i + 1])
        )

        if mask.any():
            closes.append(
                float(np.median(ys[mask]))
            )

    if len(closes) < 25:
        return None

    closes = np.asarray(
        closes,
        dtype=float
    )

    # Screen Y increases downward.
    # Reverse it so rising price = positive movement.
    closes = np.max(closes) - closes

    # Small smoothing pass.
    if len(closes) >= 3:

        closes = np.convolve(
            closes,
            np.array([0.25, 0.50, 0.25]),
            mode="same"
        )

        closes[0] = closes[1]
        closes[-1] = closes[-2]

    return (
        closes,
        bullish_count,
        bearish_count
    )


def analyze_image(image):

    result = detect_chart_series(image)

    if result is None:

        return {
            "ok": False,
            "analysis": (
                "Screen received, but chart candles "
                "could not be isolated."
            )
        }

    closes, bullish_pixels, bearish_pixels = result

    ema9 = ema(closes, 9)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi = rsi_value(closes, 14)
    macd = macd_value(closes)
    cci = cci_proxy(closes, 20)
    atr = atr_proxy(closes, 14)

    recent = float(
        np.mean(closes[-10:])
    )

    if len(closes) >= 30:
        older = float(
            np.mean(closes[-30:-20])
        )
    else:
        older = recent

    slope = recent - older

    votes_call = 0
    votes_put = 0

    # EMA 9 / 20
    if ema9 > ema20:
        votes_call += 1
    elif ema9 < ema20:
        votes_put += 1

    # EMA 20 / 50
    if ema20 > ema50:
        votes_call += 1
    elif ema20 < ema50:
        votes_put += 1

    # RSI
    if rsi >= 55:
        votes_call += 1
    elif rsi <= 45:
        votes_put += 1

    # MACD
    if macd > 0:
        votes_call += 1
    elif macd < 0:
        votes_put += 1

    # CCI
    if cci >= 50:
        votes_call += 1
    elif cci <= -50:
        votes_put += 1

    # Price slope
    if slope > 0:
        votes_call += 1
    elif slope < 0:
        votes_put += 1

    total_votes = 6

    strongest = max(
        votes_call,
        votes_put
    )

    confidence = int(
        round(
            (strongest / total_votes) * 100
        )
    )

    # Require strong agreement.
    if (
        votes_call >= 5
        and votes_call > votes_put
    ):
        signal = "CALL"

    elif (
        votes_put >= 5
        and votes_put > votes_call
    ):
        signal = "PUT"

    else:
        signal = "WAIT"
        confidence = min(
            confidence,
            77
        )

    if (
        bullish_pixels
        + bearish_pixels
    ):

        candle_bias = int(
            round(
                100
                * bullish_pixels
                / (
                    bullish_pixels
                    + bearish_pixels
                )
            )
        )

    else:
        candle_bias = 50

    if signal == "CALL":

        analysis_text = (
            "Chart analyzed: bullish agreement "
            f"{votes_call}/{total_votes}; "
            f"candle bias {candle_bias}%."
        )

    elif signal == "PUT":

        analysis_text = (
            "Chart analyzed: bearish agreement "
            f"{votes_put}/{total_votes}; "
            f"candle bias "
            f"{100 - candle_bias}%."
        )

    else:

        analysis_text = (
            "Chart analyzed: indicators are mixed; "
            "waiting for stronger agreement."
        )

    return {
        "ok": True,

        # Do not invent these from screen pixels.
        "asset": "UNKNOWN",
        "price": 0.0,
        "entry": 0.0,

        "signal": signal,
        "confidence": confidence,

        "candles": int(len(closes)),

        "ema9": ema9,
        "ema20": ema20,
        "ema50": ema50,

        "rsi": rsi,
        "macd": macd,
        "cci": cci,
        "atr": atr,

        "analysis": analysis_text
    }


def update_json(data):

    with lock:

        if "asset" in data:
            state["asset"] = str(
                data["asset"]
            )

        if "price" in data:
            state["price"] = safe_float(
                data["price"]
            )

        if "signal" in data:

            signal = str(
                data["signal"]
            ).upper()

            if signal in (
                "CALL",
                "PUT",
                "WAIT"
            ):
                state["signal"] = signal

        if "confidence" in data:

            state["confidence"] = max(
                0,
                min(
                    100,
                    safe_int(
                        data["confidence"]
                    )
                )
            )

        if "entry" in data:
            state["entry"] = safe_float(
                data["entry"]
            )

        if "entry_window" in data:

            state["entry_window"] = max(
                0,
                safe_int(
                    data["entry_window"],
                    12
                )
            )

        if "candles" in data:

            state["candles"] = max(
                0,
                safe_int(
                    data["candles"]
                )
            )

        for key in (
            "ema9",
            "ema20",
            "ema50",
            "rsi",
            "macd",
            "cci",
            "atr"
        ):

            if key in data:
                state[key] = safe_float(
                    data[key]
                )

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
        ).convert("RGB")

        image.load()

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": "Invalid image: " + str(exc)
        }), 400

    analysis = analyze_image(image)

    timestamp = now_utc()

    with lock:

        state["image_received"] = True
        state["last_frame"] = timestamp
        state["feed"] = "LIVE"
        state["updated"] = timestamp

        if analysis.get("ok"):

            for key in (
                "asset",
                "price",
                "signal",
                "confidence",
                "entry",
                "candles",
                "ema9",
                "ema20",
                "ema50",
                "rsi",
                "macd",
                "cci",
                "atr",
                "analysis"
            ):

                if key in analysis:
                    state[key] = analysis[key]

        else:

            state["signal"] = "WAIT"
            state["confidence"] = 0
            state["analysis"] = (
                analysis["analysis"]
            )

    return jsonify({
        "ok": True,
        "message": (
            "ALUCARD screen frame "
            "accepted and analyzed"
        ),
        "feed": "LIVE",
        "image_received": True,
        "analysis_ok": analysis.get(
            "ok",
            False
        ),
        "timestamp": timestamp,
        "state": current_state()
    })


def current_state():

    with lock:
        result = dict(state)

    age = 999999

    if result["updated"]:

        try:

            last = datetime.strptime(
                result["updated"],
                "%Y-%m-%d %H:%M:%S UTC"
            ).replace(
                tzinfo=timezone.utc
            )

            age = max(
                0,
                int(
                    (
                        datetime.now(
                            timezone.utc
                        ) - last
                    ).total_seconds()
                )
            )

        except Exception:
            age = 999999

    result["age_seconds"] = age

    if age > 20:

        result["feed"] = "DISCONNECTED"

        result["analysis"] = (
            "Pocket Option screen feed stopped."
        )

        result["signal"] = "WAIT"
        result["confidence"] = 0

    return result


@app.get("/")
def dashboard():
    return render_template_string(HTML)


@app.get("/api/state")
def api_state():
    return jsonify(
        current_state()
    )


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
            "message": (
                "ALUCARD JSON feed accepted"
            ),
            "state": current_state()
        })

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

    raw = request.get_data()

    if raw:
        return process_image(raw)

    return jsonify({
        "ok": False,
        "error": (
            "No JSON or image received"
        )
    }), 400


@app.post("/api/frame")
def api_frame():

    if not authorized():

        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

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

    if request.is_json:

        data = request.get_json(
            silent=True
        )

        if isinstance(data, dict):

            update_json(data)

            return jsonify({
                "ok": True,
                "message": (
                    "ALUCARD JSON frame accepted"
                ),
                "state": current_state()
            })

    raw = request.get_data()

    if raw:
        return process_image(raw)

    return jsonify({
        "ok": False,
        "error": (
            "No image or JSON data received"
        )
    }), 400


HTML = r"""
<!doctype html>
<html>
<head>

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>

body {
    margin: 0;
    background: #08090d;
    color: #eee;
    font-family: Arial, sans-serif;
}

.wrap {
    max-width: 1100px;
    margin: auto;
    padding: 18px;
}

h1 {
    margin: 0;
    font-size: 28px;
    letter-spacing: 3px;
}

.sub {
    color: #888;
    margin: 4px 0 14px;
}

.status {
    padding: 10px;
    border: 1px solid #333;
    margin-bottom: 14px;
    font-weight: bold;
}

.live {
    color: #7cff9a;
}

.dead {
    color: #ff6666;
}

.tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
    flex-wrap: wrap;
}

.tab {
    padding: 9px 13px;
    border: 1px solid #333;
    color: #aaa;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(4, 1fr);
    gap: 10px;
}

.card {
    background: #11141a;
    border: 1px solid #292d35;
    padding: 13px;
    min-height: 62px;
}

.label {
    color: #777;
    font-size: 11px;
    letter-spacing: 1px;
}

.value {
    font-size: 22px;
    margin-top: 8px;
}

.signal {
    font-weight: bold;
}

.analysis {
    grid-column: 1 / -1;
}

.ind {
    grid-column: 1 / -1;
    line-height: 1.8;
}

@media(max-width:700px) {

    .grid {
        grid-template-columns:
            repeat(2, 1fr);
    }

}

</style>

</head>

<body>

<div class="wrap">

<h1>ALUCARD</h1>

<div class="sub">
GOTHIC MARKET INTELLIGENCE — V2.1
</div>

<div id="status"
     class="status">
FEED: CHECKING...
</div>

<div class="tabs">

<div class="tab">Signals</div>
<div class="tab">Trades</div>
<div class="tab">Performance</div>
<div class="tab">Settings</div>

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
<div class="label">SIGNAL</div>
<div id="signal"
     class="value signal">
WAIT
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
<div class="label">CONFIDENCE</div>
<div id="confidence"
     class="value">
0%
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
<div class="label">ENTRY WINDOW</div>
<div id="window"
     class="value">
12s
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
<div class="label">SCREEN</div>
<div id="screen"
     class="value">
WAITING
</div>
</div>

<div class="card analysis">

<div class="label">
MARKET ANALYSIS
</div>

<div id="analysis"
     class="value">
Waiting...
</div>

</div>

<div class="card ind">

<div class="label">
INDICATORS
</div>

EMA 9:
<span id="ema9">0.00000</span>
&nbsp;|&nbsp;

EMA 20:
<span id="ema20">0.00000</span>
&nbsp;|&nbsp;

EMA 50:
<span id="ema50">0.00000</span>
&nbsp;|&nbsp;

RSI:
<span id="rsi">0.00</span>
&nbsp;|&nbsp;

MACD:
<span id="macd">0.00000</span>
&nbsp;|&nbsp;

CCI:
<span id="cci">0.00</span>
&nbsp;|&nbsp;

ATR:
<span id="atr">0.00000</span>

</div>

<div class="card analysis">

<div class="label">
LAST FRAME
</div>

<div id="lastframe"
     class="value">
--
</div>

</div>

</div>

</div>

<script>

function fmt(value, digits) {

    return Number(
        value || 0
    ).toFixed(digits);

}

async function refresh() {

    try {

        const response =
            await fetch(
                "/api/state",
                {
                    cache: "no-store"
                }
            );

        const s =
            await response.json();

        const live =
            s.feed === "LIVE";

        const status =
            document.getElementById(
                "status"
            );

        status.textContent =
            "FEED: " + s.feed;

        status.className =
            "status " +
            (live ? "live" : "dead");

        document.getElementById(
            "asset"
        ).textContent =
            s.asset;

        document.getElementById(
            "signal"
        ).textContent =
            s.signal;

        document.getElementById(
            "price"
        ).textContent =
            fmt(s.price, 6);

        document.getElementById(
            "confidence"
        ).textContent =
            (s.confidence || 0) + "%";

        document.getElementById(
            "entry"
        ).textContent =
            fmt(s.entry, 6);

        document.getElementById(
            "window"
        ).textContent =
            (s.entry_window || 0) + "s";

        document.getElementById(
            "candles"
        ).textContent =
            s.candles || 0;

        document.getElementById(
            "screen"
        ).textContent =
            s.image_received && live
            ? "LIVE"
            : "WAITING";

        document.getElementById(
            "analysis"
        ).textContent =
            s.analysis || "--";

        document.getElementById(
            "ema9"
        ).textContent =
            fmt(s.ema9, 5);

        document.getElementById(
            "ema20"
        ).textContent =
            fmt(s.ema20, 5);

        document.getElementById(
            "ema50"
        ).textContent =
            fmt(s.ema50, 5);

        document.getElementById(
            "rsi"
        ).textContent =
            fmt(s.rsi, 2);

        document.getElementById(
            "macd"
        ).textContent =
            fmt(s.macd, 5);

        document.getElementById(
            "cci"
        ).textContent =
            fmt(s.cci, 2);

        document.getElementById(
            "atr"
        ).textContent =
            fmt(s.atr, 5);

        document.getElementById(
            "lastframe"
        ).textContent =
            s.last_frame || "--";

    } catch (error) {

        const status =
            document.getElementById(
                "status"
            );

        status.textContent =
            "FEED: CONNECTION ERROR";

        status.className =
            "status dead";

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
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
