import os
import time
import math
import asyncio
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template_string

# ============================================================
# ALUCARD V2 — LIVE POCKET OPTION SIGNAL DASHBOARD
# ============================================================

app = Flask(__name__)

APP_NAME = "ALUCARD V2"
SUBTITLE = "GOTHIC MARKET INTELLIGENCE"

PORT = int(os.environ.get("PORT", "10000"))

MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "78"))
ENTRY_SECONDS = int(os.environ.get("ENTRY_SECONDS", "12"))
EXPIRY_SECONDS = int(os.environ.get("EXPIRY_SECONDS", "300"))

PO_SSID = os.environ.get("POCKET_OPTION_SSID", "").strip()

MAX_HISTORY = 100
MAX_CANDLES = 500

# ============================================================
# ASSET CATALOG
# ============================================================

ASSETS = {
    "FOREX": [
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
        "USD/CAD", "USD/CHF", "NZD/USD", "EUR/GBP",
        "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD",
        "EUR/NZD", "GBP/JPY", "GBP/CHF", "GBP/AUD",
        "GBP/CAD", "GBP/NZD", "AUD/JPY", "AUD/CAD",
        "AUD/CHF", "AUD/NZD", "CAD/JPY", "CAD/CHF",
        "CHF/JPY", "NZD/JPY", "NZD/CAD", "NZD/CHF"
    ],

    "FOREX OTC": [
        "EUR/USD OTC", "GBP/USD OTC", "USD/JPY OTC",
        "AUD/USD OTC", "USD/CAD OTC", "USD/CHF OTC",
        "NZD/USD OTC", "EUR/GBP OTC", "EUR/JPY OTC",
        "EUR/CHF OTC", "EUR/NZD OTC", "AUD/CAD OTC",
        "AUD/CHF OTC", "AUD/JPY OTC", "AUD/NZD OTC",
        "CAD/CHF OTC", "CAD/JPY OTC", "CHF/JPY OTC",
        "GBP/AUD OTC", "GBP/JPY OTC", "NZD/JPY OTC",
        "NZD/USD OTC", "USD/SGD OTC", "USD/CLP OTC",
        "USD/PHP OTC", "USD/ARS OTC", "USD/IDR OTC",
        "USD/BDT OTC", "TND/USD OTC", "AED/CNY OTC",
        "QAR/CNY OTC", "JOD/CNY OTC", "ZAR/USD OTC",
        "USD/DZD OTC", "USD/VND OTC", "YER/USD OTC",
        "UAH/USD OTC", "SAR/CNY OTC"
    ],

    "CRYPTO": [
        "Bitcoin", "Ethereum", "Litecoin", "Bitcoin Cash",
        "Dash", "Chainlink", "BTC/GBP", "BTC/JPY",
        "BCH/EUR", "BCH/GBP", "BCH/JPY"
    ],

    "CRYPTO OTC": [
        "Bitcoin OTC", "Ethereum OTC", "Litecoin OTC",
        "Bitcoin Cash OTC", "Dogecoin OTC", "Solana OTC",
        "Cardano OTC", "BNB OTC", "TRON OTC",
        "Chainlink OTC", "Toncoin OTC", "Avalanche OTC",
        "Polkadot OTC", "Polygon OTC", "Bitcoin ETF OTC"
    ],

    "COMMODITIES": [
        "Gold", "Silver", "Platinum", "Palladium",
        "Brent Oil", "WTI Crude Oil", "Natural Gas"
    ],

    "COMMODITIES OTC": [
        "Gold OTC", "Silver OTC", "Platinum Spot OTC",
        "Palladium Spot OTC", "Brent Oil OTC",
        "WTI Crude Oil OTC", "Natural Gas OTC"
    ],

    "STOCKS": [
        "Apple", "Amazon", "Microsoft", "Tesla", "NVIDIA",
        "AMD", "Intel", "Netflix", "Meta", "Google",
        "Boeing", "VISA", "Mastercard", "McDonald's",
        "Coca-Cola", "Johnson & Johnson", "Pfizer",
        "ExxonMobil", "Cisco", "FedEx", "Coinbase",
        "Palantir", "GameStop", "Alibaba",
        "American Express", "Citigroup", "Marathon Digital"
    ],

    "STOCKS OTC": [
        "Apple OTC", "Amazon OTC", "Microsoft OTC",
        "Tesla OTC", "NVIDIA OTC", "AMD OTC", "Intel OTC",
        "Netflix OTC", "Meta OTC", "Boeing OTC",
        "VISA OTC", "Palantir OTC", "Coinbase OTC",
        "Cisco OTC", "FedEx OTC", "McDonald's OTC",
        "Johnson & Johnson OTC", "ExxonMobil OTC",
        "Pfizer OTC", "Citigroup OTC", "GameStop OTC",
        "Alibaba OTC", "American Express OTC",
        "Marathon Digital OTC"
    ],

    "INDICES": [
        "US100", "SP500", "DJI30", "D30", "E50",
        "E35", "CAC 40", "JPN225", "AUS 200",
        "HONG KONG 33", "100GBP"
    ],

    "INDICES OTC": [
        "US100 OTC", "SP500 OTC", "DJI30 OTC",
        "D30EUR OTC", "E50EUR OTC", "E35EUR OTC",
        "F40EUR OTC", "JPN225 OTC", "100GBP OTC"
    ]
}

# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400
}

# ============================================================
# POCKET OPTION SYMBOL CONVERSION
# ============================================================

SYMBOL_MAP = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "AUD/USD": "AUDUSD",
    "USD/CAD": "USDCAD",
    "USD/CHF": "USDCHF",
    "NZD/USD": "NZDUSD",
    "EUR/GBP": "EURGBP",
    "EUR/JPY": "EURJPY",
    "EUR/CHF": "EURCHF",
    "EUR/AUD": "EURAUD",
    "EUR/CAD": "EURCAD",
    "EUR/NZD": "EURNZD",
    "GBP/JPY": "GBPJPY",
    "GBP/CHF": "GBPCHF",
    "GBP/AUD": "GBPAUD",
    "GBP/CAD": "GBPCAD",
    "GBP/NZD": "GBPNZD",
    "AUD/JPY": "AUDJPY",
    "AUD/CAD": "AUDCAD",
    "AUD/CHF": "AUDCHF",
    "AUD/NZD": "AUDNZD",
    "CAD/JPY": "CADJPY",
    "CAD/CHF": "CADCHF",
    "CHF/JPY": "CHFJPY",
    "NZD/JPY": "NZDJPY",
    "NZD/CAD": "NZDCAD",
    "NZD/CHF": "NZDCHF"
}


def pocket_symbol(asset):
    name = asset.strip()

    otc = name.upper().endswith(" OTC")

    if otc:
        name = name[:-4].strip()

    if name in SYMBOL_MAP:
        symbol = SYMBOL_MAP[name]
    else:
        symbol = (
            name.upper()
            .replace("/", "")
            .replace(" ", "_")
        )

    if otc:
        symbol += "_otc"

    return symbol


# ============================================================
# STATE
# ============================================================

STATE = {
    "feed": "DISCONNECTED",
    "feed_message": "Waiting for Pocket Option connection",
    "last_tick": None,
    "selected_asset": "EUR/USD OTC",
    "selected_timeframe": "1m",
    "symbol": "EURUSD_otc",
    "price": None,
    "signal": "WAIT",
    "confidence": 0,
    "reason": "Waiting for live candles",
    "entry_price": None,
    "payout": None,
    "signal_time": None,
    "entry_deadline": None,
    "expiry_time": None,
    "scan": 0,
    "candles": [],
    "indicators": {},
    "history": [],
    "connected": False,
    "demo": True,
    "error": None,
    "last_update": None
}

LOCK = threading.RLock()
PO_CLIENT = None
PO_LOOP = None
PO_THREAD = None


# ============================================================
# TIME HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def unix_now():
    return time.time()


# ============================================================
# INDICATORS
# ============================================================

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    return (
        100 - (100 / (1 + rs))
    ).fillna(50)


def macd(series):
    fast = ema(series, 12)
    slow = ema(series, 26)

    line = fast - slow
    signal = ema(line, 9)

    return line, signal


