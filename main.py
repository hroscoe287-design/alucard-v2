import os
import time
import threading
from flask import Flask, request, jsonify, render_template_string, Response

app = Flask(__name__)

VERSION = "ALUCARD-2.3"
FEED_TIMEOUT = int(os.getenv("FRAME_TIMEOUT", "15"))
FEED_TOKEN = os.getenv("FEED_TOKEN", "")

ASSETS = {
    "FOREX": [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "USD/CHF",
        "AUD/USD",
        "USD/CAD",
        "NZD/USD",
        "EUR/GBP",
        "EUR/JPY",
        "EUR/CHF",
        "EUR/AUD",
        "EUR/CAD",
        "EUR/NZD",
        "GBP/JPY",
        "GBP/CHF",
        "GBP/AUD",
        "GBP/CAD",
        "GBP/NZD",
        "AUD/JPY",
        "AUD/CAD",
        "AUD/CHF",
        "AUD/NZD",
        "CAD/JPY",
        "CAD/CHF",
        "CHF/JPY",
        "NZD/JPY",
        "NZD/CAD",
        "NZD/CHF"
    ],

    "OTC FOREX": [
        "EUR/USD OTC",
        "GBP/USD OTC",
        "USD/JPY OTC",
        "USD/CHF OTC",
        "AUD/USD OTC",
        "USD/CAD OTC",
        "NZD/USD OTC",
        "EUR/GBP OTC",
        "EUR/JPY OTC",
        "EUR/CHF OTC",
        "EUR/AUD OTC",
        "EUR/CAD OTC",
        "GBP/JPY OTC",
        "GBP/CHF OTC",
        "GBP/AUD OTC",
        "AUD/JPY OTC",
        "AUD/CAD OTC",
        "AUD/CHF OTC",
        "CAD/JPY OTC",
        "CHF/JPY OTC",
        "NZD/JPY OTC"
    ],

    "CRYPTO": [
        "BTC/USD",
        "ETH/USD",
        "LTC/USD",
        "XRP/USD",
        "BCH/USD",
        "ADA/USD",
        "DOGE/USD",
        "SOL/USD",
        "DOT/USD",
        "BNB/USD",
        "BTC/USDT",
        "ETH/USDT"
    ],

    "COMMODITIES": [
        "Gold",
        "XAU/USD",
        "Silver",
        "XAG/USD",
        "Oil",
        "Brent Oil",
        "WTI Oil",
        "Natural Gas",
        "Copper"
    ],

    "INDICES": [
        "US30",
        "US100",
        "NASDAQ",
        "S&P 500",
        "SPX",
        "GER30",
        "DAX",
        "UK100",
        "FTSE 100",
        "JP225",
        "Nikkei 225",
        "AUS200",
        "FRA40",
        "EU50"
    ],

    "STOCKS": [
        "Apple",
        "Microsoft",
        "Amazon",
        "Alphabet",
        "Meta",
        "Tesla",
        "NVIDIA",
        "Netflix",
        "Intel",
        "AMD",
        "Coca-Cola",
        "McDonald's",
        "Boeing",
        "Disney",
        "Nike"
    ]
}

STATE = {
    "asset": "EUR/USD OTC",
    "price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry": None,
    "entry_window": 0,
    "candles": 0,
    "connected": False,
    "feed": "DISCONNECTED",
    "image_received": False,
    "frame_count": 0,
    "last_update": 0,
    "last_frame": 0,
    "scan": 0,
    "favorite_assets": [
        "EUR/USD OTC",
        "GBP/USD OTC",
        "USD/JPY OTC",
        "BTC/USD",
        "Gold"
    ]
}

FRAME_DATA = None
FRAME_CONTENT_TYPE = "image/jpeg"
LOCK = threading.Lock()


def authorized():
    if not FEED_TOKEN:
        return True

    for header in (
        "X-FEED-TOKEN",
        "X-ALUCARD-TOKEN",
        "X-RYU-TOKEN"
    ):
        if request.headers.get(header, "") == FEED_TOKEN:
            return True

    return False


def valid_image(data):
    if not data or len(data) < 20:
        return False

    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    return False


@app.route("/")
def index():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALUCARD SIGNAL BOT</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #050505;
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    text-align: center;
    border-bottom: 1px solid #333;
    background: #0b0b0b;
}

