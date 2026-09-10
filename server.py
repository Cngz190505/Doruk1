import os, json, time, threading, sqlite3, re
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "matches.db")
LIVE_URL = os.getenv("LIVE_URL", "https://www.nesine.com/iddaa/canli-skor/futbol")

app = Flask(__name__, static_folder=BASE, static_url_path="")

lock = threading.Lock()
state = {"live": [], "finished": [], "updated": None, "error": None}

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS matches (
        match_key TEXT PRIMARY KEY,
        league TEXT, home TEXT, away TEXT, home_score TEXT, away_score TEXT,
        status TEXT, match_time TEXT, updated_at TEXT
    )""")
    c.commit()
    return c

def save_matches(items):
    c = db()
    now = datetime.now(timezone.utc).isoformat()
    for m in items:
        c.execute("""INSERT INTO matches(match_key,league,home,away,home_score,away_score,status,match_time,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(match_key) DO UPDATE SET
                     league=excluded.league, home=excluded.home, away=excluded.away,
                     home_score=excluded.home_score, away_score=excluded.away_score,
                     status=excluded.status, match_time=excluded.match_time, updated_at=excluded.updated_at""",
                  (m["key"],m.get("league",""),m["home"],m["away"],str(m.get("home_score","-")),
                   str(m.get("away_score","-")),m.get("status","LIVE"),m.get("time",""),now))
    c.commit(); c.close()

def read_finished():
    c=db()
    rows=c.execute("""SELECT match_key,league,home,away,home_score,away_score,status,match_time,updated_at
                      FROM matches WHERE status='FINISHED' ORDER BY updated_at DESC LIMIT 500""").fetchall()
    c.close()
    return [{"key":r[0],"league":r[1],"home":r[2],"away":r[3],"home_score":r[4],
             "away_score":r[5],"status":r[6],"time":r[7],"updated_at":r[8]} for r in rows]

def normalize_text(x):
    return re.sub(r"\s+"," ",x or "").strip()

def extract_from_page(page):
    # We deliberately keep extraction generic for the first deployment.
    # After Render is live, the actual DOM can be inspected and selectors tightened.
    data = page.locator("body").inner_text(timeout=10000)
    items=[]
    # Common score-line patterns are intentionally conservative.
    # This first pass is a connectivity test; exact selectors come next.
    for line in [normalize_text(x) for x in data.splitlines() if normalize_text(x)]:
        if " - " in line and len(line) < 100:
            parts = [x.strip() for x in line.split(" - ", 1)]
            if len(parts)==2 and parts[0] and parts[1]:
                items.append({"key": line.lower(), "league":"", "home":parts[0],
                               "away":parts[1], "home_score":"-", "away_score":"-",
                               "status":"LIVE", "time":""})
    # Deduplicate
    seen=set(); out=[]
    for x in items:
        if x["key"] not in seen:
            seen.add(x["key"]); out.append(x)
    return out[:300]

def browser_worker():
    global state
    while True:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
                page = browser.new_page(locale="tr-TR")
                page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=45000)
                try: page.wait_for_load_state("networkidle", timeout=15000)
                except Exception: pass
                while True:
                    try:
                        items = extract_from_page(page)
                        save_matches(items)
                        with lock:
                            state["live"]=items
                            state["finished"]=read_finished()
                            state["updated"]=datetime.now().isoformat(timespec="seconds")
                            state["error"]=None
                        # Let the source page itself update; reload only as a fallback.
                        page.wait_for_timeout(3000)
                    except Exception as e:
                        with lock: state["error"]=str(e)
                        try: page.reload(wait_until="domcontentloaded", timeout=30000)
                        except Exception: time.sleep(5)
        except Exception as e:
            with lock: state["error"]=str(e)
            time.sleep(10)

@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")

@app.get("/api/live")
def api_live():
    with lock: return jsonify(state)

@app.get("/api/results")
def api_results():
    return jsonify({"results": read_finished()})

@app.get("/health")
def health():
    return jsonify({"ok": True, "updated": state.get("updated"), "error": state.get("error")})

if __name__ == "__main__":
    db()
    threading.Thread(target=browser_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")))
