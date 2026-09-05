from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from urllib.parse import urljoin

app = Flask(__name__)

CURRENT_URL = "https://www.sahadan.com/iddaa-programi"
ARCHIVE_URL = "https://arsiv-origin.sahadan.com/Iddaa/program.aspx"
LIVE_URL = "https://www.sahadan.com/canli-sonuclar"

VERSION = "doruk-sahadan-live-v3"

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ODD_RE = re.compile(r"^(?:\d{1,3}[.,]\d{1,2}|-)$")
CODE_RE = re.compile(r"^\d{4,6}$")

SCORE_RE = re.compile(
    r"^\s*(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+?)\s*$"
)

SCHEDULED_RE = re.compile(
    r"^\s*(.+?)\s+v\s+(.+?)\s*$",
    re.IGNORECASE
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def clean(s):
    return re.sub(
        r"\s+",
        " ",
        (s or "").replace("\xa0", " ")
    ).strip()


def norm_odd(s):
    s = clean(s)
    return None if not s or s == "-" else s.replace(",", ".")


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def fetch(url, timeout=30):
    r = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout
    )
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


# =========================================================
# IDDAA - ARŞİV PARSER
# =========================================================

def parse_archive(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    for tr in soup.find_all("tr"):
        cells = [
            clean(x.get_text(" ", strip=True))
            for x in tr.find_all(["td", "th"])
        ]

        cells = [x for x in cells if x]

        if not cells:
            continue

        time_i = next(
            (
                i
                for i, x in enumerate(cells)
                if TIME_RE.match(x)
            ),
            None
        )

        if time_i is None:
            continue

        tail = cells[time_i + 1:]

        if len(tail) < 3:
            continue

        pair_i = next(
            (
                i
                for i, x in enumerate(tail)
                if " - " in x
                and len(x) > 5
                and not TIME_RE.match(x)
            ),
            None
        )

        if pair_i is None:
            continue

        pair = tail[pair_i]

        home, away = [
            clean(x)
            for x in pair.split(" - ", 1)
        ]

        if not home or not away:
            continue

        before_pair = tail[:pair_i]

        league = next(
            (
                x
                for x in reversed(before_pair)
                if x.upper() not in {"IMAGE", "İMAGE"}
                and len(x) <= 25
            ),
            None
        )

        after = tail[pair_i + 1:]

        code_i = next(
            (
                i
                for i, x in enumerate(after)
                if CODE_RE.match(x)
            ),
            None
        )

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

        if code is None and not odds:
            continue

        matches.append({
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
        })

    out = []
    seen = set()

    for m in matches:
        key = (
            m["time"],
            m["home"],
            m["away"],
            m["code"]
        )

        if key in seen:
            continue

        seen.add(key)
        out.append(m)

    return out


# =========================================================
# IDDAA - GÜNCEL SAYFA PARSER
# =========================================================

def parse_current(html):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(
        soup.get_text(" ", strip=True)
    )

    matches = []

    pattern = re.compile(
        r"(?P<home>"
        r"[A-Za-zÇĞİÖŞÜçğıöşü0-9().'&/\- ]{2,80}"
        r")\s+"
        r"(?P<time>"
        r"(?:[01]\d|2[0-3]):[0-5]\d"
        r")\s+"
        r"(?P<away>"
        r"[A-Za-zÇĞİÖŞÜçğıöşü0-9().'&/\- ]{2,80}"
        r")"
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
                "odds": {
                    "1": None,
                    "X": None,
                    "2": None
                },
            })

    return matches


# =========================================================
# SAHADAN CANLI SKOR PARSER
# =========================================================

