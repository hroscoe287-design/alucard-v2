import base64
import io
import math
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string
from PIL import Image


# ============================================================
# ALUCARD V2
# GOTHIC MARKET INTELLIGENCE
# Render / Flask / Gunicorn
#
# Dependencies:
#   Flask
#   gunicorn
#   Pillow
#   requests
#
# NO OPENCV / cv2 REQUIRED
# ============================================================

app = Flask(__name__)

VERSION = "ALUCARD-V2.5"

FEED_TIMEOUT = 20
ENTRY_WINDOW_SECONDS = 12
FRACTAL_PERIOD = 2


# ============================================================
# CURRENCY / ASSET DATABASE
# ============================================================

CURRENCIES = [
    # Major Forex
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",

    # Forex Crosses
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURCAD",
    "EURNZD",
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "GBPCAD",
    "GBPNZD",
    "AUDJPY",
    "AUDCAD",
    "AUDCHF",
    "AUDNZD",
    "CADJPY",
    "CADCHF",
    "CHFJPY",
    "NZDJPY",
    "NZDCAD",

    # OTC
    "EURUSD_otc",
    "GBPUSD_otc",
    "USDJPY_otc",
    "USDCHF_otc",
    "AUDUSD_otc",
    "USDCAD_otc",
    "NZDUSD_otc",
    "EURGBP_otc",
    "EURJPY_otc",
    "GBPJPY_otc",
    "AUDJPY_otc",
    "CADJPY_otc",

    # Crypto
    "BTCUSD",
    "BTCUSD_otc",
    "ETHUSD",
    "ETHUSD_otc",
    "LTCUSD",
    "LTCUSD_otc",
    "XRPUSD",
    "XRPUSD_otc",
    "DOGEUSD",
    "DOGEUSD_otc",

    # Commodities
    "XAUUSD",
    "XAUUSD_otc",
    "XAGUSD",
    "XAGUSD_otc",
    "USOIL",
    "USOIL_otc",
    "UKOIL",
    "UKOIL_otc",
    "NATURALGAS",
    "NATURALGAS_otc",

    # Stocks
    "AAPL",
    "AAPL_otc",
    "TSLA",
    "TSLA_otc",
    "AMZN",
    "AMZN_otc",
    "MSFT",
    "MSFT_otc",
    "GOOGL",
    "GOOGL_otc",
    "META",
    "META_otc",
    "NVDA",
    "NVDA_otc",

    # Indices
    "SP500",
    "SP500_otc",
    "NASDAQ",
    "NASDAQ_otc",
    "DOW",
    "DOW_otc",
    "DAX",
    "DAX_otc",
    "FTSE",
    "FTSE_otc",
    "CAC40",
    "CAC40_otc",
    "NIKKEI",
    "NIKKEI_otc",
]


# ============================================================
# GLOBAL STATE
# ============================================================

STATE_LOCK = threading.Lock()

STATE = {
    "version": VERSION,

    "feed": "DISCONNECTED",
    "feed_health": "OFFLINE",
    "last_feed": 0.0,
    "last_feed_time": None,

    "asset": "UNKNOWN",
    "price": 0.0,

    "signal": "WAIT",
    "confidence": 0,

    "entry": 0.0,
    "entry_window": ENTRY_WINDOW_SECONDS,

    "candles": 0,

    "fractal": FRACTAL_PERIOD,

    "ema9": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,

    "rsi": 0.0,
    "atr": 0.0,
    "cci": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,

    "analysis": "Waiting for screen feed...",

    "image_received": False,
    "image_size": 0,

    "selected_currency": "EURUSD_otc",

    "payout": 0,

    "scan_count": 0,
    "signal_count": 0,

    "wins": 0,
    "losses": 0,

    "updated": None,
}


# ============================================================
# CANDLE / PRICE STORAGE
# ============================================================

PRICE_HISTORY = []

MAX_PRICES = 250


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if not values:
        return 0.0

    if len(values) < period:
        return sum(values) / len(values)

    multiplier = 2.0 / (period + 1.0)

    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (value - result) * multiplier + result

    return result


def calculate_rsi(values, period=14):
    if len(values) < 2:
        return 0.0

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

    if not gains:
        return 50.0

    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def calculate_atr(values, period=14):
    if len(values) < 2:
        return 0.0

    changes = []

    for i in range(1, len(values)):
        changes.append(abs(values[i] - values[i - 1]))

    recent = changes[-period:]

    if not recent:
        return 0.0

    return sum(recent) / len(recent)


