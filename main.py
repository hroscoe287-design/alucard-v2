import os
import io
import time
from collections import deque

import numpy as np
from PIL import Image
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

TOKEN = (
    os.getenv("RYU_FEED_TOKEN")
    or os.getenv("ALUCARD_FEED_TOKEN")
    or ""
)

VERSION = "ALUCARD-ANALYTICS-4.0"

# ============================================================
# STATE
# ============================================================

state = {
    "feed": "DISCONNECTED",
    "asset": "UNKNOWN",
    "price": 0.0,

    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": 12,

    "candles": 0,
    "image_received": False,

    "last_feed": 0.0,

    "analysis": "Waiting for screen feed...",

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,

    "rsi": 0.0,
    "atr": 0.0,
    "cci": 0.0,

    "macd": 0.0,
    "macd_signal": 0.0,

    "sar": 0.0,

    "fractal": 2,

    "payout": 0,
}

prices = deque(maxlen=300)

screen_frame = {
    "bytes": None,
    "mime": "image/jpeg",
    "time": 0.0,
}

# ============================================================
# HELPERS
# ============================================================

def auth_ok():
    if not TOKEN:
        return True

    supplied = (
        request.headers.get("X-RYU-TOKEN")
        or request.headers.get("X-ALUCARD-TOKEN")
    )

    return supplied == TOKEN


def ema(values, period):
    if len(values) == 0:
        return 0.0

    alpha = 2.0 / (period + 1.0)

    value = float(values[0])

    for v in values[1:]:
        value = alpha * float(v) + (1.0 - alpha) * value

    return value


def calculate_indicators(values):
    if len(values) == 0:
        return (
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )

    x = np.asarray(values, dtype=float)

    ema9 = ema(x, 9)
    ema20 = ema(x, 20)
    ema50 = ema(x, 50)

    if len(x) < 2:
        return (
            ema9,
            ema20,
            ema50,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )

    differences = np.diff(x)

    gains = np.maximum(differences, 0)
    losses = np.maximum(-differences, 0)

    period = min(14, len(differences))

    avg_gain = float(gains[-period:].mean())
    avg_loss = float(losses[-period:].mean())

    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    true_ranges = np.abs(differences)

    atr = (
        float(true_ranges[-period:].mean())
        if len(true_ranges)
        else 0.0
    )

    recent = x[-period:]

    sma = float(recent.mean())
    deviation = float(recent.std())

    if deviation == 0:
        cci = 0.0
    else:
        cci = float(
            (x[-1] - sma)
            / (0.015 * deviation)
        )

    macd = ema(x, 12) - ema(x, 26)

    if len(x) >= 26:

        macd_history = []

        for i in range(26, len(x) + 1):
            section = x[:i]

            value = (
                ema(section, 12)
                - ema(section, 26)
            )

            macd_history.append(value)

        macd_signal = ema(
            np.asarray(macd_history),
            9,
        )

    else:
        macd_signal = macd

    return (
        ema9,
        ema20,
        ema50,
        rsi,
        atr,
        cci,
        macd,
        macd_signal,
    )


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze_market():

    values = list(prices)

    if not values:
        return

    (
        ema9,
        ema20,
        ema50,
        rsi,
        atr,
        cci,
        macd,
        macd_signal,
    ) = calculate_indicators(values)

    call_score = 0
    put_score = 0

    # EMA 9 / 20
    if ema9 > ema20:
        call_score += 20
    elif ema9 < ema20:
        put_score += 20

    # EMA 20 / 50
    if ema20 > ema50:
        call_score += 20
    elif ema20 < ema50:
        put_score += 20

    # MACD
    if macd > macd_signal:
        call_score += 20
    elif macd < macd_signal:
        put_score += 20

    # RSI
    if rsi > 50:
        call_score += 10
    elif rsi < 50:
        put_score += 10

    # CCI
    if cci > 0:
        call_score += 10
    elif cci < 0:
        put_score += 10

    # Short-term price direction
    if len(values) >= 3:

        if (
            values[-1]
            > values[-2]
            > values[-3]
        ):
            call_score += 20

        elif (
            values[-1]
            < values[-2]
            < values[-3]
        ):
            put_score += 20

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if (
        call_score >= 70
        and call_score > put_score
    ):
        signal = "CALL"
        confidence = call_score

    elif (
        put_score >= 70
        and put_score > call_score
    ):
        signal = "PUT"
        confidence = put_score

    else:
        signal = "WAIT"
        confidence = abs(
            call_score - put_score
        )

    last_price = float(values[-1])

    with app.app_context():

        state.update(
            {
                "signal": signal,
                "confidence": int(confidence),
                "entry": last_price,

                "analysis": (
                    f"{signal} setup | "
                    f"EMA trend + MACD + RSI + CCI"
                ),

                "ema9": float(ema9),
                "ema20": float(ema20),
                "ema50": float(ema50),

                "rsi": float(rsi),
                "atr": float(atr),
                "cci": float(cci),

                "macd": float(macd),
                "macd_signal": float(macd_signal),

                "candles": len(values),

                "feed": "LIVE",
                "image_received": (
                    screen_frame["bytes"] is not None
                ),
            }
        )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