def parse_sahadan_live_matches(html):
    soup = BeautifulSoup(html, "html.parser")

    results = []
    seen = set()

    # Sahadan canlı sayfasındaki maç linkleri
    links = soup.find_all(
        "a",
        href=re.compile(r"/mac/", re.IGNORECASE)
    )

    for a in links:
        text = clean(
            a.get_text(" ", strip=True)
        )

        if not text:
            continue

        href = a.get("href")

        if href:
            url = urljoin(
                LIVE_URL,
                href
            )
        else:
            url = None

        # -------------------------------------------------
        # CANLI / SKORLU MAÇ
        # Örnek:
        # Newcastle 0 - 1 Bournemouth
        # -------------------------------------------------

        m = SCORE_RE.match(text)

        if m:
            home = clean(m.group(1))
            home_score = int(m.group(2))
            away_score = int(m.group(3))
            away = clean(m.group(4))

            if not home or not away:
                continue

            key = (
                home.lower(),
                away.lower(),
                home_score,
                away_score
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "score": f"{home_score}-{away_score}",
                "status": "live",
                "url": url,
                "raw": text
            })

            continue

        # -------------------------------------------------
        # PROGRAMDA OLAN / HENÜZ BAŞLAMAMIŞ MAÇ
        # Örnek:
        # Erzurumspor FK v Konyaspor
        # -------------------------------------------------

        m = SCHEDULED_RE.match(text)

        if m:
            home = clean(m.group(1))
            away = clean(m.group(2))

            if not home or not away:
                continue

            key = (
                home.lower(),
                away.lower(),
                "scheduled"
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "home": home,
                "away": away,
                "home_score": None,
                "away_score": None,
                "score": None,
                "status": "scheduled",
                "url": url,
                "raw": text
            })

    return results


# =========================================================
# ANA SAYFA
# =========================================================

@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "version": VERSION,
        "source": CURRENT_URL
    })


# =========================================================
# VERSION TEST
# =========================================================

@app.get("/api/version")
def version():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "service": "iddaa-program-backend"
    })


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "version": VERSION,
        "time": now_iso()
    })


# =========================================================
# IDDAA PROGRAM
# =========================================================

@app.get("/api/iddaa-program")
def iddaa_program():
    errors = []

    # 1) Güncel Sahadan
    try:
        html = fetch(CURRENT_URL)

        matches = parse_current(html)

        if matches:
            return jsonify({
                "ok": True,
                "count": len(matches),
                "source": CURRENT_URL,
                "fetched_at": now_iso(),
                "matches": matches
            })

        errors.append(
            "current_page: no matches parsed"
        )

    except Exception as e:
        errors.append(
            "current_page: " + str(e)
        )

    # 2) Eski arşiv kaynak
    try:
        html = fetch(ARCHIVE_URL)

        matches = parse_archive(html)

        return jsonify({
            "ok": True,
            "count": len(matches),
            "source": ARCHIVE_URL,
            "fetched_at": now_iso(),
            "matches": matches,
            "fallback_used": True,
            "notes": errors
        })

    except Exception as e:
        errors.append(
            "archive: " + str(e)
        )

        return jsonify({
            "ok": False,
            "count": 0,
            "source": CURRENT_URL,
            "fetched_at": now_iso(),
            "matches": [],
            "errors": errors
        }), 502


# =========================================================
# SAHADAN CANLI SKOR
# =========================================================

@app.get("/api/sahadan-live")
def sahadan_live():
    started = datetime.utcnow()

    try:
        html = fetch(
            LIVE_URL,
            timeout=20
        )

        matches = parse_sahadan_live_matches(
            html
        )

        live_matches = [
            m for m in matches
            if m["status"] == "live"
        ]

        scheduled_matches = [
            m for m in matches
            if m["status"] == "scheduled"
        ]

        elapsed = (
            datetime.utcnow() - started
        ).total_seconds()

        return jsonify({
            "ok": True,
            "version": VERSION,
            "source": LIVE_URL,
            "fetched_at": now_iso(),
            "elapsed_seconds": round(
                elapsed,
                3
            ),
            "count": len(matches),
            "live_count": len(live_matches),
            "scheduled_count": len(
                scheduled_matches
            ),
            "matches": matches
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "version": VERSION,
            "source": LIVE_URL,
            "fetched_at": now_iso(),
            "count": 0,
            "live_count": 0,
            "scheduled_count": 0,
            "matches": [],
            "error": str(e)
        }), 502


# =========================================================
# IDDAA DEBUG
# =========================================================

@app.get("/api/iddaa-debug")
def debug():
    result = {
        "ok": True,
        "version": VERSION,
        "sources": []
    }

    for name, url in [
        ("current", CURRENT_URL),
        ("archive", ARCHIVE_URL)
    ]:

        try:
            html = fetch(
                url,
                timeout=20
            )

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            title = None

            if soup.title:
                title = clean(
                    soup.title.get_text()
                )

            result["sources"].append({
                "name": name,
                "url": url,
                "html_size": len(html),
                "title": title,
                "archive_matches": len(
                    parse_archive(html)
                ),
                "current_matches": len(
                    parse_current(html)
                )
            })

        except Exception as e:
            result["sources"].append({
                "name": name,
                "url": url,
                "error": str(e)
            })

    return jsonify(result)


# =========================================================
# LOCAL
# =========================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )
