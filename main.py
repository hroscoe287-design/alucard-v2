from flask import Flask, request, jsonify, Response
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone
import threading
import time

app = Flask(__name__)
lock = threading.Lock()

ASSETS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "GBPCHF", "AUDJPY", "EURAUD", "EURCAD",
    "GBPAUD", "GBPCAD", "USD/CAD", "USD/CHF", "XAUUSD", "XAGUSD", "USOIL",
    "UKOIL", "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD", "SPX500",
    "NAS100", "US30", "GER30", "FRA40", "JPN225", "HK50", "AAPL", "TSLA",
    "AMZN", "MSFT", "NVDA", "META", "GOOGL"
]

state = {
    "asset": "EURUSD",
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
    "payout": 0,
    "updated": None,
    "frame_width": 0,
    "frame_height": 0,
    "frame_bytes": 0,
}

last_image = None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_asset(value):
    if not value:
        return None

    value = str(value).strip().upper()

    if value.endswith("_OTC"):
        value = value[:-4]

    return value if value else None


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_signal(value):
    value = str(value or "WAIT").upper().strip()

    if value in ("CALL", "PUT", "WAIT"):
        return value

    return "WAIT"


def apply_payload(data):
    if not isinstance(data, dict):
        return

    asset = clean_asset(data.get("asset"))

    if asset:
        state["asset"] = asset

    if "price" in data:
        state["price"] = number(
            data.get("price"),
            state["price"]
        )

    if "signal" in data:
        state["signal"] = normalize_signal(
            data.get("signal")
        )

    if "confidence" in data:
        state["confidence"] = max(
            0,
            min(
                100,
                integer(
                    data.get("confidence"),
                    state["confidence"]
                )
            )
        )

    if "entry" in data:
        state["entry"] = number(
            data.get("entry"),
            state["entry"]
        )

    if "entry_window" in data:
        state["entry_window"] = max(
            0,
            integer(
                data.get("entry_window"),
                12
            )
        )

    for key in ("candles", "payout"):
        if key in data:
            state[key] = integer(
                data.get(key),
                state[key]
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
            state[key] = number(
                data.get(key),
                state[key]
            )

    if data.get("analysis"):
        state["analysis"] = str(data["analysis"])


@app.get("/")
def dashboard():

    html = []

    html.append(
        '<!doctype html><html><head>'
        '<meta charset="utf-8">'
    )

    html.append(
        '<meta name="viewport" '
        'content="width=device-width,initial-scale=1">'
    )

    html.append(
        '<title>ALUCARD V2.1</title>'
    )

    html.append("<style>")

    html.append(
        "body{"
        "margin:0;"
        "background:#08090b;"
        "color:#eee;"
        "font-family:Arial,sans-serif"
        "}"
    )

    html.append(
        ".wrap{"
        "max-width:1100px;"
        "margin:auto;"
        "padding:18px"
        "}"
    )

    html.append(
        "h1{"
        "margin:0;"
        "color:#ddd;"
        "letter-spacing:4px"
        "}"
    )

    html.append(
        ".sub{"
        "color:#888;"
        "margin:5px 0 18px"
        "}"
    )

    html.append(
        ".status{"
        "padding:10px 14px;"
        "border:1px solid #333;"
        "border-radius:8px;"
        "background:#111;"
        "margin-bottom:14px"
        "}"
    )

    html.append(
        ".grid{"
        "display:grid;"
        "grid-template-columns:"
        "repeat(4,1fr);"
        "gap:10px"
        "}"
    )

    html.append(
        ".card{"
        "background:#11151a;"
        "border:1px solid #292d33;"
        "border-radius:10px;"
        "padding:14px;"
        "min-height:70px"
        "}"
    )

    html.append(
        ".label{"
        "font-size:11px;"
        "color:#888;"
        "text-transform:uppercase"
        "}"
    )

    html.append(
        ".value{"
        "font-size:25px;"
        "margin-top:8px;"
        "font-weight:bold"
        "}"
    )

    html.append(
        ".signal{"
        "font-size:34px"
        "}"
    )

    html.append(
        ".green{color:#49e38a}"
    )

    html.append(
        ".red{color:#ff6262}"
    )

    html.append(
        ".yellow{color:#ffd166}"
    )

    html.append(
        "select,button{"
        "background:#12161b;"
        "color:#eee;"
        "border:1px solid #444;"
        "border-radius:7px;"
        "padding:10px"
        "}"
    )

    html.append(
        ".tabs{"
        "display:flex;"
        "gap:8px;"
        "margin:14px 0"
        "}"
    )

    html.append(
        ".panel{"
        "background:#0d1014;"
        "border:1px solid #252a30;"
        "border-radius:10px;"
        "padding:15px;"
        "margin-top:12px"
        "}"
    )

    html.append(
        ".small{"
        "font-size:12px;"
        "color:#999"
        "}"
    )

    html.append(
        "@media(max-width:700px){"
        ".grid{"
        "grid-template-columns:"
        "repeat(2,1fr)"
        "}"
        "}"
    )

    html.append("</style></head><body>")

    html.append('<div class="wrap">')

    html.append(
        '<h1>ALUCARD</h1>'
        '<div class="sub">'
        'GOTHIC MARKET INTELLIGENCE — V2.1'
        '</div>'
    )

    html.append(
        '<div class="status" id="status">'
        'Feed: WAITING | Asset: EURUSD'
        '</div>'
    )

    html.append(
        '<div class="tabs">'
        '<button onclick="showTab(\'signals\')">'
        'Signals</button>'
        '<button onclick="showTab(\'trades\')">'
        'Trades</button>'
        '<button onclick="showTab(\'performance\')">'
        'Performance</button>'
        '<button onclick="showTab(\'settings\')">'
        'Settings</button>'
        '</div>'
    )

    html.append(
        '<div class="panel">'
        '<div class="label">Currency / Asset</div>'
        '<select id="asset" '
        'onchange="setAsset(this.value)">'
    )

    for asset in ASSETS:
        html.append(
            '<option value="' +
            asset +
            '">' +
            asset +
            '</option>'
        )

    html.append("</select></div>")

    html.append('<div class="grid">')

    cards = [
        ("signal", "Signal", "signal"),
        ("price", "Price", ""),
        ("confidence", "Confidence", ""),
        ("entry", "Entry", ""),
        ("entry_window", "Entry Window", ""),
        ("candles", "Candles", "")
    ]

    for ident, label, extra in cards:
        html.append(
            '<div class="card">'
            '<div class="label">' +
            label +
            '</div>'
            '<div id="' +
            ident +
            '" class="value ' +
            extra +
            '">--</div>'
            '</div>'
        )

    html.append("</div>")

    html.append(
        '<div class="panel">'
        '<div class="label">Analytics</div>'
        '<div id="analysis">'
        'Waiting for Pocket Option screen feed...'
        '</div>'
        '<div class="small" id="indicators">'
        'EMA9 -- | EMA20 -- | EMA50 -- | '
        'RSI -- | MACD -- | CCI -- | ATR --'
        '</div>'
        '</div>'
    )

    html.append(
        '<div class="panel">'
        '<div class="label">Screen Feed</div>'
        '<div id="frameinfo">'
        'No screenshot received'
        '</div>'
        '<div class="small" id="updated">'
        'No frame timestamp'
        '</div>'
        '</div>'
    )

    html.append(
        '<div id="tabcontent" class="panel">'
        'Live signal dashboard'
        '</div>'
    )

    html.append("</div>")

    html.append("<script>")

    html.append(
        'let selectedAsset="EURUSD";'
    )

    html.append(
        'function fmt(v){'
        'if(v===null||v===undefined||'
        'Number.isNaN(Number(v)))return "--";'
        'return Number(v).toFixed(6)'
        '}'
    )

    html.append(
        'function paint(s){'
        'document.getElementById("status").textContent='
        '"Feed: "+s.feed+" | Asset: "+'
        '(s.asset||"UNKNOWN");'

        'document.getElementById("signal").textContent='
        's.signal||"WAIT";'

        'document.getElementById("signal").className='
        '"value signal "+'
        '(s.signal==="CALL"?"green":'
        's.signal==="PUT"?"red":"yellow");'

        'document.getElementById("price").textContent='
        'fmt(s.price);'

        'document.getElementById("confidence").textContent='
        '(s.confidence||0)+"%";'

        'document.getElementById("entry").textContent='
        'fmt(s.entry);'

        'document.getElementById("entry_window").textContent='
        '(s.entry_window??12)+"s";'

        'document.getElementById("candles").textContent='
        's.candles??0;'

        'document.getElementById("analysis").textContent='
        's.analysis||"Waiting for Pocket Option screen feed...";'

        'document.getElementById("indicators").textContent='
        '"EMA9 "+fmt(s.ema9)+'
        '" | EMA20 "+fmt(s.ema20)+'
        '" | EMA50 "+fmt(s.ema50)+'
        '" | RSI "+fmt(s.rsi)+'
        '" | MACD "+fmt(s.macd)+'
        '" | CCI "+fmt(s.cci)+'
        '" | ATR "+fmt(s.atr);'

        'document.getElementById("frameinfo").textContent='
        's.image_received?'
        '"Screenshot received: "+'
        '(s.frame_width||"?")+"×"+'
        '(s.frame_height||"?")+" ("+'
        '(s.frame_bytes||0)+" bytes)":'
        '"No screenshot received";'

        'document.getElementById("updated").textContent='
        's.last_frame?'
        '"Last frame: "+s.last_frame:'
        '"No frame timestamp";'

        'let sel=document.getElementById("asset");'

        'if(s.asset&&!sel.matches(":focus")){'
        'sel.value=s.asset;'
        '}'
        '}'
    )

    html.append(
        'async function refresh(){'
        'try{'
        'let r=await fetch('
        '"/api/state?ts="+Date.now(),'
        '{cache:"no-store"}'
        ');'
        'let s=await r.json();'
        'paint(s)'
        '}catch(e){'
        'document.getElementById("status").textContent='
        '"Feed: ERROR | Dashboard API unavailable"'
        '}'
        '}'
    )

    html.append(
        'async function setAsset(a){'
        'selectedAsset=a;'
        'try{'
        'await fetch("/api/asset",'
        '{'
        'method:"POST",'
        'headers:{"Content-Type":"application/json"},'
        'body:JSON.stringify({asset:a})'
        '}'
        ')'
        '}catch(e){}'
        'refresh()'
        '}'
    )

    html.append(
        'function showTab(t){'
        'let x={'
        'signals:"Live signal dashboard",'
        'trades:"Trade history is populated when '
        'trade data is supplied to the feed.",'
        'performance:"Performance statistics require '
        'completed trade results.",'
        'settings:"Screen-feed mode: active. '
        'Entry window: 12 seconds."'
        '};'
        'document.getElementById("tabcontent").textContent='
        'x[t]||x.signals'
        '}'

        'setInterval(refresh,1500);'
        'refresh();'
    )

    html.append("</script></body></html>")

    return Response(
        "".join(html),
        mimetype="text/html"
    )


@app.get("/api/state")
def api_state():

    with lock:
        result = dict(state)

    if result.get("updated"):
        try:
            age = (
                time.time()
                -
                datetime.fromisoformat(
                    result["updated"].replace(
                        "Z",
                        "+00:00"
                    )
                ).timestamp()
            )

            if age > 15:
                result["feed"] = "STALE"

        except Exception:
            pass

    return jsonify(result)


@app.post("/api/asset")
def api_asset():

    data = request.get_json(silent=True) or {}

    asset = clean_asset(
        data.get("asset")
    )

    if not asset:
        return jsonify(
            ok=False,
            error="asset required"
        ), 400

    with lock:
        state["asset"] = asset

    return jsonify(
        ok=True,
        asset=asset
    )


@app.post("/api/frame")
def api_frame():

    global last_image

    data = request.get_json(
        silent=True
    )

    if data:

        with lock:
            apply_payload(data)

            state["feed"] = "LIVE"
            state["updated"] = now_iso()

            if (
                state["analysis"]
                ==
                "Waiting for Pocket Option screen feed..."
            ):
                state["analysis"] = (
                    "JSON feed received."
                )

            result = dict(state)

        return jsonify(
            ok=True,
            message="JSON frame accepted",
            state=result
        )

    raw = request.get_data(
        cache=False
    )

    upload = (
        request.files.get("frame")
        or request.files.get("image")
        or request.files.get("file")
    )

    if upload:
        raw = upload.read()

    if not raw:
        return jsonify(
            ok=False,
            error="No image or JSON data received"
        ), 400

    try:
        image = Image.open(
            BytesIO(raw)
        )

        image.load()

        width, height = image.size
        fmt = image.format or "UNKNOWN"

    except Exception as exc:
        return jsonify(
            ok=False,
            error="Invalid image: " + str(exc)
        ), 400

    with lock:

        last_image = raw

        state["feed"] = "LIVE"
        state["image_received"] = True
        state["last_frame"] = now_iso()
        state["updated"] = state["last_frame"]

        state["frame_width"] = width
        state["frame_height"] = height
        state["frame_bytes"] = len(raw)

        state["analysis"] = (
            "Pocket Option screenshot received. "
            "Market values will update when the "
            "feed supplies extracted price/candle data."
        )

        result = dict(state)

    return jsonify(
        ok=True,
        message="Image frame accepted",
        format=fmt,
        state=result
    )


@app.post("/api/feed")
def api_feed():
    return api_frame()


@app.get("/api/health")
def health():

    return jsonify(
        ok=True,
        service="alucard-v2",
        time=now_iso()
    )


@app.get("/api/frame")
def get_frame():

    if not last_image:
        return jsonify(
            ok=False,
            error="No frame received yet"
        ), 404

    return Response(
        last_image,
        mimetype="image/jpeg"
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