.title {
    font-size: 28px;
    font-weight: bold;
    letter-spacing: 3px;
}

.subtitle {
    color: #999;
    margin-top: 5px;
    letter-spacing: 2px;
    font-size: 12px;
}

.statusbar {
    display: flex;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 12px;
    background: #090909;
}

.status {
    padding: 8px 14px;
    border: 1px solid #333;
    border-radius: 20px;
    font-size: 13px;
}

.live {
    color: #7cff8a;
}

.dead {
    color: #ff5555;
}

.container {
    max-width: 1200px;
    margin: auto;
    padding: 15px;
}

.card {
    background: #0d0d0d;
    border: 1px solid #292929;
    border-radius: 12px;
    margin-bottom: 15px;
    overflow: hidden;
}

.cardtitle {
    padding: 12px 15px;
    border-bottom: 1px solid #292929;
    font-weight: bold;
    letter-spacing: 1px;
}

.selector {
    padding: 15px;
}

.search {
    width: 100%;
    padding: 13px;
    border-radius: 8px;
    border: 1px solid #444;
    background: #111;
    color: #fff;
    font-size: 15px;
    outline: none;
}

.categories {
    display: flex;
    gap: 7px;
    overflow-x: auto;
    padding: 12px 0;
}

.cat {
    flex: 0 0 auto;
    padding: 9px 13px;
    border-radius: 20px;
    border: 1px solid #444;
    background: #111;
    color: #ccc;
    cursor: pointer;
}

.cat.active {
    background: #222;
    color: #fff;
    border-color: #888;
}

.asset-list {
    display: grid;
    grid-template-columns: repeat(auto-fill,minmax(160px,1fr));
    gap: 7px;
    max-height: 330px;
    overflow-y: auto;
}

.asset {
    padding: 11px;
    background: #111;
    border: 1px solid #292929;
    border-radius: 7px;
    cursor: pointer;
    color: #ccc;
}

.asset:hover {
    background: #1b1b1b;
}

.asset.selected {
    border-color: #aaa;
    color: #fff;
}

.asset.favorite::before {
    content: "★ ";
}

.selectedbar {
    margin-top: 12px;
    padding: 12px;
    background: #151515;
    border-radius: 8px;
}

.screen {
    width: 100%;
    max-height: 700px;
    display: block;
    background: #111;
    object-fit: contain;
}

.waiting {
    padding: 70px 20px;
    text-align: center;
    color: #777;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit,minmax(140px,1fr));
    gap: 10px;
    padding: 15px;
}

.box {
    background: #111;
    border: 1px solid #292929;
    border-radius: 8px;
    padding: 15px;
}

.label {
    color: #777;
    font-size: 11px;
    text-transform: uppercase;
}

.value {
    margin-top: 6px;
    font-size: 21px;
    font-weight: bold;
}

.signal {
    font-size: 30px;
}

.footer {
    text-align: center;
    padding: 20px;
    color: #555;
    font-size: 11px;
}
</style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD SIGNAL BOT</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="statusbar">
    <div class="status" id="connection">
        FEED: DISCONNECTED
    </div>

    <div class="status" id="frames">
        FRAMES: 0
    </div>

    <div class="status">
        VERSION: ALUCARD-2.3
    </div>
</div>

<div class="container">

    <div class="card">
        <div class="cardtitle">
            ASSET / CURRENCY SELECTOR
        </div>

        <div class="selector">

            <input
                id="search"
                class="search"
                type="text"
                placeholder="Search currency, pair, crypto, stock..."
                oninput="renderAssets()"
            >

            <div id="categories" class="categories"></div>

            <div id="assetList" class="asset-list"></div>

            <div class="selectedbar">
                ACTIVE ASSET:
                <strong id="selectedAsset">EUR/USD OTC</strong>
            </div>

        </div>
    </div>

    <div class="card">
        <div class="cardtitle">
            LIVE SCREEN FEED
        </div>

        <img
            id="feedImage"
            class="screen"
            style="display:none"
            alt="Pocket Option live screen"
        >

        <div id="waiting" class="waiting">
            Waiting for Pocket Option screen feed...
        </div>
    </div>

    <div class="card">
        <div class="cardtitle">
            LIVE STATE
        </div>

        <div class="grid">

            <div class="box">
                <div class="label">Asset</div>
                <div class="value" id="asset">
                    EUR/USD OTC
                </div>
            </div>

            <div class="box">
                <div class="label">Price</div>
                <div class="value" id="price">--</div>
            </div>

            <div class="box">
                <div class="label">Signal</div>
                <div class="value signal" id="signal">
                    WAIT
                </div>
            </div>

            <div class="box">
                <div class="label">Confidence</div>
                <div class="value" id="confidence">
                    0%
                </div>
            </div>

            <div class="box">
                <div class="label">Frames</div>
                <div class="value" id="frameCount">
                    0
                </div>
            </div>

            <div class="box">
                <div class="label">Feed</div>
                <div class="value" id="feed">
                    DISCONNECTED
                </div>
            </div>

        </div>
    </div>

