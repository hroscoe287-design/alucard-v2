from flask import Flask, request, jsonify, Response
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone
import threading

app = Flask(__name__)
lock = threading.Lock()

ASSETS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "GBPCHF", "AUDJPY", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "GBPNZD", "AUDCAD",
    "AUDCHF", "AUDNZD", "CADCHF", "NZDCAD", "NZDCHF",

    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "USDCHF_otc",
    "AUDUSD_otc", "USDCAD_otc", "NZDUSD_otc", "EURGBP_otc",
    "EURJPY_otc", "GBPJPY_otc", "GBPCHF_otc", "AUDJPY_otc",
    "CADJPY_otc", "CHFJPY_otc", "EURAUD_otc", "EURCAD_otc",
    "EURNZD_otc", "GBPAUD_otc", "GBPCAD_otc", "GBPNZD_otc",
    "AUDCAD_otc", "AUDCHF_otc", "AUDNZD_otc", "CADCHF_otc",
    "NZDCAD_otc", "NZDCHF_otc",

    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD",
    "BTCUSD_otc", "ETHUSD_otc", "LTCUSD_otc", "XRPUSD_otc",

    "GOLD", "SILVER", "USOIL", "UKOIL", "NATGAS",

    "AAPL", "TSLA", "AMZN", "MSFT", "GOOGL", "META",

    "NASDAQ", "SP500", "DOW", "DAX", "FTSE"
]

state = {
    "asset": "UNKNOWN",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": 0.0,
    "entry_window": 12,
    "candles": 0,

    "feed": "DISCONNECTED",
    "image_received": False,
    "analysis": "Waiting for Pocket Option screen feed...",

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "rsi": 0.0,
    "atr": 0.0,
    "cci": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "fractal": 2,

    "payout": 0,

    "last_frame": None,
    "frames": 0,

    "trades": 0,
    "wins": 0,
    "losses": 0,

    "last_error": ""
}


def utc_now():
    return datetime.now(timezone.utc)


def timestamp():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def validate_image(data):
    """
    Verify that the received bytes are actually an image.
    This is the critical fix for /api/frame.
    """
    try:
        image = Image.open(BytesIO(data))
        image.load()

        image_format = image.format
        width, height = image.size

        if image_format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError(
                "Unsupported image format: " + str(image_format)
            )

        if width < 10 or height < 10:
            raise ValueError("Image dimensions are too small")

        return image_format, width, height

    except Exception as exc:
        raise ValueError(str(exc))


def mark_frame_live():
    with lock:
        state["feed"] = "LIVE"
        state["image_received"] = True
        state["last_frame"] = timestamp()
        state["frames"] += 1
        state["last_error"] = ""


def get_state():
    with lock:
        result = dict(state)

    if result["last_frame"]:
        try:
            last = datetime.strptime(
                result["last_frame"],
                "%Y-%m-%d %H:%M:%S UTC"
            ).replace(tzinfo=timezone.utc)

            age = (utc_now() - last).total_seconds()

            if age > 20:
                result["feed"] = "DISCONNECTED"

        except (TypeError, ValueError):
            result["feed"] = "DISCONNECTED"

    return result


HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>ALUCARD V2.1</title>

<style>

body {
    margin: 0;
    background: #08070b;
    color: #eeeeee;
    font-family: Arial, sans-serif;
}

header {
    padding: 16px;
    border-bottom: 1px solid #332c3a;
    background: #100d14;
}

h1 {
    margin: 0;
    font-size: 25px;
    letter-spacing: 2px;
}

.sub {
    color: #a99caf;
    font-size: 12px;
    margin-top: 4px;
}

nav {
    display: flex;
    gap: 6px;
    padding: 10px;
    background: #0d0a10;
    overflow-x: auto;
}

nav button {
    background: #17121b;
    color: #eeeeee;
    border: 1px solid #3d3344;
    padding: 10px 14px;
    border-radius: 6px;
}

main {
    max-width: 1100px;
    margin: auto;
    padding: 12px;
}

.status,
.card {
    background: #100d14;
    border: 1px solid #352c3c;
    border-radius: 8px;
    padding: 13px;
}

.status {
    margin-bottom: 10px;
}

.live {
    color: #79ff99;
}

.dead {
    color: #ff7180;
}

.grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
}