def cci(df, period=20):
    tp = (
        df["high"] +
        df["low"] +
        df["close"]
    ) / 3

    mean = tp.rolling(period).mean()

    deviation = (
        tp - mean
    ).abs().rolling(period).mean()

    return (
        (tp - mean) /
        (0.015 * deviation.replace(0, np.nan))
    ).fillna(0)


def awesome_oscillator(df):
    median = (
        df["high"] +
        df["low"]
    ) / 2

    fast = median.rolling(5).mean()
    slow = median.rolling(34).mean()

    return (fast - slow).fillna(0)


def psar(df, step=0.02, maximum=0.2):

    if len(df) < 5:
        return pd.Series(
            index=df.index,
            dtype=float
        )

    high = df["high"].astype(float).values
    low = df["low"].astype(float).values

    sar = np.zeros(len(df))

    bull = True
    af = step
    ep = high[0]

    sar[0] = low[0]

    for i in range(1, len(df)):

        previous = sar[i - 1]

        if bull:

            sar[i] = (
                previous +
                af * (ep - previous)
            )

            if i >= 2:
                sar[i] = min(
                    sar[i],
                    low[i - 1],
                    low[i - 2]
                )

            if low[i] < sar[i]:

                bull = False
                sar[i] = ep
                af = step
                ep = low[i]

            elif high[i] > ep:

                ep = high[i]
                af = min(
                    maximum,
                    af + step
                )

        else:

            sar[i] = (
                previous +
                af * (ep - previous)
            )

            if i >= 2:
                sar[i] = max(
                    sar[i],
                    high[i - 1],
                    high[i - 2]
                )

            if high[i] > sar[i]:

                bull = True
                sar[i] = ep
                af = step
                ep = high[i]

            elif low[i] < ep:

                ep = low[i]
                af = min(
                    maximum,
                    af + step
                )

    return pd.Series(
        sar,
        index=df.index
    )


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(df):

    if df is None or len(df) < 50:

        return {
            "signal": "WAIT",
            "confidence": 0,
            "reason": "Waiting for at least 50 live candles",
            "indicators": {}
        }

    df = df.copy()

    close = df["close"]

    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)

    r = rsi(close)

    macd_line, macd_signal = macd(close)

    cc = cci(df)
    ao = awesome_oscillator(df)
    sar = psar(df)

    i = -1

    call = 0
    put = 0

    # EMA TREND

    if e9.iloc[i] > e21.iloc[i]:
        call += 1
    elif e9.iloc[i] < e21.iloc[i]:
        put += 1

    if e21.iloc[i] > e50.iloc[i]:
        call += 1
    elif e21.iloc[i] < e50.iloc[i]:
        put += 1

    # RSI

    if r.iloc[i] > 55:
        call += 1
    elif r.iloc[i] < 45:
        put += 1

    # MACD

    if macd_line.iloc[i] > macd_signal.iloc[i]:
        call += 1
    elif macd_line.iloc[i] < macd_signal.iloc[i]:
        put += 1

    # CCI

    if cc.iloc[i] > 50:
        call += 1
    elif cc.iloc[i] < -50:
        put += 1

    # AO

    if ao.iloc[i] > 0:
        call += 1
    elif ao.iloc[i] < 0:
        put += 1

    # PSAR

    if close.iloc[i] > sar.iloc[i]:
        call += 1
    elif close.iloc[i] < sar.iloc[i]:
        put += 1

    total = 7

    strongest = max(call, put)

    confidence = int(
        round(
            50 +
            (strongest / total) * 48
        )
    )

    if (
        call >= 5 and
        call > put and
        confidence >= MIN_CONFIDENCE
    ):

        signal = "CALL"

    elif (
        put >= 5 and
        put > call and
        confidence >= MIN_CONFIDENCE
    ):

        signal = "PUT"

    else:

        signal = "WAIT"
        confidence = min(confidence, 69)

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": (
            f"CALL {call}/{total} | "
            f"PUT {put}/{total}"
        ),
        "indicators": {
            "EMA9": float(e9.iloc[i]),
            "EMA21": float(e21.iloc[i]),
            "EMA50": float(e50.iloc[i]),
            "RSI": float(r.iloc[i]),
            "MACD": float(macd_line.iloc[i]),
            "MACD_SIGNAL": float(macd_signal.iloc[i]),
            "CCI": float(cc.iloc[i]),
            "AO": float(ao.iloc[i]),
            "PSAR": float(sar.iloc[i])
        }
    }