</div>

<div class="footer">
    ALUCARD V2 • LIVE SCREEN INTELLIGENCE
</div>

<script>
const ASSETS = {{ assets | tojson }};
let currentCategory = "FOREX";
let selectedAsset = "EUR/USD OTC";
let favorites = [
    "EUR/USD OTC",
    "GBP/USD OTC",
    "USD/JPY OTC",
    "BTC/USD",
    "Gold"
];

function buildCategories() {
    const box = document.getElementById("categories");
    box.innerHTML = "";

    const all = document.createElement("button");
    all.className = "cat";
    all.textContent = "ALL";
    all.onclick = function() {
        currentCategory = "ALL";
        renderCategories();
        renderAssets();
    };
    box.appendChild(all);

    Object.keys(ASSETS).forEach(function(category) {
        const button = document.createElement("button");

        button.className = "cat";
        button.textContent = category;

        button.onclick = function() {
            currentCategory = category;
            renderCategories();
            renderAssets();
        };

        box.appendChild(button);
    });

    renderCategories();
}

function renderCategories() {
    document.querySelectorAll(".cat").forEach(function(button) {
        button.classList.remove("active");

        if (
            button.textContent === currentCategory ||
            (currentCategory === "ALL" &&
             button.textContent === "ALL")
        ) {
            button.classList.add("active");
        }
    });
}

function renderAssets() {
    const search = document
        .getElementById("search")
        .value
        .toLowerCase()
        .trim();

    const list = document.getElementById("assetList");
    list.innerHTML = "";

    let items = [];

    if (currentCategory === "ALL") {
        Object.values(ASSETS).forEach(function(group) {
            items = items.concat(group);
        });
    } else {
        items = ASSETS[currentCategory] || [];
    }

    items = [...new Set(items)];

    items = items.filter(function(asset) {
        return asset.toLowerCase().includes(search);
    });

    items.sort(function(a, b) {
        const af = favorites.includes(a);
        const bf = favorites.includes(b);

        if (af && !bf) return -1;
        if (!af && bf) return 1;

        return a.localeCompare(b);
    });

    items.forEach(function(asset) {
        const button = document.createElement("button");

        button.className = "asset";

        if (asset === selectedAsset) {
            button.classList.add("selected");
        }

        if (favorites.includes(asset)) {
            button.classList.add("favorite");
        }

        button.textContent = asset;

        button.onclick = function() {
            selectAsset(asset);
        };

        list.appendChild(button);
    });
}

async function selectAsset(asset) {
    selectedAsset = asset;

    document.getElementById("selectedAsset").textContent = asset;
    document.getElementById("asset").textContent = asset;

    renderAssets();

    try {
        await fetch("/api/select_asset", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                asset: asset
            })
        });
    } catch (e) {
        console.log("asset selection error", e);
    }
}

