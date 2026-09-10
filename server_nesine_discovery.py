import os, re, json, time, threading
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
LIVE_URL = "https://www.nesine.com/iddaa/canli-skor/futbol"
app = Flask(__name__, static_folder=BASE, static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})

state = {"ok": False, "updated": None, "error": None, "page_text_sample": "", "network": []}
lock = threading.Lock()


def worker():
    global state
    while True:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context = browser.new_context(locale="tr-TR")
                page = context.new_page()

                def on_response(response):
                    try:
                        u = response.url
                        ct = (response.headers.get("content-type") or "").lower()
                        # Keep only likely data/API calls, not images/fonts/css/js.
                        if any(x in ct for x in ("json", "text/plain", "javascript")) or any(x in u.lower() for x in ("api", "live", "score", "event", "match")):
                            with lock:
                                if u not in state["network"]:
                                    state["network"].append(u)
                                    state["network"] = state["network"][-100:]
                    except Exception:
                        pass

                page.on("response", on_response)
                page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(5000)

                text = page.locator("body").inner_text(timeout=15000)
                sample = re.sub(r"\s+", " ", text).strip()[:5000]
                with lock:
                    state["ok"] = True
                    state["updated"] = datetime.now(timezone.utc).isoformat()
                    state["error"] = None
                    state["page_text_sample"] = sample

                # Keep browser alive briefly so late XHR/fetch calls are captured.
                page.wait_for_timeout(15000)
                browser.close()
        except Exception as e:
            with lock:
                state["ok"] = False
                state["updated"] = datetime.now(timezone.utc).isoformat()
                state["error"] = repr(e)
            time.sleep(10)


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")

@app.get("/api/debug")
def debug():
    with lock:
        return jsonify(state)

@app.get("/health")
def health():
    with lock:
        return jsonify({"ok": state["ok"], "updated": state["updated"], "error": state["error"]})

threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
