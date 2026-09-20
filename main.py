from flask import Flask, request, jsonify, Response
from PIL import Image, ImageStat, ImageFilter
from io import BytesIO
from datetime import datetime, timezone
import threading
import base64
import re
import time

app = Flask(__name__)

# Allow normal Pocket Option screenshots.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

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

    "frame_width": 0,
    "frame_height": 0,
    "frame_bytes": 0,

    "visual_brightness": 0.0,
    "visual_edges": 0.0,

    "trades": 0,
    "wins": 0,
    "losses": 0,

    "last_error": ""
}

latest_image = None


def utc_now():
    return datetime.now(timezone.utc)


def timestamp():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def validate_image(data):
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

        return image_format, width, height, image

    except Exception as exc:
        raise ValueError(str(exc))


def visual_analysis(image):
    """
    Basic image health analysis.

    This does NOT pretend to calculate financial indicators
    from pixels. It verifies that a real screen/chart image
    is arriving and measures visual activity.
    """

    try:
        rgb = image.convert("RGB")

        small = rgb.resize((160, 160))

        stat = ImageStat.Stat(small)
        brightness = sum(stat.mean) / 3.0

        gray = small.convert("L")

        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)

        edge_value = edge_stat.mean[0]

        return round(brightness, 2), round(edge_value, 2)

    except Exception:
        return 0.0, 0.0


def mark_frame_live(data, image):
    global latest_image

    brightness, edges = visual_analysis(image)

    with lock:
        latest_image = bytes(data)

        state["feed"] = "LIVE"
        state["image_received"] = True
        state["last_frame"] = timestamp()
        state["frames"] += 1

        state["frame_width"] = image.width
        state["frame_height"] = image.height
        state["frame_bytes"] = len(data)

        state["visual_brightness"] = brightness
        state["visual_edges"] = edges

        state["last_error"] = ""

        state["analysis"] = (
            "Pocket Option screen captured successfully. "
            "Waiting for readable market values..."
        )


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

            result["frame_age"] = round(age, 1)

            if age > 20:
                result["feed"] = "STALE"

                if result["image_received"]:
                    result["analysis"] = (
                        "Screen feed is stale. "
                        "Waiting for a new Pocket Option frame..."
                    )

            else:
                result["feed"] = "LIVE"

        except (TypeError, ValueError):
            result["feed"] = "DISCONNECTED"
            result["frame_age"] = -1

    else:
        result["frame_age"] = -1

    return result


def normalize_asset(value):
    if not value:
        return None

    raw = str(value).strip().upper()

    raw = raw.replace(" ", "")
    raw = raw.replace("/", "")

    for asset in ASSETS:

        a = asset.upper().replace("/", "")

        if raw == a:
            return asset

        if raw == a.replace("_OTC", "OTC"):
            return asset

    return None


def parse_price(text):
    if not text:
        return None

    cleaned = text.replace(",", "")

    candidates = re.findall(
        r"\b\d{1,6}(?:\.\d{1,8})?\b",
        cleaned
    )

    values = []

    for item in candidates:
        try:
            number = float(item)

            if number > 0:
                values.append(number)

        except ValueError:
            pass

    if not values:
        return None

    # Ignore obvious UI numbers.
    filtered = [
        x for x in values
        if x not in (0, 1, 5, 10, 12, 20, 30, 50, 60, 100, 300)
    ]

    if filtered:
        return filtered[0]

    return values[0]


def update_from_ocr(text):
    """
    Receives OCR text from the dashboard browser.

    The browser performs OCR because the Render service should
    not require a system-level Tesseract installation.
    """

    if not text:
        return

    text = str(text)

    found_asset = None

    upper = text.upper().replace("/", "")

    for asset in ASSETS:

        normal = asset.upper().replace("/", "")

        if normal in upper:
            found_asset = asset
            break

        if normal.replace("_OTC", "OTC") in upper:
            found_asset = asset
            break

    found_price = parse_price(text)

    with lock:

        if found_asset:
            state["asset"] = found_asset

        if found_price is not None:
            state["price"] = found_price

            if state["entry"] == 0:
                state["entry"] = found_price

        if found_asset or found_price is not None:

            state["analysis"] = (
                "Screen feed LIVE. "
                "Market text detected from Pocket Option."
            )

        else:

            state["analysis"] = (
                "Screen feed LIVE. "
                "Chart captured, but readable market text "
                "was not detected yet."
            )

        state["last_error"] = ""


HTML = """<!doctype html>
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

.warn {
    color: #ffd36e;
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

.screen-card {
    margin-top: 10px;
}

#screen {
    width: 100%;
    max-height: 600px;
    object-fit: contain;
    background: #000;
    border-radius: 6px;
    display: none;
}

.capture-info {
    margin-top: 8px;
    color: #aaa;
    font-size: 12px;
}

@media(max-width:700px) {

    .grid {
        grid-template-columns: repeat(2, 1fr);
    }

    .value {
        font-size: 21px;
    }
}

</style>

<!-- Browser-side OCR.
     This lets the Render server remain Python/Pillow only. -->
<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>

</head>

<body>

<header>

<h1>ALUCARD</h1>

<div class="sub">
GOTHIC MARKET INTELLIGENCE — V2.1
</div>

</header>


<nav>

<button onclick="showTab('signals')">
Signals
</button>

<button onclick="showTab('trades')">
Trades
</button>

<button onclick="showTab('performance')">
Performance
</button>

<button onclick="showTab('settings')">
Settings
</button>

</nav>


<main>

<div class="status">

Feed:
<b id="feed" class="dead">DISCONNECTED</b>

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
<div class="value signal" id="signal">
WAIT
</div>
</div>

<div class="card">
<div class="label">Price</div>
<div class="value" id="price">
0.000000
</div>
</div>

<div class="card">
<div class="label">Confidence</div>
<div class="value" id="confidence">
0%
</div>
</div>

<div class="card">
<div class="label">Entry</div>
<div class="value" id="entry">
0.000000
</div>
</div>

<div class="card">
<div class="label">Entry Window</div>
<div class="value" id="window">
12s
</div>
</div>

<div class="card">
<div class="label">Candles</div>
<div class="value" id="candles">
0
</div>
</div>

<div class="card">
<div class="label">EMA 9</div>
<div class="value" id="ema9">
0.000000
</div>
</div>

<div class="card">
<div class="label">EMA 20</div>
<div class="value" id="ema20">
0.000000
</div>
</div>

<div class="card">
<div class="label">EMA 50</div>
<div class="value" id="ema50">
0.000000
</div>
</div>

<div class="card">
<div class="label">RSI</div>
<div class="value" id="rsi">
0.00
</div>
</div>

<div class="card">
<div class="label">ATR</div>
<div class="value" id="atr">
0.000000
</div>
</div>

<div class="card">
<div class="label
