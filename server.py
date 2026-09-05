from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

app = Flask(__name__)

CURRENT_URL = "https://www.sahadan.com/iddaa-programi"
ARCHIVE_URL = "https://arsiv-origin.sahadan.com/Iddaa/program.aspx"

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ODD_RE = re.compile(r"^(?:\d{1,3}[.,]\d{1,2}|-)$")
CODE_RE = re.compile(r"^\d{4,6}$")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()

def norm_odd(s):
    s = clean(s)
    return None if not s or s == "-" else s.replace(",", ".")

def fetch(url, timeout=30):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text

def parse_archive(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    # Legacy Sahadan archive is table-based and exposes:
    # time / league / home-away / match code / 1-X-2 / other markets.
    for tr in soup.find_all("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td", "th"])]
        cells = [x for x in cells if x]

        if not cells:
            continue

        time_i = next((i for i, x in enumerate(cells) if TIME_RE.match(x)), None)
        if time_i is None:
            continue

        tail = cells[time_i + 1:]
        if len(tail) < 3:
            continue

        # Find the cell containing the two teams. Archive text normally uses " - ".
        pair_i = next(
            (i for i, x in enumerate(tail)
             if " - " in x and len(x) > 5 and not TIME_RE.match(x)),
            None
        )
        if pair_i is None:
            continue

        pair = tail[pair_i]
        home, away = [clean(x) for x in pair.split(" - ", 1)]
        if not home or not away:
            continue

        before_pair = tail[:pair_i]
        league = next(
            (x for x in reversed(before_pair)
             if x.upper() not in {"IMAGE", "İMAGE"} and len(x) <= 25),
            None
        )

        after = tail[pair_i + 1:]

        # Locate a 4-6 digit match code and take the first three odds after it.
        code_i = next((i for i, x in enumerate(after) if CODE_RE.match(x)), None)

        code = None
        odds = []
        if code_i is not None:
            code = after[code_i]
            for x in after[code_i + 1:]:
                if ODD_RE.match(x):
                    v = norm_odd(x)
                    if v is not None:
                        odds.append(v)
                    if len(odds) == 3:
                        break

        # Some rows have the result/score between the teams and code.
        # We deliberately ignore those and only expose pre-match 1/X/2 odds.
        if code is None and not odds:
            continue

        item = {
            "time": cells[time_i],
            "league": league,
            "home": home,
            "away": away,
            "code": code,
            "odds": {
                "1": odds[0] if len(odds) > 0 else None,
                "X": odds[1] if len(odds) > 1 else None,
                "2": odds[2] if len(odds) > 2 else None,
            },
        }
        matches.append(item)

    # Deduplicate while preserving order.
    out = []
    seen = set()
    for m in matches:
        key = (m["time"], m["home"], m["away"], m["code"])
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out

def parse_current(html):
    # Current Next.js page: use visible text patterns when possible.
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    # This parser is intentionally conservative. If the current page is only
    # an RSC shell, we fall through to the legacy archive source below.
    matches = []
    pattern = re.compile(
        r"(?P<home>[A-Za-zÇĞİÖŞÜçğıöşü0-9().'&/\- ]{2,80})\s+"
        r"(?P<time>(?:[01]\d|2[0-3]):[0-5]\d)\s+"
        r"(?P<away>[A-Za-zÇĞİÖŞÜçğıöşü0-9().'&/\- ]{2,80})"
    )
    for m in pattern.finditer(text):
        home = clean(m.group("home"))
        away = clean(m.group("away"))
        if home and away:
            matches.append({
                "time": m.group("time"),
                "league": None,
                "home": home,
                "away": away,
                "code": None,
                "odds": {"1": None, "X": None, "2": None},
            })
    return matches

@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "source": CURRENT_URL
    })

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z"
    })

@app.get("/api/iddaa-program")
def iddaa_program():
    errors = []

    # 1) Try the current Sahadan page.
    try:
        html = fetch(CURRENT_URL)
        matches = parse_current(html)
        if matches:
            return jsonify({
                "ok": True,
                "count": len(matches),
                "source": CURRENT_URL,
                "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "matches": matches
            })
        errors.append("current_page: no matches parsed")
    except Exception as e:
        errors.append("current_page: " + str(e))

    # 2) Legacy Sahadan source. This is the important fallback:
    # it is a server-rendered ASPX table rather than the current Next.js shell.
    try:
        html = fetch(ARCHIVE_URL)
        matches = parse_archive(html)
        return jsonify({
            "ok": True,
            "count": len(matches),
            "source": ARCHIVE_URL,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "matches": matches,
            "fallback_used": True,
            "notes": errors
        })
    except Exception as e:
        errors.append("archive: " + str(e))
        return jsonify({
            "ok": False,
            "count": 0,
            "source": CURRENT_URL,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "matches": [],
            "errors": errors
        }), 502

@app.get("/api/iddaa-debug")
def debug():
    result = {"ok": True, "sources": []}
    for name, url in [("current", CURRENT_URL), ("archive", ARCHIVE_URL)]:
        try:
            html = fetch(url, timeout=20)
            result["sources"].append({
                "name": name,
                "url": url,
                "html_size": len(html),
                "title": clean(BeautifulSoup(html, "html.parser").title.get_text()) if BeautifulSoup(html, "html.parser").title else None,
                "archive_matches": len(parse_archive(html)),
                "current_matches": len(parse_current(html)),
            })
        except Exception as e:
            result["sources"].append({"name": name, "url": url, "error": str(e)})
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
