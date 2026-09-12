import os
import base64
from datetime import datetime, timezone

from flask import Flask, request, jsonify, Response, render_template_string

app = Flask(__name__)

# =========================================================
# ALUCARD V2 — ANDROID SCREEN FEED SERVER
# =========================================================

SCREEN_TOKEN = os.environ.get("ALUCARD_SCREEN_TOKEN", "").strip()

latest_frame = None
latest_received = None
latest_size = 0


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def authorized(req):
    if not SCREEN_TOKEN:
        return False

    token = req.headers.get("X-Alucard-Token", "").strip()

    if not token:
        auth = req.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    return token == SCREEN_TOKEN


def store_frame(data):
    global latest_frame
    global latest_received
    global latest_size

    latest_frame = data
    latest_received = now_iso()
    latest_size = len(data)


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "ALUCARD V2",
        "screen_endpoint": "/api/screen"
    })


# =========================================================
# RECEIVE ANDROID SCREEN FRAME
# =========================================================

@app.post("/api/screen")
def receive_screen():

    if not authorized(request):
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 401

    image_data = None

    # -----------------------------------------
    # Method 1: multipart image upload
    # -----------------------------------------

    if "image" in request.files:

        uploaded = request.files["image"]

        image_data = uploaded.read()

    # -----------------------------------------
    # Method 2: raw image POST
    # -----------------------------------------

    elif request.data:

        image_data = request.data

    # -----------------------------------------
    # Method 3: JSON base64 image
    # -----------------------------------------

    else:

        try:

            body = request.get_json(silent=True) or {}

            encoded = body.get("image", "")

            if encoded:

                if encoded.startswith("data:") and "," in encoded:
                    encoded = encoded.split(",", 1)[1]

                image_data = base64.b64decode(encoded)

        except Exception:

            image_data = None

    if not image_data:

        return jsonify({
            "ok": False,
            "error": "No image received"
        }), 400

    # Maximum frame size: 8 MB
    if len(image_data) > 8 * 1024 * 1024:

        return jsonify({
            "ok": False,
            "error": "Image exceeds 8 MB limit"
        }), 413

    store_frame(image_data)

    return jsonify({
        "ok": True,
        "service": "ALUCARD V2",
        "received_at": latest_received,
        "bytes": latest_size
    })


# =========================================================
# SCREEN FEED STATUS
# =========================================================

@app.get("/api/screen/status")
def screen_status():

    if latest_received is None:

        return jsonify({
            "screen_feed": "OFFLINE",
            "last_frame": None,
            "age_seconds": None
        })

    try:

        received = datetime.fromisoformat(latest_received)

        age = (
            now_utc() - received
        ).total_seconds()

    except Exception:

        age = None

    live = (
        age is not None
        and age <= 15
    )

    return jsonify({
        "screen_feed": "LIVE" if live else "OFFLINE",
        "last_frame": latest_received,
        "age_seconds": round(age, 2) if age is not None else None,
        "frame_bytes": latest_size
    })


# =========================================================
# SHOW MOST RECENT SCREEN
# =========================================================

@app.get("/api/screen/latest")
def latest_screen():

    if latest_frame is None:

        return jsonify({
            "ok": False,
            "error": "No Android screen frame received yet"
        }), 404

    return Response(
        latest_frame,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )


# =========================================================
# ALUCARD DASHBOARD
# =========================================================

HTML = """
<!DOCTYPE html>

<html>

<head>

<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>ALUCARD V2</title>

<style>

body {
    margin: 0;
    background: #070707;
    color: white;
    font-family: Arial, sans-serif;
}

.header {
    text-align: center;
    padding: 22px 10px;
    border-bottom: 1px solid #333;
}

.title {
    font-size: 30px;
    font-weight: bold;
    letter-spacing: 4px;
}

.subtitle {
    color: #999;
    margin-top: 7px;
    letter-spacing: 2px;
}

.card {
    max-width: 1100px;
    margin: 20px auto;
    padding: 20px;
    background: #111;
    border: 1px solid #333;
    border-radius: 14px;
}

.feed-status {
    font-size: 22px;
    font-weight: bold;
}

.live {
    color: #4cff88;
}

.offline {
    color: #ff5555;
}

.waiting {
    color: #ffaa33;
}

.info {
    margin-top: 10px;
    color: #999;
    font-size: 14px;
}

.screen-container {
    margin-top: 20px;
    background: black;
    border-radius: 10px;
    overflow: hidden;
    text-align: center;
}

.screen {
    width: 100%;
    max-height: 700px;
    object-fit: contain;
}

.hidden {
    display: none;
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

</div>


<div class="card">

    <div class="feed-status">

        ANDROID SCREEN:
        <span id="status"
              class="waiting">
            CONNECTING...
        </span>

    </div>

    <div id="info"
         class="info">
        Checking screen feed...
    </div>


    <div class="screen-container">

        <img id="screen"
             class="screen hidden">

    </div>

</div>


<script>

async function updateScreen() {

    try {

        const response =
            await fetch(
                "/api/screen/status?t=" +
                Date.now()
            );

        const data =
            await response.json();

        const status =
            document.getElementById("status");

        const info =
            document.getElementById("info");

        const image =
            document.getElementById("screen");


        if (data.screen_feed === "LIVE") {

            status.textContent = "LIVE";
            status.className = "live";

            info.textContent =
                "Android screen received " +
                data.age_seconds +
                " seconds ago.";


            image.classList.remove("hidden");

            image.src =
                "/api/screen/latest?t=" +
                Date.now();

        }

        else {

            status.textContent = "OFFLINE";
            status.className = "offline";

            info.textContent =
                "Waiting for Android screen capture...";

            image.classList.add("hidden");

        }

    }

    catch (error) {

        const status =
            document.getElementById("status");

        const info =
            document.getElementById("info");

        status.textContent = "OFFLINE";
        status.className = "offline";

        info.textContent =
            "Unable to contact Alucard server.";

    }

}


updateScreen();

setInterval(
    updateScreen,
    3000
);

</script>

</body>

</html>
"""


@app.get("/")
def dashboard():

    return render_template_string(HTML)


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
