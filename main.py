import os
import time
import math
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template_string

# ============================================================
# ALUCARD V2 — GOTHIC MARKET INTELLIGENCE
# POCKET OPTION STYLE SIGNAL DASHBOARD
# ============================================================

app = Flask(__name__)

APP_NAME = "ALUCARD V2"
SUBTITLE = "GOTHIC MARKET INTELLIGENCE"

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

PORT = int(os.environ.get("PORT", "10000"))

MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "78"))
ENTRY_SECONDS = int(os.environ.get("ENTRY_SECONDS", "12"))
EXPIRY_SECONDS = int(os.environ.get("EXPIRY_SECONDS", "300"))

MAX_HISTORY = 100

# ------------------------------------------------------------
# ASSET CATALOG
#
# This is the dashboard catalog. A live Pocket Option feed can
# replace/extend this catalog dynamically.
# ------------------------------------------------------------

ASSETS = {

    "FOREX": [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "AUD/USD",
        "USD/CAD",
        "USD/CHF",
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
        "NZD/CHF",
    ],

    "FOREX OTC": [
        "EUR/USD OTC",
        "GBP/USD OTC",
        "USD/JPY OTC",
        "AUD/USD OTC",
        "USD/CAD OTC",
        "USD/CHF OTC",
        "NZD/USD OTC",
        "EUR/GBP OTC",
        "EUR/JPY OTC",
        "EUR/CHF OTC",
        "EUR/NZD OTC",
        "AUD/CAD OTC",
        "AUD/CHF OTC",
        "AUD/JPY OTC",
        "AUD/NZD OTC",
        "CAD/CHF OTC",
        "CAD/JPY OTC",
        "CHF/JPY OTC",
        "GBP/AUD OTC",
        "GBP/JPY OTC",
        "NZD/JPY OTC",
        "NZD/USD OTC",
        "USD/SGD OTC",
        "USD/CLP OTC",
        "USD/PHP OTC",
        "USD/ARS OTC",
        "USD/IDR OTC",
        "USD/BDT OTC",
        "TND/USD OTC",
        "AED/CNY OTC",
        "QAR/CNY OTC",
        "JOD/CNY OTC",
        "ZAR/USD OTC",
        "USD/DZD OTC",
        "USD/VND OTC",
        "YER/USD OTC",
        "UAH/USD OTC",
        "SAR/CNY OTC",
    ],

    "CRYPTO": [
        "Bitcoin",
        "Ethereum",
        "Litecoin",
        "Bitcoin Cash",
        "Dash",
        "Chainlink",
        "BTC/GBP",
        "BTC/JPY",
        "BCH/EUR",
        "BCH/GBP",
        "BCH/JPY",
    ],

    "CRYPTO OTC": [
        "Bitcoin OTC",
        "Ethereum OTC",
        "Litecoin OTC",
        "Bitcoin Cash OTC",
        "Dogecoin OTC",
        "Solana OTC",
        "Cardano OTC",
        "BNB OTC",
        "TRON OTC",
        "Chainlink OTC",
        "Toncoin OTC",
        "Avalanche OTC",
        "Polkadot OTC",
        "Polygon OTC",
        "Bitcoin ETF OTC",
    ],

    "COMMODITIES": [
        "Gold",
        "Silver",
        "Platinum",
        "Palladium",
        "Brent Oil",
        "WTI Crude Oil",
        "Natural Gas",
    ],

    "COMMODITIES OTC": [
        "Gold OTC",
        "Silver OTC",
        "Platinum Spot OTC",
        "Palladium Spot OTC",
        "Brent Oil OTC",
        "WTI Crude Oil OTC",
        "Natural Gas OTC",
    ],

    "STOCKS": [
        "Apple",
        "Amazon",
        "Microsoft",
        "Tesla",
        "NVIDIA",
        "AMD",
        "Intel",
        "Netflix",
        "Meta",
        "Google",
        "Boeing",
        "VISA",
        "Mastercard",
        "McDonald's",
        "Coca-Cola",
        "Johnson & Johnson",
        "Pfizer",
        "ExxonMobil",
        "Cisco",
        "FedEx",
        "Coinbase",
        "Palantir",
        "GameStop",
        "Alibaba",
        "American Express",
        "Citigroup",
        "Marathon Digital",
    ],

    "STOCKS OTC": [
        "Apple OTC",
        "Amazon OTC",
        "Microsoft OTC",
        "Tesla OTC",
        "NVIDIA OTC",
        "AMD OTC",
        "Intel OTC",
        "Netflix OTC",
        "Meta OTC",
        "Boeing OTC",
        "VISA OTC",
        "Palantir OTC",
        "Coinbase OTC",
        "Cisco OTC",
        "FedEx OTC",
        "McDonald's OTC",
        "Johnson & Johnson OTC",
        "ExxonMobil OTC",
        "Pfizer OTC",
        "Citigroup OTC",
        "GameStop OTC",
        "Alibaba OTC",
        "American Express OTC",
        "Marathon Digital OTC",
    ],

    "INDICES": [
        "US100",
        "SP500",
        "DJI30",
        "D30",
        "E50",
        "E35",
        "CAC 40",
        "JPN225",
        "AUS 200",
        "HONG KONG 33",
        "100GBP",
    ],

    "INDICES OTC": [
        "US100 OTC",
        "SP500 OTC",
        "DJI30 OTC",
        "D30EUR OTC",
        "E50EUR OTC",
        "E35EUR OTC",
        "F40EUR OTC",
        "JPN225 OTC",
        "100GBP OTC",
    ],
}