# ============================================================
# CANDLE NORMALIZATION
# ============================================================

def normalize_candle(item):

    try:

        if isinstance(item, dict):

            timestamp = (
                item.get("timestamp")
                or item.get("time")
                or item.get("at")
                or item.get("from")
            )

            opening = (
                item.get("open")
                or item.get("o")
            )

            high = (
                item.get("high")
                or item.get("h")
            )

            low = (
                item.get("low")
                or item.get("l")
            )

            close = (
                item.get("close")
                or item.get("c")
            )

        elif isinstance(item, (list, tuple)):

            if len(item) < 5:
                return None

            timestamp = item[0]
            opening = item[1]
            close = item[2]
            high = item[3]
            low = item[4]

        else:
            return None

        if timestamp is None:
            timestamp = time.time()

        timestamp = float(timestamp)

        if timestamp > 100000000000:
            timestamp /= 1000

        values = [
            opening,
            high,
            low,
            close
        ]

        if any(v is None for v in values):
            return None

        return {
            "timestamp": timestamp,
            "open": float(opening),
            "high": float(high),
            "low": float(low),
            "close": float(close)
        }

    except Exception:
        return None


# ============================================================
# DATAFRAME
# ============================================================

def candles_dataframe():

    with LOCK:
        candles = list(STATE["candles"])

    if not candles:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close"
            ]
        )

    df = pd.DataFrame(candles)

    df = df.drop_duplicates(
        subset=["timestamp"],
        keep="last"
    )

    df = df.sort_values(
        "timestamp"
    )

    return df.tail(
        MAX_CANDLES
    ).reset_index(drop=True)


# ============================================================
# PROCESS LIVE CANDLE
# ============================================================

def process_candle(candle):

    if not candle:
        return

    with LOCK:

        candles = STATE["candles"]

        if candles:

            last = candles[-1]

            # Same candle: update it.

            if candle["timestamp"] == last["timestamp"]:

                candles[-1] = candle

            # New candle.

            elif candle["timestamp"] > last["timestamp"]:

                candles.append(candle)

            else:
                return

        else:

            candles.append(candle)

        if len(candles) > MAX_CANDLES:
            STATE["candles"] = candles[-MAX_CANDLES:]

        STATE["price"] = candle["close"]
        STATE["last_tick"] = candle["timestamp"]
        STATE["last_update"] = iso_now()
        STATE["scan"] += 1

    df = candles_dataframe()

    result = calculate_signal(df)

    with LOCK:

        STATE["signal"] = result["signal"]
        STATE["confidence"] = result["confidence"]
        STATE["reason"] = result["reason"]
        STATE["indicators"] = result["indicators"]

        if result["signal"] in ("CALL", "PUT"):

            now = time.time()

            STATE["entry_price"] = candle["close"]
            STATE["signal_time"] = now
            STATE["entry_deadline"] = (
                now + ENTRY_SECONDS
            )
            STATE["expiry_time"] = (
                now + EXPIRY_SECONDS
            )

            STATE["history"].insert(
                0,
                {
                    "time": iso_now(),
                    "asset": STATE["selected_asset"],
                    "timeframe": STATE["selected_timeframe"],
                    "signal": result["signal"],
                    "confidence": result["confidence"],
                    "price": candle["close"]
                }
            )

            STATE["history"] = (
                STATE["history"][:MAX_HISTORY]
            )


# ============================================================
# POCKET OPTION LIVE CONNECTOR
# ============================================================

