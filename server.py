from flask import Flask, jsonify, send_from_directory
import requests
import re
import json
import time
from datetime import datetime

app = Flask(__name__)

NESINE_URL = "https://bulten.nesine.com/api/bulten/getprebultenfull"
VERSION = "nesine-v2"
CACHE_SECONDS = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nesine.com/",
    "Origin": "https://www.nesine.com",
}

session = requests.Session()
session.headers.update(HEADERS)

cache = {
    "time": 0,
    "data": None
}


def now_iso():
    return datetime.utcnow().replace(
        microsecond=0
    ).isoformat() + "Z"


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_value(obj, keys):
    if not isinstance(obj, dict):
        return None

    lowered = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]

        key_lower = key.lower()

        if (
            key_lower in lowered
            and lowered[key_lower] not in (None, "")
        ):
            return lowered[key_lower]

    return None


def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj

        for value in obj.values():
            yield from walk_dicts(value)

    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)


def normalize_odd(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if value <= 0:
            return None

        return round(float(value), 2)

    text = clean(value).replace(",", ".")

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        number = float(match.group(0))

        if number <= 0:
            return None

        return round(number, 2)

    except Exception:
        return None


def extract_teams(obj):

    home = first_value(
        obj,
        [
            "home",
            "homeTeam",
            "homeTeamName",
            "HomeTeam",
            "HomeTeamName",
            "team1",
            "Team1",
            "competitor1",
            "Competitor1",
            "home_name",
            "homeName",
        ]
    )

    away = first_value(
        obj,
        [
            "away",
            "awayTeam",
            "awayTeamName",
            "AwayTeam",
            "AwayTeamName",
            "team2",
            "Team2",
            "competitor2",
            "Competitor2",
            "away_name",
            "awayName",
        ]
    )

    if home and away:
        return clean(home), clean(away)

    match_name = first_value(
        obj,
        [
            "match_name",
            "matchName",
            "eventName",
            "EventName",
            "name",
            "Name",
            "match",
            "Match",
        ]
    )

    if match_name:

        parts = re.split(
            r"\s+-\s+|\s+vs\.?\s+|\s+v\s+",
            clean(match_name),
            maxsplit=1
        )

        if len(parts) == 2:
            return (
                clean(parts[0]),
                clean(parts[1])
            )

    return "", ""


def extract_odds(obj):

    result = {
        "1": None,
        "X": None,
        "2": None
    }

    direct = first_value(
        obj,
        [
            "odds",
            "Odds",
            "odd",
            "Odd",
            "matchOdds",
            "match_odds",
            "mainOdds",
        ]
    )

    sources = []

    if isinstance(direct, dict):
        sources.append(direct)

    sources.append(obj)

    for source in sources:

        if not isinstance(source, dict):
            continue

        # 1
        for key in [
            "1",
            "1.0",
            "homeOdd",
            "homeOdds",
            "ms1",
        ]:

            odd = normalize_odd(
                first_value(source, [key])
            )

            if odd is not None:
                result["1"] = odd
                break

        # X
        for key in [
            "X",
            "x",
            "draw",
            "drawOdd",
            "drawOdds",
            "msx",
        ]:

            odd = normalize_odd(
                first_value(source, [key])
            )

            if odd is not None:
                result["X"] = odd
                break

        # 2
        for key in [
            "2",
            "2.0",
            "awayOdd",
            "awayOdds",
            "ms2",
        ]:

            odd = normalize_odd(
                first_value(source, [key])
            )

            if odd is not None:
                result["2"] = odd
                break

    nested = first_value(
        obj,
        [
            "markets",
            "Markets",
            "market",
            "Market",
            "outcomes",
            "Outcomes",
            "selections",
            "Selections",
        ]
    )

    if isinstance(nested, list):

        for item in nested:

            if not isinstance(item, dict):
                continue

            label = clean(
                first_value(
                    item,
                    [
                        "label",
                        "name",
                        "Name",
                        "code",
                        "Code",
                        "selection",
                        "Selection",
                        "type",
                        "Type",
                    ]
                )
            ).upper()

            odd = normalize_odd(
                first_value(
                    item,
                    [
                        "odd",
                        "Odd",
                        "odds",
                        "Odds",
                        "value",
                        "Value",
                        "price",
                        "Price",
                    ]
                )
            )

            if odd is None:
                continue

            if label in ("1", "MS1", "HOME"):
                result["1"] = odd

            elif label in ("X", "MSX", "DRAW"):
                result["X"] = odd

            elif label in ("2", "MS2", "AWAY"):
                result["2"] = odd

    return result


def normalize_match(obj):

    if not isinstance(obj, dict):
        return None

    home, away = extract_teams(obj)

    if not home or not away:
        return None

    if len(home) > 100 or len(away) > 100:
        return None

    date = clean(
        first_value(
            obj,
            [
                "date",
                "Date",
                "matchDate",
                "MatchDate",
                "eventDate",
                "EventDate",
            ]
        )
    )

    match_time = clean(
        first_value(
            obj,
            [
                "time",
                "Time",
                "matchTime",
                "MatchTime",
                "eventTime",
                "EventTime",
            ]
        )
    )

    league = clean(
        first_value(
            obj,
            [
                "league",
                "League",
                "leagueName",
                "LeagueName",
                "competition",
                "Competition",
                "tournament",
                "Tournament",
            ]
        )
    )

    league_code = clean(
        first_value(
            obj,
            [
                "league_code",
                "leagueCode",
                "LeagueCode",
                "competitionCode",
                "CompetitionCode",
            ]
        )
    )

    code = clean(
        first_value(
            obj,
            [
                "code",
                "Code",
                "matchCode",
                "MatchCode",
                "eventCode",
                "EventCode",
                "eventId",
                "EventId",
                "id",
                "Id",
            ]
        )
    )

    match_name = clean(
        first_value(
            obj,
            [
                "match_name",
                "matchName",
                "eventName",
                "EventName",
            ]
        )
    )

    if not match_name:
        match_name = f"{home} - {away}"

    return {
        "home": home,
        "away": away,
        "date": date,
        "time": match_time,
        "league": league,
        "league_code": league_code,
        "match_name": match_name,
        "code": code,
        "odds": extract_odds(obj),
        "type": 1
    }


def parse_nesine(payload):

    matches = []
    seen = set()

    for obj in walk_dicts(payload):

        match = normalize_match(obj)

        if not match:
            continue

        key = (
            match["date"],
            match["time"],
            match["home"].casefold(),
            match["away"].casefold(),
            match["code"],
        )

        if key in seen:
            continue

        seen.add(key)
        matches.append(match)

    matches.sort(
        key=lambda x: (
            x.get("date", ""),
            x.get("time", ""),
            x.get("league", ""),
            x.get("home", ""),
        )
    )

    return matches


def fetch_nesine():

    current_time = time.time()

    if (
        cache["data"] is not None
        and current_time - cache["time"] < CACHE_SECONDS
    ):
        return cache["data"]

    response = session.get(
        NESINE_URL,
        timeout=25
    )

    response.raise_for_status()

    payload = response.json()

    matches = parse_nesine(payload)

    result = {
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": VERSION,
        "source": NESINE_URL,
        "fetched_at": now_iso(),
        "count": len(matches),
        "matches": matches,
    }

    cache["time"] = time.time()
    cache["data"] = result

    return result


# ------------------------------------------------------------
# ANA SAYFA
# ------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(
        ".",
        "index.html"
    )


