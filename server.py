import os
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

NESINE_API = "https://bulten.nesine.com/api/bulten/getprebultenfull"

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36",
    "Referer": "https://www.nesine.com/",
    "Origin": "https://www.nesine.com",
    "Cache-Control": "no-cache",
}

state = {
    "live": [],
    "results": [],
    "updated": None,
    "error": None,
}

def parse_matches(data):
    out = []
    sg = data.get("sg", {}) if isinstance(data, dict) else {}
    events = sg.get("EA", []) if isinstance(sg, dict) else []

    if isinstance(events, dict):
        events = list(events.values())

    for x in events:
        if not isinstance(x, dict):
            continue

        item = {
            "id": x.get("C"),
            "home": x.get("HN"),
            "away": x.get("AN"),
            "date": x.get("D"),
            "time": x.get("T"),
            "type": x.get("TYPE"),
            "league_id": x.get("LC"),
            "name": x.get("ENO"),
        }

        if item["home"] or item["away"]:
            out.append(item)

    return out

def fetch_nesine():
    try:
        response = requests.get(
            NESINE_API,
            headers=HEADERS,
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()

        data = response.json()
        matches = parse_matches(data)

        state["results"] = matches
        state["updated"] = datetime.now(timezone.utc).isoformat()
        state["error"] = None

        print(f"[NESINE] OK | {len(matches)} mac", flush=True)

    except Exception as exc:
        state["error"] = str(exc)
        print(f"[NESINE] ERROR | {exc}", flush=True)

def worker():
    time.sleep(3)
    while True:
        fetch_nesine()
        time.sleep(10)

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/api/live")
def api_live():
    return jsonify({
        "error": state["error"],
        "live": state["live"],
        "updated": state["updated"],
    })

@app.route("/api/results")
def api_results():
    return jsonify({
        "error": state["error"],
        "results": state["results"],
        "updated": state["updated"],
    })

@app.route("/api/test")
def api_test():
    fetch_nesine()
    return jsonify({
        "ok": state["error"] is None,
        "error": state["error"],
        "updated": state["updated"],
        "match_count": len(state["results"]),
        "sample": state["results"][:5],
    })

# Gunicorn import edildiğinde sunucu portunu bloke etmemesi için
# veri çekme işlemini gecikmeli başlatıyoruz.
threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