async def pocket_loop():

    global PO_CLIENT

    if not PO_SSID:

        with LOCK:
            STATE["feed"] = "DISCONNECTED"
            STATE["feed_message"] = (
                "POCKET_OPTION_SSID is not configured"
            )
            STATE["error"] = (
                "Add POCKET_OPTION_SSID in Render"
            )

        return

    try:

        from binaryoptionstoolsv2 import PocketOptionAsync

    except Exception as exc:

        with LOCK:
            STATE["feed"] = "ERROR"
            STATE["feed_message"] = (
                "BinaryOptionsToolsV2 is not installed"
            )
            STATE["error"] = str(exc)

        return

    while True:

        try:

            with LOCK:
                STATE["feed"] = "CONNECTING"
                STATE["feed_message"] = (
                    "Connecting to Pocket Option..."
                )
                STATE["error"] = None

            # Current library automatically handles the
            # authenticated Pocket Option session.

            client = await PocketOptionAsync(
                PO_SSID
            )

            PO_CLIENT = client

            await asyncio.sleep(3)

            with LOCK:
                STATE["connected"] = True
                STATE["feed"] = "LIVE"
                STATE["feed_message"] = (
                    "Pocket Option WebSocket connected"
                )

            asset = STATE["selected_asset"]
            symbol = pocket_symbol(asset)

            # Request historical candles first.

            try:

                historical = await client.get_candles(
                    symbol,
                    60,
                    int(time.time()) - 60 * 500
                )

                if historical:

                    for item in historical:

                        candle = normalize_candle(item)

                        if candle:
                            process_candle(candle)

            except Exception as exc:

                with LOCK:
                    STATE["error"] = (
                        "History: " + str(exc)
                    )

            # Subscribe to real-time stream.

            stream = await client.subscribe_symbol(
                symbol
            )

            async for item in stream:

                candle = normalize_candle(item)

                if candle:

                    process_candle(candle)

                with LOCK:

                    STATE["feed"] = "LIVE"
                    STATE["connected"] = True
                    STATE["feed_message"] = (
                        "Receiving live Pocket Option data"
                    )

        except Exception as exc:

            with LOCK:

                STATE["connected"] = False
                STATE["feed"] = "DISCONNECTED"
                STATE["feed_message"] = (
                    "Pocket Option connection lost"
                )
                STATE["error"] = str(exc)

            try:

                if PO_CLIENT:

                    await PO_CLIENT.shutdown()

            except Exception:
                pass

            PO_CLIENT = None

            await asyncio.sleep(5)


def start_pocket_connector():

    global PO_LOOP
    global PO_THREAD

    if PO_THREAD and PO_THREAD.is_alive():
        return

    def runner():

        global PO_LOOP

        PO_LOOP = asyncio.new_event_loop()

        asyncio.set_event_loop(
            PO_LOOP
        )

        PO_LOOP.run_until_complete(
            pocket_loop()
        )

    PO_THREAD = threading.Thread(
        target=runner,
        daemon=True
    )

    PO_THREAD.start()


# ============================================================
# WATCHDOG
# ============================================================

def watchdog():

    while True:

        time.sleep(2)

        with LOCK:

            last = STATE["last_update"]

            if not last:
                continue

            try:

                last_time = datetime.fromisoformat(
                    last
                ).timestamp()

                age = time.time() - last_time

            except Exception:
                continue

            if age > 15:

                if STATE["connected"]:

                    STATE["feed"] = "STALE"
                    STATE["feed_message"] = (
                        f"No live candle update for "
                        f"{int(age)} seconds"
                    )

            elif STATE["connected"]:

                STATE["feed"] = "LIVE"