# ------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------

@app.route("/api/health")
def health():

    return jsonify({
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": VERSION,
        "message": "Nesine veri servisi çalışıyor.",
        "endpoints": {
            "/api/health": "Servis durumu",
            "/api/nesine": "Nesine maç ve oran verileri",
            "/api/version": "Versiyon"
        }
    })


# ------------------------------------------------------------
# NESINE API
# ------------------------------------------------------------

@app.route("/api/nesine")
def nesine():

    try:

        return jsonify(
            fetch_nesine()
        )

    except requests.RequestException as error:

        return jsonify({
            "ok": False,
            "project": "Nesine Veri Sistemi",
            "version": VERSION,
            "error": f"Nesine bağlantı hatası: {error}",
            "count": 0,
            "matches": []
        }), 502

    except (ValueError, json.JSONDecodeError) as error:

        return jsonify({
            "ok": False,
            "project": "Nesine Veri Sistemi",
            "version": VERSION,
            "error": f"Nesine JSON okunamadı: {error}",
            "count": 0,
            "matches": []
        }), 502

    except Exception as error:

        return jsonify({
            "ok": False,
            "project": "Nesine Veri Sistemi",
            "version": VERSION,
            "error": str(error),
            "count": 0,
            "matches": []
        }), 500


# ------------------------------------------------------------
# VERSION
# ------------------------------------------------------------

@app.route("/api/version")
def version():

    return jsonify({
        "ok": True,
        "version": VERSION,
        "project": "Nesine Veri Sistemi"
    })


# ------------------------------------------------------------
# START
# ------------------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
