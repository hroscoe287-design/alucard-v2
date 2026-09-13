import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ============================================================
# ALUCARD SIGNAL BOT
# Screen-stream receiver / signal dashboard
# ============================================================

RTSP_FEED_URL = os.getenv("RTSP_FEED_URL", "").strip()
FEED_TOKEN = os.getenv("FEED_TOKEN", "").strip()

DEFAULT_ASSET = os.getenv("DEFAULT_ASSET", "EUR/USD OTC")
EXPIRY_SECONDS = int(os.getenv("EXPIRY_SECONDS", "300"))

state = {
    "connected": False,
    "feed_url": RTSP_FEED_URL,
    "last_frame": None,
    "last_update": None,
    "asset": DEFAULT_ASSET,
    "direction": "WAIT",
    "confidence": 0,
    "entry_price": "--",
    "expiry": EXPIRY_SECONDS,
    "message": "Waiting for Android screen stream",
    "scan_count": 0,
    "feed_status": "WAITING",
}


# ============================================================
# BACKGROUND FEED MONITOR
# ============================================================

def feed_monitor():
    while True:
        try:
            state["scan_count"] += 1

            if RTSP_FEED_URL:
                state["feed_status"] = "RTSP CONFIGURED"
                state["message"] = "Waiting for screen-stream frames"
            else:
                state["feed_status"] = "NO RTSP URL"
                state["message"] = "Set RTSP_FEED_URL in Render Environment"

        except Exception as exc:
            state["feed_status"] = "ERROR"
            state["message"] = str(exc)

        time.sleep(5)


threading.Thread(target=feed_monitor, daemon=True).start()