# ============================================================
# API
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    with LOCK:

        now = time.time()

        entry_left = 0

        if STATE["entry_deadline"]:
            entry_left = max(
                0,
                int(
                    STATE["entry_deadline"] -
                    now
                )
            )

        expiry_left = 0

        if STATE["expiry_time"]:
            expiry_left = max(
                0,
                int(
                    STATE["expiry_time"] -
                    now
                )
            )

        data = {
            "app": APP_NAME,
            "subtitle": SUBTITLE,
            "feed": STATE["feed"],
            "feed_message": STATE["feed_message"],
            "connected": STATE["connected"],
            "demo": STATE["demo"],
            "asset": STATE["selected_asset"],
            "symbol": STATE["symbol"],
            "timeframe": STATE["selected_timeframe"],
            "price": STATE["price"],
            "signal": STATE["signal"],
            "confidence": STATE["confidence"],
            "reason": STATE["reason"],
            "entry_price": STATE["entry_price"],
            "payout": STATE["payout"],
            "signal_time": STATE["signal_time"],
            "entry_deadline": STATE["entry_deadline"],
            "entry_seconds_left": entry_left,
            "expiry_time": STATE["expiry_time"],
            "expiry_seconds_left": expiry_left,
            "scan": STATE["scan"],
            "candle_count": len(STATE["candles"]),
            "indicators": STATE["indicators"],
            "history": STATE["history"][:20],
            "error": STATE["error"],
            "last_update": STATE["last_update"]
        }

    return jsonify(data)


@app.route("/api/assets")
def api_assets():

    return jsonify(ASSETS)


@app.route("/api/select", methods=["POST"])
def api_select():

    data = request.get_json(
        silent=True
    ) or {}

    asset = data.get(
        "asset",
        STATE["selected_asset"]
    )

    timeframe = data.get(
        "timeframe",
        STATE["selected_timeframe"]
    )

    if timeframe not in TIMEFRAMES:
        return jsonify({
            "ok": False,
            "error": "Invalid timeframe"
        }), 400

    with LOCK:

        STATE["selected_asset"] = asset
        STATE["selected_timeframe"] = timeframe
        STATE["symbol"] = pocket_symbol(asset)

        STATE["candles"] = []
        STATE["signal"] = "WAIT"
        STATE["confidence"] = 0
        STATE["entry_price"] = None
        STATE["entry_deadline"] = None
        STATE["expiry_time"] = None
        STATE["reason"] = "Switching live symbol..."

    return jsonify({
        "ok": True,
        "asset": asset,
        "symbol": pocket_symbol(asset),
        "timeframe": timeframe
    })


@app.route("/health")
def health():

    with LOCK:

        return jsonify({
            "status": "ok",
            "feed": STATE["feed"],
            "connected": STATE["connected"],
            "scan": STATE["scan"],
            "last_update": STATE["last_update"]
        })


# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport"
      content="width=device-width,initial-scale=1">

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
            #30111b 0%,
            #090909 45%,
            #020202 100%
        );
    color: #eee;
    font-family: Arial, sans-serif;
}

.header {
    padding: 18px;
    border-bottom: 1px solid #49202b;
    background: rgba(0,0,0,.75);
}

.title {
    font-size: 28px;
    font-weight: 900;
    letter-spacing: 2px;
}

.subtitle {
    color: #b68b95;
    margin-top: 4px;
}

.status {
    margin-top: 12px;
    display: inline-block;
    padding: 8px 13px;
    border-radius: 20px;
    font-weight: bold;
    background: #222;
}

.container {
    padding: 14px;
    max-width: 1100px;
    margin: auto;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit,minmax(160px,1fr));
    gap: 10px;
}

.card {
    background: rgba(18,18,18,.92);
    border: 1px solid #3c2028;
    border-radius: 12px;
    padding: 14px;
}

.label {
    font-size: 11px;
    color: #a99ca0;
    text-transform: uppercase;
}

.value {
    font-size: 23px;
    font-weight: bold;
    margin-top: 6px;
}

.signal {
    text-align: center;
    padding: 25px;
    margin-top: 12px;
    border-radius: 15px;
    background: #110b0e;
    border: 1px solid #5d2735;
}

.signalText {
    font-size: 46px;
    font-weight: 900;
    letter-spacing: 3px;
}

.confidence {
    font-size: 22px;
    margin-top: 8px;
}

select,
button {
    width: 100%;
    padding: 11px;
    margin-top: 7px;
    border-radius: 8px;
    border: 1px solid #4a2932;
    background: #111;
    color: #fff;
}

button {
    cursor: pointer;
    font-weight: bold;
}

.timer {
    font-size: 30px;
    font-weight: 900;
    text-align: center;
    margin-top: 10px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
    font-size: 12px;
}

td, th {
    padding: 8px;
    border-bottom: 1px solid #292020;
    text-align: left;
}