async function update() {
    try {
        const response =
            await fetch("/api/status?t=" + Date.now());

        const s = await response.json();

        selectedAsset = s.asset || selectedAsset;

        document.getElementById("selectedAsset")
            .textContent = selectedAsset;

        document.getElementById("asset")
            .textContent = selectedAsset;

        const live =
            s.connected === true &&
            s.feed === "LIVE";

        const connection =
            document.getElementById("connection");

        connection.textContent =
            live
            ? "FEED: LIVE"
            : "FEED: DISCONNECTED";

        connection.className =
            "status " + (live ? "live" : "dead");

        document.getElementById("frames")
            .textContent =
            "FRAMES: " + (s.frame_count || 0);

        document.getElementById("price")
            .textContent =
            s.price && Number(s.price) !== 0
            ? Number(s.price).toFixed(5)
            : "--";

        document.getElementById("signal")
            .textContent =
            s.signal || "WAIT";

        document.getElementById("confidence")
            .textContent =
            (s.confidence || 0) + "%";

        document.getElementById("frameCount")
            .textContent =
            s.frame_count || 0;

        document.getElementById("feed")
            .textContent =
            s.feed || "DISCONNECTED";

        if (s.image_received && s.frame_count > 0) {
            const img =
                document.getElementById("feedImage");

            const waiting =
                document.getElementById("waiting");

            img.src =
                "/api/frame.jpg?t=" + Date.now();

            img.style.display = "block";
            waiting.style.display = "none";
        }

    } catch (e) {
        console.log("status error", e);
    }
}

buildCategories();
renderAssets();
update();
setInterval(update, 2000);
</script>

</body>
</html>
""", assets=ASSETS)


@app.route("/api/status")
def api_status():
    with LOCK:
        state = dict(STATE)

    if state["last_update"]:
        age = time.time() - state["last_update"]

        if age > FEED_TIMEOUT:
            state["connected"] = False
            state["feed"] = "DISCONNECTED"

    return jsonify(state)


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "feed": STATE["feed"],
        "frame_count": STATE["frame_count"]
    })


@app.route("/api/select_asset", methods=["POST"])
def select_asset():
    if not authorized():
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}
    asset = str(data.get("asset", "")).strip()

    all_assets = []

    for group in ASSETS.values():
        all_assets.extend(group)

    if asset not in all_assets:
        return jsonify({
            "ok": False,
            "error": "Asset not available"
        }), 400

    with LOCK:
        STATE["asset"] = asset
        STATE["signal"] = "WAIT"
        STATE["confidence"] = 0

    return jsonify({
        "ok": True,
        "asset": asset
    })


@app.route("/api/feed", methods=["POST"])
def api_feed():
    if not authorized():
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "ok": False,
            "error": "No JSON data received"
        }), 400

    with LOCK:
        for key in [
            "asset",
            "price",
            "signal",
            "confidence",
            "entry",
            "entry_window",
            "candles"
        ]:
            if key in data:
                STATE[key] = data[key]

        STATE["feed"] = data.get("feed", "LIVE")
        STATE["connected"] = True
        STATE["last_update"] = time.time()

    return jsonify({
        "ok": True,
        "message": "JSON feed accepted",
        "feed": "LIVE",
        "state": STATE
    })


@app.route("/api/frame", methods=["POST"])
def api_frame():
    global FRAME_DATA
    global FRAME_CONTENT_TYPE

    if not authorized():
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    image_data = None

    content_type = request.content_type or ""

    if "multipart/form-data" in content_type:
        uploaded = (
            request.files.get("image")
            or request.files.get("frame")
        )

        if uploaded:
            image_data = uploaded.read()

    else:
        image_data = request.get_data()

    detected_type = valid_image(image_data)

    if not detected_type:
        return jsonify({
            "ok": False,
            "error": "Invalid or missing image"
        }), 400

    with LOCK:
        FRAME_DATA = image_data
        FRAME_CONTENT_TYPE = detected_type

        STATE["last_update"] = time.time()
        STATE["last_frame"] = time.time()
        STATE["connected"] = True
        STATE["feed"] = "LIVE"
        STATE["image_received"] = True
        STATE["frame_count"] += 1

        count = STATE["frame_count"]

    return jsonify({
        "ok": True,
        "message": "Screen frame accepted",
        "feed": "LIVE",
        "frame_count": count
    })


@app.route("/api/frame.jpg")
def frame_image():
    with LOCK:
        data = FRAME_DATA
        content_type = FRAME_CONTENT_TYPE

    if not data:
        return Response(
            "No frame received",
            status=404,
            mimetype="text/plain"
        )

    return Response(
        data,
        status=200,
        mimetype=content_type,
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache"
        }
    )


def monitor():
    while True:
        time.sleep(3)

        with LOCK:
            STATE["scan"] += 1

            if STATE["last_update"]:
                age = time.time() - STATE["last_update"]

                if age > FEED_TIMEOUT:
                    STATE["connected"] = False
                    STATE