.label {
    font-size: 11px;
    color: #a99caf;
    text-transform: uppercase;
}

.value {
    font-size: 25px;
    margin-top: 5px;
}

.signal {
    font-weight: bold;
    font-size: 30px;
}

select {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    background: #17131b;
    color: #eeeeee;
    border: 1px solid #423748;
    border-radius: 6px;
}

.panel {
    display: none;
}

.panel.active {
    display: block;
}

.small {
    color: #aaaaaa;
    font-size: 13px;
}

@media(max-width:700px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
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
    <button onclick="showTab('signals')">Signals</button>
    <button onclick="showTab('trades')">Trades</button>
    <button onclick="showTab('performance')">Performance</button>
    <button onclick="showTab('settings')">Settings</button>
</nav>

<main>

<div class="status">

    Feed:
    <b id="feed">DISCONNECTED</b>

    &nbsp; | &nbsp;

    Asset:
    <b id="assetTop">UNKNOWN</b>

    <br>

    <span class="small" id="last">
        Waiting for Pocket Option screen feed...
    </span>

</div>


<section id="signals" class="panel active">

<div class="card" style="margin-bottom:10px">

    <div class="label">
        Currency / Asset
    </div>

    <select id="assetSel"></select>

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
    <div class="value" id="window">12s</div>
</div>

<div class="card">
    <div class="label">Candles</div>
    <div class="value" id="candles">0</div>
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
    <div class="label">ATR</div>
    <div class="value" id="atr">0.000000</div>
</div>

<div class="card">
    <div class="label">CCI</div>
    <div class="value" id="cci">0.00</div>
</div>

</div>


<div class="card" style="margin-top:10px">

    <div class="label">
        Analysis
    </div>

    <div id="analysis">
        Waiting for Pocket Option screen feed...
    </div>

</div>

</section>


<section id="trades" class="panel">

<div class="card">

    <div class="value" id="tradeStats">
        Trades: 0 | Wins: 0 | Losses: 0
    </div>

</div>

</section>


<section id="performance" class="panel">

<div class="card">

    <div class="value" id="perf">
        No completed trades.
    </div>

</div>

</section>


<section id="settings" class="panel">

<div class="card">

    <div class="small">

        Signal threshold: 78%
        &nbsp; | &nbsp;
        Entry window: 12s
        &nbsp; | &nbsp;
        Expiry: 300s

    </div>

</div>

</section>

</main>


<script>

const assets = __ASSETS__;

document.getElementById("assetSel").innerHTML =
    assets.map(function(asset) {
        return "<option>" + asset + "</option>";
    }).join("");


function showTab(id) {

    document
        .querySelectorAll(".panel")
        .forEach(function(panel) {
            panel.classList.remove("active");
        });

    document
        .getElementById(id)
        .classList.add("active");
}


function put(id, value) {
    document.getElementById(id).textContent = value;
}


async function refresh() {

    try {

        const response = await fetch(
            "/api/state",
            {cache: "no-store"}
        );

        const s = await response.json();


        put(
            "feed",
            s.feed || "DISCONNECTED"
        );

        document.getElementById("feed").className =
            s.feed === "LIVE" ? "live" : "dead";


        put(
            "assetTop",
            s.asset || "UNKNOWN"
        );


        if (s.asset) {
            document.getElementById("assetSel").value =
                s.asset;
        }


        put(
            "last",
            s.feed === "LIVE"
                ? "LIVE — last frame: " +
                  (s.last_frame || "now")
                : (
                    s.analysis ||
                    "Waiting for Pocket Option screen feed..."
                  )
        );


        put(
            "signal",
            s.signal || "WAIT"
        );

        put(
            "price",
            Number(s.price || 0).toFixed(6)
        );

        put(
            "confidence",
            (s.confidence || 0) + "%"
        );

        put(
            "entry",
            Number(s.entry || 0).toFixed(6)
        );

        put(
            "window",
            (s.entry_window || 12) + "s"
        );

        put(
            "candles",
            s.candles || 0
        );


        ["ema9", "ema20", "ema50", "atr"]
            .forEach(function(key) {

                put(
                    key,
                    Number(s[key] || 0).toFixed(6)
                );

            });


        ["rsi", "cci"]
            .forEach(function(key) {

                put(
                    key,
                    Number(s[key] || 0).toFixed(2)
                );

            });


        put(
            "analysis",
            s.analysis ||
            "Waiting for Pocket Option screen feed..."
        );


        put(
            "tradeStats",

            "Trades: " + (s.trades || 0) +
            " | Wins: " + (s.wins || 0) +
            " | Losses: " + (s.losses || 0)
        );


        const total =
            (s.wins || 0) +
            (s.losses || 0);


        put(
            "perf",

            total
                ? "Completed: " +
                  total +
                  " | Win rate: " +
                  ((s.wins / total) * 100).toFixed(1) +
                  "%"
                : "No completed trades."
        );

    } catch (error) {

        // Keep the dashboard alive if a poll fails.

    }
}


setInterval(refresh, 1000);

refresh();

</script>

</body>
</html>
"""

HTML = HTML.replace(
    "__ASSETS__",
    repr(ASSETS)
)


@app.get("/")
def home():
    return Response(
        HTML,
        mimetype="text/html"
    )


@app.get("/api/state")
def api_state():
    return jsonify(get_state())


@app.get("/api/health")
def health():
    return jsonify(
        ok=True,
        service="alucard-v2.1",
        frame_endpoint="/api/frame"
    )


@app.post("/api/frame")
def api_frame():

    data = None
    source = "none"

    # EXACTLY matches the existing bridge:
    #
    # files={
    #     "image": (
    #         "alucard_live.jpg",
    #         image_file,
    #         "image/jpeg"
    #     )
    # }

    if "image" in request.files:

        data = request.files["image"].read()
        source = "multipart:image"

    elif "frame" in request.files:

        data = request.files["frame"].read()
        source = "multipart:frame"

    elif request.data:

        data = request.data
        source = "raw"


    if not data:

        return jsonify(
            ok=False,
            error="No image received",
            detail="POST a JPEG as multipart field 'image'"
        ), 400


    try:

        image_format, width, height = \
            validate_image(data)

    except ValueError as exc:

        with lock:
            state["last_error"] = str(exc)

        return jsonify(
            ok=False,
            error="Invalid image",
            detail=str(exc)
        ), 400


    mark_frame_live()


    return jsonify(
        ok=True,
        message="Image frame accepted",
        feed="LIVE",
        source=source,
        format=image_format,
        width=width,
        height=height,
        frames=state["frames"]
    )


@app.post("/api/feed")
def api_feed():

    payload = request.get_json(silent=True)


    if not isinstance(payload, dict):

        return jsonify(
            ok=False,
            error="No JSON data received"
        ), 400


    integer_fields = {
        "candles",
        "entry_window",
        "fractal"
    }

    number_fields = {
        "price",
        "confidence",
        "entry",
        "ema9",
        "ema20",
        "ema50",
        "rsi",
        "atr",
        "cci",
        "macd",
        "macd_signal",
        "payout"
    }


    with lock:

        for key in (
            "asset",
            "signal",
            "analysis"
        ):

            if key in payload:
                state[key] = str(payload[key])


        for key in integer_fields:

            if key in payload:

                try:
                    state[key] = int(
                        float(payload[key])
                    )

                except (TypeError, ValueError):
                    pass


        for key in number_fields:

            if key in payload:

                try:
                    state[key] = float(
                        payload[key]
                    )

                except (TypeError, ValueError):
                    pass


        state["feed"] = "LIVE"
        state["last_frame"] = timestamp()
        state["frames"] += 1
        state["last_error"] = ""


    return jsonify(
        ok=True,
        message="JSON feed accepted",
        state=get_state()
    )


@app.post("/api/reset")
def reset():

    with lock:

        state.update({

            "asset": "UNKNOWN",
            "price": 0.0,
            "signal": "WAIT",
            "confidence": 0,
            "entry": 0.0,
            "entry_window": 12,
            "candles": 0,

            "feed": "DISCONNECTED",
            "image_received": False,

            "analysis":
                "Waiting for Pocket Option screen feed...",

            "ema9": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "rsi": 0.0,
            "atr": 0.0,
            "cci": 0.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "fractal": 2,

            "payout": 0,

            "last_frame": None,
            "frames": 0,

            "trades": 0,
            "wins": 0,
            "losses": 0,

            "last_error": ""
        })


    return jsonify(ok=True)


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
