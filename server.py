from flask import Flask, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup, NavigableString
import re
from datetime import datetime
from urllib.parse import urljoin

app = Flask(__name__)

CURRENT_URL = "https://www.sahadan.com/iddaa-programi"
ARCHIVE_URL = "https://arsiv-origin.sahadan.com/Iddaa/program.aspx"
LIVE_URL = "https://www.sahadan.com/canli-sonuclar"

VERSION = "doruk-sahadan-live-v6"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

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
    r"^(?:\d{1,3}(?:\+\d{1,2})?['’]|DUR|MS|UZ|ERT)$",
    re.IGNORECASE
)


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        (value or "").replace("\xa0", " ")
    ).strip()


def now_iso():
    return datetime.utcnow().isoformat(
        timespec="seconds"
    ) + "Z"


def norm_odd(value):
    value = clean(value)

    if not value or value == "-":
        return None

    return value.replace(",", ".")


def fetch(url, timeout=25):
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


# ---------------------------------------------------------
# IDDAA ARŞİV PARSER
# ---------------------------------------------------------

def parse_archive(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    matches = []

    for tr in soup.find_all("tr"):

        cells = [
            clean(cell.get_text(" ", strip=True))
            for cell in tr.find_all(["td", "th"])
        ]

        cells = [
            cell for cell in cells
            if cell
        ]

        if not cells:
            continue

        time_index = next(
            (
                i
                for i, value in enumerate(cells)
                if TIME_RE.match(value)
            ),
            None
        )

        if time_index is None:
            continue

        tail = cells[time_index + 1:]

        if len(tail) < 3:
            continue

        pair_index = next(
            (
                i
                for i, value in enumerate(tail)
                if " - " in value
                and len(value) > 5
            ),
            None
        )

        if pair_index is None:
            continue

        pair = tail[pair_index]

        home, away = pair.split(
            " - ",
            1
        )

        home = clean(home)
        away = clean(away)

        if not home or not away:
            continue

        before_pair = tail[:pair_index]

        league = None

        for value in reversed(before_pair):
            upper = value.upper()

            if upper in {
                "IMAGE",
                "İMAGE"
            }:
                continue

            if len(value) <= 80:
                league = value
                break

        after_pair = tail[pair_index + 1:]

        code_index = next(
            (
                i
                for i, value in enumerate(after_pair)
                if CODE_RE.match(value)
            ),
            None
        )

        code = None
        odds = []

        if code_index is not None:

            code = after_pair[code_index]

            for value in after_pair[code_index + 1:]:

                if not ODD_RE.match(value):
                    continue

                odd = norm_odd(value)

                if odd is None:
                    continue

                odds.append(odd)

                if len(odds) == 3:
                    break

        if code is None and not odds:
            continue

        matches.append({
            "time": cells[time_index],
            "league": league,
            "home": home,
            "away": away,
            "code": code,
            "odds": {
                "1": odds[0] if len(odds) > 0 else None,
                "X": odds[1] if len(odds) > 1 else None,
                "2": odds[2] if len(odds) > 2 else None,
            }
        })

    result = []
    seen = set()

    for match in matches:

        key = (
            match["time"],
            match["home"],
            match["away"],
            match["code"]
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(match)

    return result


# ---------------------------------------------------------
# CURRENT IDDAA PAGE
# ---------------------------------------------------------

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

    for match in pattern.finditer(text):

        home = clean(
            match.group("home")
        )

        away = clean(
            match.group("away")
        )

        if not home or not away:
            continue

        matches.append({
            "time": match.group("time"),
            "league": None,
            "home": home,
            "away": away,
            "code": None,
            "odds": {
                "1": None,
                "X": None,
                "2": None
            }
        })

    return matches


# ---------------------------------------------------------
# SAHADAN CANLI MAÇ DURUMU
# ---------------------------------------------------------

def nearby_match_state(anchor):

    parent = anchor.parent

    if parent:

        nodes = list(parent.descendants)

        for node in reversed(nodes):

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

    for anchor in links:

        text = clean(
            anchor.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        state = nearby_match_state(
            anchor
        )

        # ---------------------------------------------
        # SKORLU MAÇ
        # ---------------------------------------------

        score_match = SCORE_RE.match(text)

        if score_match:

            home = clean(
                score_match.group(1)
            )

            home_score = int(
                score_match.group(2)
            )

            away_score = int(
                score_match.group(3)
            )

            away = clean(
                score_match.group(4)
            )

            if not home or not away:
                continue

            state_upper = str(
                state or ""
            ).upper()

            finished = state_upper in {
                "MS",
                "DUR"
            }

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
                    if finished
                    else "live"
                ),
                "minute": (
                    None
                    if finished
                    else state
                ),
                "state": state,
                "url": None
            })

            continue

        # ---------------------------------------------
        # HENÜZ BAŞLAMAMIŞ MAÇ
        # ---------------------------------------------

        scheduled_match = SCHEDULED_RE.match(
            text
        )

        if scheduled_match:

            home = clean(
                scheduled_match.group(1)
            )

            away = clean(
                scheduled_match.group(2)
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
                "url": None
            })

    return results


# ---------------------------------------------------------
# ANA SAYFA
# ---------------------------------------------------------

@app.get("/")
def index():

    return send_from_directory(
        ".",
        "index.html"
    )


# ---------------------------------------------------------
# VERSİYON TESTİ
# ---------------------------------------------------------

@app.get("/api/version")
def version():

    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "version": VERSION
    })


# ---------------------------------------------------------
# SAĞLIK TESTİ
# ---------------------------------------------------------

@app.get("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "version": VERSION,
        "time": now_iso()
    })


# ---------------------------------------------------------
# IDDAA PROGRAMI
# ---------------------------------------------------------

@app.get("/api/iddaa-program")
def iddaa_program():

    errors = []

    # Önce güncel Sahadan sayfası
    try:

        html = fetch(
            CURRENT_URL
        )

        matches = parse_current(
            html
        )

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

    except Exception as error:

        errors.append(
            "current_page: "
            + str(error)
        )

    # Arşiv yedeği
    try:

        html = fetch(
            ARCHIVE_URL
        )

        matches = parse_archive(
            html
        )

        return jsonify({
            "ok": True,
            "count": len(matches),
            "source": ARCHIVE_URL,
            "fetched_at": now_iso(),
            "matches": matches,
            "fallback_used": True,
            "notes": errors
        })

    except Exception as error:

        errors.append(
            "archive: "
            + str(error)
        )

        return jsonify({
            "ok": False,
            "count": 0,
            "source": CURRENT_URL,
            "fetched_at": now_iso(),
            "matches": [],
            "errors": errors
        }), 502


# ---------------------------------------------------------
# CANLI SKOR
# ---------------------------------------------------------

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
            match
            for match in matches
            if match["status"] == "live"
        ]

        finished_matches = [
            match
            for match in matches
            if match["status"] == "finished"
        ]

        scheduled_matches = [
            match
            for match in matches
            if match["status"] == "scheduled"
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
            "live_count": len(live_matches),
            "finished_count": len(finished_matches),
            "scheduled_count": len(scheduled_matches),
            "matches": matches
        })

    except Exception as error:

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
            "error": str(error)
        }), 502


# ---------------------------------------------------------
# DEBUG
# ---------------------------------------------------------

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
                )
            })

        except Exception as error:

            result["sources"].append({
                "name": name,
                "url": url,
                "error": str(error)
            })

    return jsonify(result)


# ---------------------------------------------------------
# ÇALIŞTIR
# ---------------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