.good {
    color: #5cff9b;
}

.warn {
    color: #ffd45c;
}

.bad {
    color: #ff5c6c;
}

pre {
    white-space: pre-wrap;
    word-break: break-word;
    color: #b9aeb2;
}

</style>
</head>

<body>

<div class="header">

<div class="title">
ALUCARD V2
</div>

<div class="subtitle">
GOTHIC MARKET INTELLIGENCE
</div>

<div id="feedStatus"
     class="status">
CONNECTING...
</div>

</div>

<div class="container">

<div class="grid">

<div class="card">
<div class="label">Asset</div>
<div id="asset"
     class="value">---</div>
</div>

<div class="card">
<div class="label">Price</div>
<div id="price"
     class="value">---</div>
</div>

<div class="card">
<div class="label">Timeframe</div>
<div id="timeframe"
     class="value">---</div>
</div>

<div class="card">
<div class="label">Scan</div>
<div id="scan"
     class="value">0</div>
</div>

</div>

<div class="signal">

<div class="label">
CURRENT SIGNAL
</div>

<div id="signal"
     class="signalText">
WAIT
</div>

<div id="confidence"
     class="confidence">
0%
</div>

<div id="reason">
Waiting for live market data
</div>

<div class="timer">
ENTRY:
<span id="entryTimer">--</span>
</div>

<div class="timer">
EXPIRY:
<span id="expiryTimer">--</span>
</div>

</div>

<div class="card"
     style="margin-top:12px">

<div class="label">
SELECT MARKET
</div>

<select id="assetSelect"></select>

<select id="timeSelect">

<option value="1m">1 Minute</option>
<option value="5m">5 Minutes</option>
<option value="15m">15 Minutes</option>
<option value="30m">30 Minutes</option>
<option value="1h">1 Hour</option>
<option value="4h">4 Hours</option>
<option value="1d">1 Day</option>

</select>

<button onclick="changeMarket()">
LOAD LIVE MARKET
</button>

</div>

<div class="grid"
     style="margin-top:12px">

<div class="card">
<div class="label">EMA 9</div>
<div id="ema9"
     class="value">---</div>
</div>

<div class="card">
<div class="label">EMA 21</div>
<div id="ema21"
     class="value">---</div>
</div>

<div class="card">
<div class="label">EMA 50</div>
<div id="ema50"
     class="value">---</div>
</div>

<div class="card">
<div class="label">RSI</div>
<div id="rsi"
     class="value">---</div>
</div>

<div class="card">
<div class="label">MACD</div>
<div id="macd"
     class="value">---</div>
</div>

<div class="card">
<div class="label">CCI</div>
<div id="cci"
     class="value">---</div>
</div>

<div class="card">
<div class="label">AO</div>
<div id="ao"
     class="value">---</div>
</div>

<div class="card">
<div class="label">PSAR</div>
<div id="psar"
     class="value">---</div>
</div>

</div>

<div class="card"
     style="margin-top:12px">

<div class="label">
SIGNAL HISTORY
</div>

<table>

<thead>
<tr>
<th>Time</th>
<th>Asset</th>
<th>Signal</th>
<th>Confidence</th>
<th>Price</th>
</tr>
</thead>

<tbody id="history"></tbody>

</table>

</div>

<div class="card"
     style="margin-top:12px">

<div class="label">
FEED DIAGNOSTICS
</div>

<pre id="diagnostics">
Waiting...
</pre>

</div>

</div>

<script>

let assetsLoaded = false;

async function loadAssets() {

    const response =
        await fetch("/api/assets");

    const assets =
        await response.json();

    const select =
        document.getElementById(
            "assetSelect"
        );

    select.innerHTML = "";

    for (
        const category
        in assets
    ) {

        const group =
            document.createElement(
                "optgroup"
            );

        group.label =
            category;

        for (
            const asset
            of assets[category]
        ) {

            const option =
                document.createElement(
                    "option"
                );

            option.value =
                asset;

            option.textContent =
                asset;

            group.appendChild(
                option
            );
        }

        select.appendChild(
            group
        );
    }

    assetsLoaded = true;
}