def home():
    return render_template_string(HTML)


# ============================================================
# STATE API
# ============================================================

@app.route("/api/state")
def api_state():

    current = dict(state)

    age = time.time() - current["last_feed"]

    if current["last_feed"] == 0:
        current["feed"] = "DISCONNECTED"

    elif age > 15:

        current["feed"] = "DISCONNECTED"

        current["analysis"] = (
            "Screen feed stale — "
            "waiting for new frame"
        )

    return jsonify(current)


# ============================================================
# FEED API
#
# Supports:
#
# 1. JSON
# 2. image/jpeg
# 3. image/png
# 4. multipart image/file
# ============================================================

@app.route("/api/feed", methods=["POST"])
def feed():

    if not auth_ok():

        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Unauthorized",
                }
            ),
            401,
        )

    content_type = (
        request.content_type
        or ""
    )

    # ========================================================
    # IMAGE FEED
    # ========================================================

    if (
        content_type.startswith("image/")
        or "multipart/form-data"
        in content_type
    ):

        data = None
        mime = "image/jpeg"

        if "multipart/form-data" in content_type:

            file_obj = (
                request.files.get("image")
                or request.files.get("file")
            )

            if file_obj is None:

                try:
                    file_obj = next(
                        iter(
                            request.files.values()
                        )
                    )
                except StopIteration:
                    file_obj = None

            if file_obj is not None:

                data = file_obj.read()

                if file_obj.mimetype:
                    mime = file_obj.mimetype

        else:

            data = request.get_data()

            if content_type:
                mime = content_type

        if not data:

            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "No image received"
                        ),
                    }
                ),
                400,
            )

        # ----------------------------------------------------
        # Validate and normalize image using PIL.
        # NO OPENCV / CV2 REQUIRED.
        # ----------------------------------------------------

        try:

            image = Image.open(
                io.BytesIO(data)
            ).convert("RGB")

            image.thumbnail(
                (1280, 1280)
            )

            output = io.BytesIO()

            image.save(
                output,
                format="JPEG",
                quality=82,
                optimize=True,
            )

            data = output.getvalue()

        except Exception as exc:

            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Invalid image: "
                            + str(exc)
                        ),
                    }
                ),
                400,
            )

        # ----------------------------------------------------
        # Save latest screen frame
        # ----------------------------------------------------

        screen_frame["bytes"] = data
        screen_frame["mime"] = "image/jpeg"
        screen_frame["time"] = time.time()

        state.update(
            {
                "feed": "LIVE",
                "last_feed": time.time(),
                "image_received": True,

                "analysis": (
                    "Screen feed LIVE — "
                    "chart captured"
                ),
            }
        )

        return jsonify(
            {
                "ok": True,
                "message": (
                    "Screen image accepted"
                ),
                "state": dict(state),
            }
        )

    # ========================================================
    # JSON FEED
    # ========================================================

    body = request.get_json(
        silent=True
    )

    if body:

        if "asset" in body:
            state["asset"] = body["asset"]

        if "price" in body:

            try:

                price = float(
                    body["price"]
                )

                state["price"] = price

                prices.append(price)

            except Exception:
                pass

        if "signal" in body:
            state["signal"] = body["signal"]

        if "confidence" in body:

            try:
                state["confidence"] = int(
                    body["confidence"]
                )
            except Exception:
                pass

        if "entry" in body:

            try:
                state["entry"] = float(
                    body["entry"]
                )
            except Exception:
                pass

        if "entry_window" in body:

            try:
                state["entry_window"] = int(
                    body["entry_window"]
                )
            except Exception:
                pass

        if "candles" in body:

            try:
                state["candles"] = int(
                    body["candles"]
                )
            except Exception:
                pass

        if "payout" in body:

            try:
                state["payout"] = int(
                    body["payout"]
                )
            except Exception:
                pass

        state["feed"] = "LIVE"
        state["last_feed"] = time.time()

        analyze_market()

        return jsonify(
            {
                "ok": True,
                "message": (
                    "JSON feed accepted"
                ),
                "state": dict(state),
            }
        )

    # ========================================================
    # NOTHING RECEIVED
    # ========================================================

    return (
        jsonify(
            {
                "ok": False,
                "error": (
                    "No JSON data or image received"
                ),
            }
        ),
        400,
    )