def calculate_cci(values, period=20):
    if len(values) < 2:
        return 0.0

    recent = values[-period:]

    if not recent:
        return 0.0

    mean = sum(recent) / len(recent)

    deviation = sum(abs(x - mean) for x in recent) / len(recent)

    if deviation == 0:
        return 0.0

    current = recent[-1]

    return (current - mean) / (0.015 * deviation)


def calculate_macd(values):
    if len(values) < 5:
        return 0.0, 0.0

    fast = ema(values, 12)
    slow = ema(values, 26)

    macd_value = fast - slow

    # Small-history approximation for signal line.
    macd_values = []

    start = max(0, len(values) - 35)

    for i in range(start, len(values)):
        subset = values[:i + 1]

        if len(subset) < 3:
            continue

        macd_values.append(
            ema(subset, 12) - ema(subset, 26)
        )

    if not macd_values:
        signal = macd_value
    else:
        signal = ema(macd_values, 9)

    return macd_value, signal


def fractal_direction(values, period=2):
    """
    Simple fractal-style price structure.

    Positive = bullish structure
    Negative = bearish structure
    Zero = neutral
    """

    needed = period * 2 + 1

    if len(values) < needed:
        return 0

    center = len(values) - period - 1

    if center < period:
        return 0

    current = values[center]

    left = values[center - period:center]
    right = values[center + 1:center + period + 1]

    if current > max(left) and current > max(right):
        return 1

    if current < min(left) and current < min(right):
        return -1

    return 0


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze_prices(values):
    if len(values) < 5:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "analysis": "Collecting market data...",
            "ema9": ema(values, 9),
            "ema20": ema(values, 20),
            "ema50": ema(values, 50),
            "rsi": calculate_rsi(values),
            "atr": calculate_atr(values),
            "cci": calculate_cci(values),
            "macd": 0.0,
            "macd_signal": 0.0,
            "fractal": 0,
        }

    ema9_value = ema(values, 9)
    ema20_value = ema(values, 20)
    ema50_value = ema(values, 50)

    rsi_value = calculate_rsi(values)
    atr_value = calculate_atr(values)
    cci_value = calculate_cci(values)

    macd_value, macd_signal_value = calculate_macd(values)

    fractal = fractal_direction(
        values,
        FRACTAL_PERIOD
    )

    score = 0
    reasons = []

    # EMA trend
    if ema9_value > ema20_value:
        score += 2
        reasons.append("EMA9 above EMA20")
    elif ema9_value < ema20_value:
        score -= 2
        reasons.append("EMA9 below EMA20")

    if ema20_value > ema50_value:
        score += 2
        reasons.append("EMA20 above EMA50")
    elif ema20_value < ema50_value:
        score -= 2
        reasons.append("EMA20 below EMA50")

    # RSI
    if rsi_value >= 55:
        score += 1
        reasons.append("RSI bullish")
    elif rsi_value <= 45:
        score -= 1
        reasons.append("RSI bearish")

    # CCI
    if cci_value > 50:
        score += 1
        reasons.append("CCI bullish")
    elif cci_value < -50:
        score -= 1
        reasons.append("CCI bearish")

    # MACD
    if macd_value > macd_signal_value:
        score += 1
        reasons.append("MACD bullish")
    elif macd_value < macd_signal_value:
        score -= 1
        reasons.append("MACD bearish")

    # Fractal
    if fractal > 0:
        score += 1
        reasons.append("Fractal bullish")
    elif fractal < 0:
        score -= 1
        reasons.append("Fractal bearish")

    # Confidence is based on indicator agreement.
    strength = abs(score)

    confidence = int(
        clamp(
            50 + (strength * 7),
            0,
            96
        )
    )

    # Require meaningful agreement.
    if score >= 5:
        signal = "CALL"
    elif score <= -5:
        signal = "PUT"
    else:
        signal = "WAIT"

    if signal == "WAIT":
        confidence = min(confidence, 69)

    if signal == "CALL":
        analysis = "BULLISH — " + ", ".join(reasons[-4:])

    elif signal == "PUT":
        analysis = "BEARISH — " + ", ".join(reasons[-4:])

    else:
        analysis = "WAIT — indicators are not sufficiently aligned."

    return {
        "signal": signal,
        "confidence": confidence,
        "analysis": analysis,

        "ema9": ema9_value,
        "ema20": ema20_value,
        "ema50": ema50_value,

        "rsi": rsi_value,
        "atr": atr_value,
        "cci": cci_value,

        "macd": macd_value,
        "macd_signal": macd_signal_value,

        "fractal": fractal,
    }


# ============================================================
# FEED MANAGEMENT
# ============================================================

def mark_feed_live():
    with STATE_LOCK:
        STATE["feed"] = "LIVE"
        STATE["feed