# ============================================================
# MAIN DASHBOARD
# ============================================================

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>ALUCARD SIGNAL BOT</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            background:
                radial-gradient(circle at top, #260000 0%, #090909 45%, #000000 100%);
            color: white;
            font-family: Arial, Helvetica, sans-serif;
            min-height: 100vh;
        }

        .header {
            padding: 18px;
            text-align: center;
            border-bottom: 1px solid #4d1111;
            background: rgba(0,0,0,.65);
        }

        .title {
            font-size: 30px;
            font-weight: 900;
            letter-spacing: 3px;
            color: #ff3030;
            text-shadow: 0 0 15px #ff0000;
        }

        .subtitle {
            margin-top: 5px;
            color: #aaa;
            font-size: 12px;
            letter-spacing: 2px;
        }

        .container {
            width: 94%;
            max-width: 1200px;
            margin: 18px auto;
        }

        .status {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 15px;
        }

        .status-card {
            flex: 1;
            min-width: 150px;
            padding: 14px;
            background: rgba(20,20,20,.9);
            border: 1px solid #441010;
            border-radius: 10px;
        }

        .label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
        }

        .value {
            margin-top: 6px;
            font-size: 18px;
            font-weight: bold;
        }

        .green {
            color: #39ff88;
        }

        .red {
            color: #ff4040;
        }

        .yellow {
            color: #ffd84d;
        }

        .panel {
            background: rgba(10,10,10,.92);
            border: 1px solid #441010;
            border-radius: 14px;
            overflow: hidden;
            margin-bottom: 15px;
            box-shadow: 0 0 25px rgba(120,0,0,.15);
        }

        .panel-title {
            padding: 13px 16px;
            background: #160606;
            border-bottom: 1px solid #441010;
            font-weight: bold;
            letter-spacing: 1px;
        }

        .screen {
            height: 400px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            background:
                linear-gradient(135deg,#071b0b,#001006,#061b0a);
            color: #777;
            padding: 20px;
        }

        .screen-inner {
            max-width: 600px;
        }

        .screen-icon {
            font-size: 60px;
            margin-bottom: 15px;
        }

        .signal {
            text-align: center;
            padding: 25px;
        }

        .asset {
            font-size: 24px;
            font-weight: bold;
        }

        .direction {
            font-size: 65px;
            font-weight: 900;
            margin: 10px 0;
            text-shadow: 0 0 20px currentColor;
        }

        .confidence {
            font-size: 20px;
            color: #ddd;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit,minmax(160px,1fr));
            gap: 10px;
            padding: 15px;
        }

        .indicator {
            padding: 15px;
            background: #111;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
        }

        .indicator strong {
            display: block;
            margin-top: 5px;
            font-size: 18px;
        }

        .footer {
            text-align: center;
            color: #666;
            font-size: 11px;
            padding: 20px;
        }

        @media(max-width:600px) {
            .title {
                font-size: 23px;
            }

            .screen {
                height: 300px;
            }

            .direction {
                font-size: 48px;
            }
        }
    </style>
</head>

<body>

<div class="header">
    <div class="title">ALUCARD SIGNAL BOT</div>
    <div class="subtitle">GOTHIC MARKET INTELLIGENCE</div>
</div>

<div class="container">

    <div class="status">

        <div class="status-card">
            <div class="label">Feed</div>
            <div id="feedStatus" class="value yellow">WAITING</div>
        </div>

        <div class="status-card">
            <div class="label">Scan</div>
            <div id="scan" class="value">0</div>
        </div>

        <div class="status-card">
            <div class="label">Asset</div>
            <div id="assetTop" class="value">EUR/USD OTC</div>
        </div>

        <div class="status-card">
            <div class="label">System</div>
            <div id="systemStatus" class="value green">ONLINE</div>
        </div>

    </div>


    <div class="panel">

        <div class="panel-title">
            ANDROID SCREEN STREAM
        </div>

        <div class="screen">

            <div class="screen-inner">

                <div class="screen-icon">🩸</div>

                <div id="streamMessage">
                    Waiting for Android Pocket Option screen stream
                </div>

                <div style="margin-top:10px;font-size:11px;color:#555;">
                    RTSP FEED
                </div>

                <div id="rtsp"
                     style="margin-top:5px;font-size:12px;color:#777;">
                    Not configured
                </div>

            </div>

        </div>

    </div>


    <div class="panel">

        <div class="panel-title">
            CURRENT SIGNAL
        </div>

        <div class="signal">

            <div id="asset" class="asset">
                EUR/USD OTC
            </div>

            <div id="direction"
                 class="direction yellow">
                WAIT
            </div>

            <div id="confidence"
                 class="confidence">
                Confidence: 0%
            </div>

            <div style="margin-top:15px;color:#888;">
                Entry Price:
                <span id="entryPrice">--</span>
            </div>

            <div style="margin-top:8px;color:#888;">
                Expiry:
                <span id="expiry">5 minutes</span>
            </div>

        </div>

    </div>


    <div class="panel">

        <div class="panel-title">
            MARKET ENGINE
        </div>

        <div class="grid">

            <div class="indicator">
                EMA
                <strong id="ema">WAIT</strong>
            </div>

            <div class="indicator">
                RSI
                <strong id="rsi">WAIT</strong>
            </div>

            <div class="indicator">
                STOCHASTIC
                <strong id="stoch">WAIT</strong>
            </div>

            <div class="indicator">
                MACD
                <strong id="macd">WAIT</strong>
            </div>

            <div class="indicator">
                ALLIGATOR
                <strong id="alligator">WAIT</strong>
            </div>

            <div class="indicator">
                DATA
                <strong id="dataState">WAITING</strong>
            </div>

        </div>

    </div>

</div>


<div class="footer">
    ALUCARD SIGNAL BOT • SCREEN ANALYSIS MODE • DEMO / INFORMATIONAL USE
</div>


<script>

async function updateDashboard() {

    try {

        const response = await fetch("/api/status");

        if (!response.ok) {
            throw new Error("Status request failed");
        }

        const data = await response.json();

        document.getElementById("feedStatus").textContent =
            data.feed_status;

        document.getElementById("scan").textContent =
            data.scan_count;

        document.getElementById("asset").textContent =
            data.asset;

        document.getElementById("assetTop").textContent =
            data.asset;

        document.getElementById("streamMessage").textContent =
            data.message;

        document.getElementById("rtsp").textContent =
            data.feed_url || "Not configured";

        document.getElementById("direction").textContent =
            data.direction;

        document.getElementById("confidence").textContent =
            "Confidence: " + data.confidence + "%";

        document.getElementById("entryPrice").textContent =
            data.entry_price;

        document.getElementById("expiry").textContent =
            formatExpiry(data.expiry);

        document.getElementById("dataState").textContent =
            data.feed_status;

    } catch (error) {

        document.getElementById("systemStatus").textContent =
           