# ------------------------------------------------------------
# TIMEFRAMES
# ------------------------------------------------------------

TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

STATE = {
    "feed": "DISCONNECTED",
    "feed_message": "Waiting for Pocket Option feed",
    "last_tick": None,
    "selected_asset": "EUR/USD OTC",
    "selected_timeframe": "1m",
    "signal": "WAIT",
    "confidence": 0,
    "entry_price": None,
    "payout": None,
    "signal_time": None,
    "entry_deadline": None,
    "expiry_time": None,
    "scan": 0,
    "candles": {},
    "history": [],
}

LOCK = threading.Lock()


# ============================================================
# UTILITY
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def clean_number(value):
    try:
        return float(value)
    except Exception:
        return None


# ============================================================
# TECHNICAL INDICATORS
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

    result = 100 - (100 / (1 + rs))

    return result.fillna(50)


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
    """
    Lightweight PSAR implementation.
    """

    high = df["high"].values
    low = df["low"].values

    if len(df) < 5:
        return pd.Series(index=df.index, dtype=float)

    sar = np.zeros(len(df))

    bull = True
    af = step
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, len(df)):

        previous = sar[i - 1]

        if bull:
            sar[i] = previous + af * (ep - previous)

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
                af = min(maximum, af + step)

        else:
            sar[i] = previous + af * (ep - previous)

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
                af = min(maximum, af + step)

    return pd.Series(sar, index=df.index)


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(df):

    if df is None or len(df) < 50:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "reason": "Waiting for candle history",
            "indicators": {},
        }

    close = df["close"]

    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)

    r = rsi(close)

    macd_line, macd_signal = macd(close)

    cc = cci(df)

    ao = awesome_oscillator(df)

    sar = psar(df)

    last = -1

    score_call = 0
    score_put = 0

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if e9.iloc[last] > e21.iloc[last]:
        score_call += 1
    else:
        score_put += 1

    if e21.iloc[last] > e50.iloc[last]:
        score_call += 1
    else:
        score_put += 1

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if r.iloc[last] > 55:
        score_call += 1

    elif r.iloc[last] < 45:
        score_put += 1

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd_line.iloc[last] > macd_signal.iloc[last]:
        score_call += 1
    else:
        score_put += 1

    # --------------------------------------------------------
    # CCI
    # --------------------------------------------------------

    if cc.iloc[last] > 50:
        score_call += 1

    elif cc.iloc[last] < -50:
        score_put += 1

    # --------------------------------------------------------
    # AWESOME OSCILLATOR
    # --------------------------------------------------------

    if ao.iloc[last] > 0:
        score_call += 1
    else:
        score_put += 1

    # --------------------------------------------------------
    # PARABOLIC SAR
    # --------------------------------------------------------

    if close.iloc[last] > sar.iloc[last]:
        score_call += 1
    else:
        score_put += 1

    total = 7

    highest = max(score_call, score_put)

    confidence = int(
        min(
            99,
            round(
                50 +
                (highest / total) * 48
            )
        )
    )

    # Require meaningful confirmation.

    if score_call >= 5 and score_call > score_put:
        signal = "CALL"

    elif score_put >= 5 and score_put > score_call:
        signal = "PUT"

    else:
        signal = "WAIT"
        confidence = min(confidence, 69)

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": (
            f"CALL {score_call}/{total} | "
            f"PUT {score_put}/{total}"
        ),
        "indicators": {
            "EMA9": round(float(e9.iloc[last]), 6),
            "EMA21": round(float(e21.iloc[last]), 6),
            "EMA50": round(float(e50.iloc[last]), 6),
            "RSI": round(float(r.iloc[last]), 2),
            "MACD": round(float(macd_line.iloc[last]), 6),
            "MACD_SIGNAL": round(float(macd_signal.iloc[last]), 6),
            "CCI": round(float(cc.iloc[last]), 2),
            "AO": round(float(ao.iloc[last]), 6),
            "PSAR": round(float(sar.iloc[last]), 6),
        }
    }


# ============================================================
# FEED INGESTION
#
# This endpoint is intentionally separate from the dashboard.
# A Pocket Option-compatible connector can POST normalized
# candles/ticks here.
# ============================================================

FEED_TOKEN = os.environ.get("ALUCARD_FEED_TOKEN", "")


def authorized_feed(req):

    if not FEED_TOKEN:
        return True

    supplied = (
        req.headers.get("
