from flask import Flask, jsonify, send_file
import requests
import time
import threading
from datetime import datetime, timezone

app = Flask(__name__)

NESINE_API = "https://bulten.nesine.com/api/bulten/getprebultenfull"

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36",
    "Referer": "https://www.nesine.com/",
    "Origin": "https://www.nesine.com",
    "Cache-Control": "no-cache",
}

state = {
    "raw": None,
    "live": [],
    "results": [],
    "updated": None,
    "error": None,
}

def parse_matches(data):
    """Nesine bültenindeki maçları mümkün olduğunca toleranslı şekilde ayırır."""
    out = []
    try:
        sg = data.get("sg", {})
        events = sg.get("EA", [])
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
                "raw": x,
            }
            if item["home"] or item["away"]:
                out.append(item)
    except Exception:
        pass
    return out

def fetch_nesine():
    try:
        r = requests.get(
            NESINE_API,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        r.raise_for_status()

        # requests gzip/deflate sıkıştırmasını normalde otomatik açar.
        data = r.json()

        matches = parse_matches(data)

        # İlk aşamada endpoint'in gerçekten çalıştığını doğruluyoruz.
        # Canlı/biten ayrımını sonraki adımda gerçek alanlara göre netleştireceğiz.
        now = datetime.now(timezone.utc).isoformat()

        state["raw"] = data
        state["live"] = []
        state["results"] = matches
        state["updated"] = now
        state["error"] = None

        print(f"[NESINE] OK | toplam maç: {len(matches)}", flush=True)

    except Exception as e:
        state["error"] = str(e)
        print(f"[NESINE] ERROR | {e}", flush=True)

def worker():
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

# Render/Gunicorn worker başlarken veri çekme döngüsünü başlat.
threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