async function changeMarket() {

    const asset =
        document.getElementById(
            "assetSelect"
        ).value;

    const timeframe =
        document.getElementById(
            "timeSelect"
        ).value;

    await fetch(
        "/api/select",
        {
            method: "POST",
            headers: {
                "Content-Type":
                    "application/json"
            },
            body: JSON.stringify({
                asset,
                timeframe
            })
        }
    );
}


function setText(id, value) {

    document.getElementById(id)
        .textContent =
        value;
}


function fmt(value) {

    if (
        value === null ||
        value === undefined
    ) {
        return "---";
    }

    if (
        typeof value === "number"
    ) {
        return value.toFixed(6);
    }

    return value;
}


function update(data) {

    const status =
        document.getElementById(
            "feedStatus"
        );

    status.textContent =
        data.feed;

    status.className =
        "status";

    if (data.feed === "LIVE") {
        status.classList.add(
            "good"
        );
    }
    else if (
        data.feed === "STALE"
    ) {
        status.classList.add(
            "warn"
        );
    }
    else {
        status.classList.add(
            "bad"
        );
    }

    setText(
        "asset",
        data.asset
    );

    setText(
        "price",
        data.price === null
            ? "---"
            : fmt(data.price)
    );

    setText(
        "timeframe",
        data.timeframe
    );

    setText(
        "scan",
        data.scan
    );

    setText(
        "signal",
        data.signal
    );

    setText(
        "confidence",
        data.confidence + "%"
    );

    setText(
        "reason",
        data.reason
    );

    setText(
        "entryTimer",
        data.entry_seconds_left + "s"
    );

    setText(
        "expiryTimer",
        data.expiry_seconds_left + "s"
    );

    const i =
        data.indicators || {};

    setText(
        "ema9",
        fmt(i.EMA9)
    );

    setText(
        "ema21",
        fmt(i.EMA21)
    );

    setText(
        "ema50",
        fmt(i.EMA50)
    );

    setText(
        "rsi",
        fmt(i.RSI)
    );

    setText(
        "macd",
        fmt(i.MACD)
    );

    setText(
        "cci",
        fmt(i.CCI)
    );

    setText(
        "ao",
        fmt(i.AO)
    );

    setText(
        "psar",
        fmt(i.PSAR)
    );

    document.getElementById(
        "diagnostics"
    ).textContent =
        "Feed: " +
        data.feed +
        "\n" +
        "Message: " +
        data.feed_message +
        "\n" +
        "Connected: " +
        data.connected +
        "\n" +
        "Symbol: " +
        data.symbol +
        "\n" +
        "Candles: " +
        data.candle_count +
        "\n" +
        "Last update: " +
        data.last_update +
        "\n" +
        "Error: " +
        (data.error || "none");

    const history =
        document.getElementById(
            "history"
        );

    history.innerHTML = "";

    for (
        const row
        of data.history
    ) {

        const tr =
            document.createElement(
                "tr"
            );

        tr.innerHTML =
            "<td>" +
            row.time +
            "</td>" +

            "<td>" +
            row.asset +
            "</td>" +

            "<td>" +
            row.signal +
            "</td>" +

            "<td>" +
            row.confidence +
            "%</td>" +

            "<td>" +
            fmt(row.price) +
            "</td>";

        history.appendChild(
            tr
        );
    }

    if (assetsLoaded) {

        document.getElementById(
            "assetSelect"
        ).value =
            data.asset;

        document.getElementById(
            "timeSelect"
        ).value =
            data.timeframe;
    }
}


async function refresh() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache: "no-store"
                }
            );

        const data =
            await response.json();

        update(data);

    }
    catch (error) {

        const status =
            document.getElementById(
                "feedStatus"
            );

        status.textContent =
            "DISCONNECTED";

        status.className =
            "status bad";
    }
}


loadAssets();

refresh();

setInterval(
    refresh,
    1000
);

</script>

</body>
</html>
"""


# ============================================================
# STARTUP
# ============================================================

def startup():

    threading.Thread(
        target=watchdog,
        daemon=True
    ).start()

    start_pocket_connector()


startup()


# ============================================================
# RENDER
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