# ============================================================
# LATEST SCREEN IMAGE
# ============================================================

@app.route("/api/screen")
def screen():

    data = screen_frame["bytes"]
    mime = screen_frame["mime"]

    if not data:

        return (
            "No screen frame",
            404,
        )

    return (
        data,
        200,
        {
            "Content-Type": mime,
            "Cache-Control": "no-store",
        },
    )


# ============================================================
# HTML
# ============================================================

HTML = r"""
<!doctype html>

<html>

<head>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>ALUCARD</title>

<style>

body{
    margin:0;
    background:#050707;
    color:#ddd;
    font-family:Arial,sans-serif;
}

.wrap{
    max-width:1100px;
    margin:auto;
    padding:16px;
}

h1{
    color:#d33;
    margin:0;
}

.sub{
    color:#888;
    margin-top:3px;
}

.top{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:10px;
}

select,
button{
    background:#111;
    color:#eee;
    border:1px solid #444;
    padding:10px;
    border-radius:8px;
}

select{
    min-width:150px;
}

.live{
    margin-top:14px;
    padding:10px;
    border-radius:8px;
    background:#111;
    border:1px solid #333;
}

.ok{
    color:#6f6;
}

.bad{
    color:#f66;
}

.grid{
    display:grid;
    grid-template-columns:
        repeat(4,1fr);
    gap:10px;
    margin-top:14px;
}

.card{
    background:#0d1111;
    border:1px solid #272d2d;
    border-radius:10px;
    padding:12px;
}

.big{
    font-size:26px;
    font-weight:bold;
    margin-top:5px;
}

.tabs{
    display:flex;
    gap:6px;
    overflow:auto;
    margin:14px 0;
}

.tab{
    white-space:nowrap;
}

.analytics{
    display:grid;
    grid-template-columns:
        repeat(4,1fr);
    gap:8px;
}

.screen{
    margin-top:14px;
    background:#000;
    border:1px solid #333;
    border-radius:10px;
    overflow:hidden;
    text-align:center;
    min-height:100px;
}

.screen img{
    max-width:100%;
    max-height:500px;
}

.analysis{
    margin-top:12px;
}

@media(max-width:700px){

    .grid,
    .analytics{
        grid-template-columns:
            repeat(2,1fr);
    }

}

</style>

</head>

<body>

<div class="wrap">

<div class="top">

<div>

<h1>ALUCARD</h1>

<div class="sub">
GOTHIC MARKET INTELLIGENCE
</div>

</div>

<select id="assetMenu">

<option value="Forex">
Forex
</option>

<option>
EUR/USD
</option>

<option>
GBP/USD
</option>

<option>
USD/JPY
</option>

<option>
AUD/USD
</option>

<option>
USD/CAD
</option>

<option>
USD/CHF
</option>

<option>
NZD/USD
</option>

<option>
EUR/GBP
</option>

<option>
EUR/JPY
</option>

<option>
GBP/JPY
</option>

<option>
EURUSD OTC
</option>

<option>
GBPUSD OTC
</option>

<option>
USDJPY OTC
</option>

<option>
AUDUSD OTC
</option>

<option>
EURJPY OTC
</option>

<option>
GBPJPY OTC
</option>

<option>
Crypto
</option>

<option>
Bitcoin
</option>

<option>
Ethereum
</option>

<option>
Gold
</option>

<option>
Silver
</option>

<option>
Oil
</option>

<option>
Natural Gas
</option>

<option>
Stocks
</option>

<option>
Indices
</option>

</select>

</div>


<div id="live"
class="live">

Feed: DISCONNECTED

</div>


<div class="grid">


<div class="card">

Signal

<div id="sig"
class="big">

WAIT

</div>

</div>


<div class="card">

Price

<div id="price"
class="big">

0.000000

</div>

</div>


<div class="card">

Confidence

<div id="conf"
class="big">

0%

</div>

</div>


<div class="card">

Entry Window

<div id="win"
class="big">

12s

</div>

</div>


</div>


<div class="tabs">

<button class="tab">
Signals
</button>

<button class="tab">
Trades
</button>

<button class="tab">
Performance
</button>

<button class="tab">
Settings
</button>

</div>


<h3>
Analytics
</h3>


<div class="analytics">


<div class="card">

EMA 9

<div id="e9">
0.000000
</div>

</div>


<div class="card">

EMA 20

<div id="e20">
0.000000
</div>

</div>


<div class="card">

EMA 50

<div id="e50">
0.000000
</div>

</div>


<div class="card">

RSI

<div id="rsi">
0.00
</div>

</div>


<div class="card">

ATR

<div id="atr">
0.000000
</div>

</div>


<div class="card">

CCI

<div id="cci">
0.00
</div>

</div>


<div class="card">

MACD

<div id="macd">
0.000000
</div>

</div>


<div class="card">

Fractal

<div>
2
</div>

</div>


</div>


<div class="card analysis">

<b id="analysis">
Waiting for screen feed...
</b>

<br>

<small id="candles">
Candles: 0 | Screen: WAITING
</small>

</div>


<div class="screen">

<img
id="screen"
src="/api/screen"
style="display:none"
onerror="this.style.display='none'"
>

</div>


</div>


<script>

async function updateDashboard(){

    try{

        const response =
            await fetch(
                "/api/state",
                {
                    cache:"no-store"
                }
            );

        const s =
            await response.json();


        document.getElementById(
            "live"
        ).textContent =
            "Feed: " +
            s.feed +
            "   Asset: " +
            (s.asset || "UNKNOWN");


        const live =
            document.getElementById(
                "live"
            );

        if(s.feed === "LIVE"){

            live.className =
                "live ok";

        }else{

            live.className =
                "live bad";

        }


        document.getElementById(
            "sig"
        ).textContent =
            s.signal || "WAIT";


        document.getElementById(
            "price"
        ).textContent =
            Number(
                s.price || 0
            ).toFixed(6);


        document.getElementById(
            "conf"
        ).textContent =
            (s.confidence || 0)
            + "%";


        document.getElementById(
            "win"
        ).textContent =
            (s.entry_window || 12)
            + "s";


        document.getElementById(
            "e9"
        ).textContent =
            Number(
                s.ema9 || 0
            ).toFixed(6);


        document.getElementById(
            "e20"
        ).textContent =
            Number(
                s.ema20 || 0
            ).toFixed(6);


        document.getElementById(
            "e50"
        ).textContent =
            Number(
                s.ema50 || 0
            ).toFixed(6);


        document.getElementById(
            "rsi"
        ).textContent =
            Number(
                s.rsi || 0
            ).toFixed(2);


        document.getElementById(
            "atr"
        ).textContent =
            Number(
                s.atr || 0
            ).toFixed(6);


        document.getElementById(
            "cci"
        ).textContent =
            Number(
                s.cci || 0
            ).toFixed(2);


        document.getElementById(
            "macd"
        ).textContent =
            Number(
                s.macd || 0
            ).toFixed(6);


        document.getElementById(
            "analysis"
        ).textContent =
            s.analysis || "";


        document.getElementById(
            "candles"
        ).textContent =
            "Candles: " +
            (s.candles || 0) +
            " | Screen: " +
            (
                s.image_received
                ? "LIVE"
                : "WAITING"
            );


        if(s.image_received){

            const screen =
                document.getElementById(
                    "screen"
                );

            screen.style.display =
                "block";

            screen.src =
                "/api/screen?t=" +
                Date.now();
        }

    }catch(error){

        console.log(error);

    }

}


setInterval(
    updateDashboard,
    2000
);

updateDashboard();

</script>

</body>

</html>
"""


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
        )
