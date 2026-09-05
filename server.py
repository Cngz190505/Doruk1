from flask import Flask, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup, NavigableString
import re
from datetime import datetime

app = Flask(__name__)

CURRENT_URL = "https://www.sahadan.com/iddaa-programi"
ARCHIVE_URL = "https://arsiv-origin.sahadan.com/Iddaa/program.aspx"
LIVE_URL = "https://www.sahadan.com/canli-sonuclar"

VERSION = "doruk-sahadan-live-v6"

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

MINUTE_RE = re.compile(
    r"^(?:\d{1,3}(?:\+\d{1,2})?['’]|DUR|MS)$",
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

    if not s or s == "-":
        return None

    return s.replace(",", ".")


def now_iso():
    return datetime.utcnow().isoformat(
        timespec="seconds"
    ) + "Z"


def fetch(url, timeout=30):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout
    )

    response.raise_for_status()

    response.encoding = (
        response.apparent_encoding
        or response.encoding
    )

    return response.text


# =========================================================
# IDDAA ARŞİV PARSER
# =========================================================

def parse_archive(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    matches = []

    for tr in soup.find_all("tr"):

        row_text = clean(
            tr.get_text(
                " ",
                strip=True
            )
        )

        if not row_text:
            continue

        # Saat bul
        time_match = re.search(
            r"\b((?:[01]\d|2[0-3]):[0-5]\d)\b",
            row_text
        )

        if not time_match:
            continue

        match_time = time_match.group(1)

        after_time = row_text[
            time_match.end():
        ].strip()

        # -------------------------------------------------
        # Ana maç regex'i
        #
        # HOME - AWAY SCORE HALF CODE 1 X 2
        # -------------------------------------------------

        tail_re = re.compile(
            r"(?P<home>"
            r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]"
            r"[A-Za-zÇĞİÖŞÜçğıöşü0-9.'’&()/\-_ ]{1,80}?"
            r")"
            r"\s+-\s+"
            r"(?P<away>"
            r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]"
            r"[A-Za-zÇĞİÖŞÜçğıöşü0-9.'’&()/\-_ ]{1,80}?"
            r")"
            r"\s+"
            r"(?P<score>\d+\s*-\s*\d+)"
            r"\s+"
            r"(?P<half>\d+\s*-\s*\d+)"
            r"\s+"
            r"(?P<code>\d{5,6})"
            r"\s+"
            r"(?P<o1>\d{1,3}[.,]\d{1,2})"
            r"\s+"
            r"(?P<ox>\d{1,3}[.,]\d{1,2})"
            r"\s+"
            r"(?P<o2>\d{1,3}[.,]\d{1,2})"
        )

        found = tail_re.search(after_time)

        # -------------------------------------------------
        # Daha esnek ikinci parser
        # -------------------------------------------------

        if not found:

            loose_re = re.compile(
                r"(?P<home>"
                r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]"
                r"[A-Za-zÇĞİÖŞÜçğıöşü0-9.'’&()/\-_ ]{1,80}?"
                r")"
                r"\s+-\s+"
                r"(?P<away>"
                r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]"
                r"[A-Za-zÇĞİÖŞÜçğıöşü0-9.'’&()/\-_ ]{1,80}?"
                r")"
                r"(?:\s+\d+\s*-\s*\d+){0,2}"
                r"\s+"
                r"(?P<code>\d{5,6})"
                r"\s+"
                r"(?P<o1>\d{1,3}[.,]\d{1,2})"
                r"\s+"
                r"(?P<ox>\d{1,3}[.,]\d{1,2})"
                r"\s+"
                r"(?P<o2>\d{1,3}[.,]\d{1,2})"
            )

            found = loose_re.search(
                after_time
            )

        if not found:
            continue

        home = clean(
            found.group("home")
        )

        away = clean(
            found.group("away")
        )

        # -------------------------------------------------
        # Yanlış başlık / market kontrolü
        # -------------------------------------------------

        bad_terms = (
            "Alt Üst",
            "Alt/Üst",
            "Çifte Şans",
            "Tümü",
            "Maç Sonucu",
            "05.09.2026",
            "06.09.2026",
            "07.09.2026",
            "İY MS",
        )

        if any(
            term.lower() in home.lower()
            or term.lower() in away.lower()
            for term in bad_terms
        ):
            continue

        # -------------------------------------------------
        # Lig bilgisini maçtan önceki alandan al
        # -------------------------------------------------

        prefix = after_time[
            :found.start()
        ].strip()

        prefix_parts = prefix.split()

        league = (
            prefix_parts[-1]
            if prefix_parts
            else None
        )

        if league and len(league) > 30:
            league = None

        # -------------------------------------------------
        # 1 / X / 2 oranları
        # -------------------------------------------------

        odds = {
            "1": norm_odd(
                found.group("o1")
            ),
            "X": norm_odd(
                found.group("ox")
            ),
            "2": norm_odd(
                found.group("o2")
            ),
        }

        matches.append({
            "time": match_time,
            "league": league,
            "home": home,
            "away": away,
            "code": found.group("code"),
            "odds": odds,
        })

    # -----------------------------------------------------
    # Duplicate temizleme
    # -----------------------------------------------------

    result = []
    seen = set()

    for match in matches:

        key = (
            match["time"],
            match["home"].lower(),
            match["away"].lower(),
            match["code"],
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(match)

    return result


# =========================================================
# GÜNCEL IDDAA SAYFASI FALLBACK
# =========================================================

def parse_current(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = clean(
        soup.get_text(
            " ",
            strip=True
        )
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

        home = clean(
            m.group("home")
        )

        away = clean(
            m.group("away")
        )

        if not home or not away:
            continue

        matches.append({
            "time": m.group("time"),
            "league": None,
            "home": home,
            "away": away,
            "code": None,
            "odds": {
                "1": None,
                "X": None,
                "2": None,
            },
        })

    return matches


# =========================================================
# CANLI MAÇ DAKİKA / DURUM
# =========================================================

def nearby_match_state(anchor):

    parent = anchor.parent

    if parent:

        for node in reversed(
            list(parent.descendants)
        ):

            if node is anchor:
                break

            if isinstance(
                node,
                NavigableString
            ):

                value = clean(
                    str(node)
                )

                if (
                    value
                    and MINUTE_RE.match(value)
                ):
                    return value

    count = 0

    for node in anchor.previous_elements:

        if count >= 80:
            break

        count += 1

        if isinstance(
            node,
            NavigableString
        ):

            value = clean(
                str(node)
            )

            if (
                value
                and MINUTE_RE.match(value)
            ):
                return value

    return None


# =========================================================
# SAHADAN CANLI SKOR PARSER
# =========================================================

def parse_sahadan_live_matches(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    results = []
    seen = set()

    links = soup.find_all(
        "a",
        href=re.compile(
            r"/mac/",
            re.IGNORECASE
        )
    )

    for a in links:

        text = clean(
            a.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        state = nearby_match_state(a)

        # -------------------------------------------------
        # SKORLU MAÇ
        # -------------------------------------------------

        m = SCORE_RE.match(text)

        if m:

            home = clean(
                m.group(1)
            )

            home_score = int(
                m.group(2)
            )

            away_score = int(
                m.group(3)
            )

            away = clean(
                m.group(4)
            )

            if not home or not away:
                continue

            is_finished = (
                str(state or "").upper()
                in {"MS", "DUR"}
            )

            key = (
                home.lower(),
                away.lower()
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "score": (
                    f"{home_score}-{away_score}"
                ),
                "status": (
                    "finished"
                    if is_finished
                    else "live"
                ),
                "minute": (
                    None
                    if is_finished
                    else state
                ),
                "state": state,
                "url": None,
            })

            continue

        # -------------------------------------------------
        # BAŞLAMAMIŞ MAÇ
        # -------------------------------------------------

        m = SCHEDULED_RE.match(text)

        if m:

            home = clean(
                m.group(1)
            )

            away = clean(
                m.group(2)
            )

            if not home or not away:
                continue

            key = (
                home.lower(),
                away.lower()
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
                "minute": None,
                "state": None,
                "url": None,
            })

    return results


# =========================================================
# ANA SAYFA
# =========================================================

@app.get("/")
def index():

    return send_from_directory(
        ".",
        "index.html"
    )


# =========================================================
# VERSION
# =========================================================

@app.get("/api/version")
def version():

    return jsonify({
        "ok": True,
        "version": VERSION,
        "service": "iddaa-program-backend",
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
        "time": now_iso(),
    })


# =========================================================
# IDDAA PROGRAM
# =========================================================

@app.get("/api/iddaa-program")
def iddaa_program():

    errors = []

    # -----------------------------------------------------
    # ÖNCE ARŞİV
    # -----------------------------------------------------

    try:

        html = fetch(
            ARCHIVE_URL,
            timeout=25
        )

        matches = parse_archive(
            html
        )

        if matches:

            return jsonify({
                "ok": True,
                "count": len(matches),
                "source": ARCHIVE_URL,
                "fetched_at": now_iso(),
                "matches": matches,
            })

        errors.append(
            "archive: no matches parsed"
        )

    except Exception as error:

        errors.append(
            "archive: " + str(error)
        )

    # -----------------------------------------------------
    # ARŞİV ÇALIŞMAZSA GÜNCEL SAYFA
    # -----------------------------------------------------

    try:

        html = fetch(
            CURRENT_URL,
            timeout=25
        )

        matches = parse_current(
            html
        )

        return jsonify({
            "ok": True,
            "count": len(matches),
            "source": CURRENT_URL,
            "fetched_at": now_iso(),
            "matches": matches,
            "fallback_used": True,
            "notes": errors,
        })

    except Exception as error:

        errors.append(
            "current_page: " + str(error)
        )

        return jsonify({
            "ok": False,
            "count": 0,
            "source": CURRENT_URL,
            "fetched_at": now_iso(),
            "matches": [],
            "errors": errors,
        }), 502


# =========================================================
# SAHADAN CANLI
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

        finished_matches = [
            m for m in matches
            if m["status"] == "finished"
        ]

        scheduled_matches = [
            m for m in matches
            if m["status"] == "scheduled"
        ]

        elapsed = (
            datetime.utcnow()
            - started
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
            "live_count": len(
                live_matches
            ),
            "finished_count": len(
                finished_matches
            ),
            "scheduled_count": len(
                scheduled_matches
            ),
            "matches": matches,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "version": VERSION,
            "source": LIVE_URL,
            "fetched_at": now_iso(),
            "count": 0,
            "live_count": 0,
            "finished_count": 0,
            "scheduled_count": 0,
            "matches": [],
            "error": str(e),
        }), 502


# =========================================================
# DEBUG
# =========================================================

@app.get("/api/iddaa-debug")
def debug():

    result = {
        "ok": True,
        "version": VERSION,
        "sources": [],
    }

    for name, url in [
        ("current", CURRENT_URL),
        ("archive", ARCHIVE_URL),
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

            result["sources"].append({
                "name": name,
                "url": url,
                "html_size": len(html),
                "title": (
                    clean(
                        soup.title.get_text()
                    )
                    if soup.title
                    else None
                ),
                "archive_matches": len(
                    parse_archive(html)
                ),
                "current_matches": len(
                    parse_current(html)
                ),
            })

        except Exception as e:

            result["sources"].append({
                "name": name,
                "url": url,
                "error": str(e),
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
