from flask import Flask, jsonify, send_from_directory
import requests
import re
import json
import time
from datetime import datetime

app = Flask(__name__)

NESINE_URL = "https://bulten.nesine.com/api/bulten/getprebultenfull"
VERSION = "nesine-v5"
CACHE_SECONDS = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nesine.com/",
    "Origin": "https://www.nesine.com",
    "Connection": "keep-alive"
}

session = requests.Session()
session.headers.update(HEADERS)

cache = {
    "time": 0,
    "data": None
}


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_value(obj, keys):
    if not isinstance(obj, dict):
        return None

    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]

    lowered = {str(k).lower(): v for k, v in obj.items()}

    for key in keys:
        value = lowered.get(str(key).lower())
        if value not in (None, ""):
            return value

    return None


def normalize_odd(value):
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)
            if number > 0:
                return round(number, 2)
        except Exception:
            return None

    text = clean(value).replace(",", ".")

    match = re.search(r"\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        number = float(match.group(0))
        if number > 0:
            return round(number, 2)
    except Exception:
        pass

    return None


def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)

    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)


def extract_teams(obj):
    home = first_value(obj, [
        "HN",
        "home",
        "homeTeam",
        "homeTeamName",
        "HomeTeam",
        "HomeTeamName"
    ])

    away = first_value(obj, [
        "AN",
        "away",
        "awayTeam",
        "awayTeamName",
        "AwayTeam",
        "AwayTeamName"
    ])

    if home and away:
        return clean(home), clean(away)

    return "", ""


def market_name(market):
    if not isinstance(market, dict):
        return ""

    return clean(first_value(market, [
        "N",
        "NAME",
        "Name",
        "name",
        "MN",
        "MarketName",
        "marketName",
        "DESC",
        "Description",
        "description",
        "TITLE",
        "Title",
        "title"
    ]))


def outcome_name(outcome):
    if not isinstance(outcome, dict):
        return ""

    return clean(first_value(outcome, [
        "N",
        "NAME",
        "Name",
        "name",
        "ON",
        "OutcomeName",
        "outcomeName",
        "DESC",
        "Description",
        "description",
        "TITLE",
        "Title",
        "title",
        "S",
        "SN",
        "selection",
        "Selection",
        "label",
        "Label"
    ]))


def extract_all_markets(obj):
    markets = []

    if not isinstance(obj, dict):
        return markets

    source = obj.get("MA")

    if not isinstance(source, list):
        return markets

    for market in source:
        if not isinstance(market, dict):
            continue

        mtid = clean(first_value(market, [
            "MTID",
            "mtid",
            "MarketTypeId",
            "marketTypeId"
        ]))

        name = market_name(market)

        outcomes = market.get("OCA")

        if not isinstance(outcomes, list):
            outcomes = []

        selections = []

        for index, outcome in enumerate(outcomes):
            if not isinstance(outcome, dict):
                continue

            odd = normalize_odd(
                first_value(outcome, [
                    "O",
                    "o",
                    "Odd",
                    "odd",
                    "Odds",
                    "odds",
                    "Value",
                    "value"
                ])
            )

            label = outcome_name(outcome)

            if not label:
                if index == 0:
                    label = "1"
                elif index == 1:
                    label = "X"
                elif index == 2:
                    label = "2"
                else:
                    label = str(index + 1)

            selections.append({
                "label": label,
                "odd": odd
            })

        if not selections:
            continue

        markets.append({
            "mtid": mtid,
            "name": name,
            "selections": selections
        })

    return markets


def extract_main_odds(obj):
    result = {
        "1": None,
        "X": None,
        "2": None
    }

    markets = obj.get("MA") if isinstance(obj, dict) else None

    if not isinstance(markets, list):
        return result

    for market in markets:
        if not isinstance(market, dict):
            continue

        mtid = clean(market.get("MTID"))

        if mtid != "1":
            continue

        oca = market.get("OCA")

        if not isinstance(oca, list):
            continue

        for index, key in enumerate(["1", "X", "2"]):
            if index >= len(oca):
                continue

            item = oca[index]

            if isinstance(item, dict):
                result[key] = normalize_odd(item.get("O"))

        break

    return result


def make_league_map(leagues):
    result = {}

    if not isinstance(leagues, list):
        return result

    for league in leagues:
        if not isinstance(league, dict):
            continue

        code = clean(first_value(league, [
            "C",
            "LC",
            "code",
            "Code",
            "leagueCode",
            "LeagueCode"
        ]))

        name = clean(first_value(league, [
            "N",
            "NAME",
            "Name",
            "name",
            "LN",
            "leagueName",
            "LeagueName"
        ]))

        if code:
            result[code] = name

    return result


def normalize_match(obj, league_map):
    if not isinstance(obj, dict):
        return None

    home = clean(obj.get("HN"))
    away = clean(obj.get("AN"))

    if not home or not away:
        home, away = extract_teams(obj)

    if not home or not away:
        return None

    date = clean(obj.get("D"))

    match_time = clean(obj.get("T"))

    league_code = clean(obj.get("LC"))

    league = ""

    if league_code and league_code in league_map:
        league = clean(league_map[league_code])

    if not league:
        league = clean(first_value(obj, [
            "LN",
            "league",
            "League",
            "leagueName",
            "LeagueName",
            "competition",
            "Competition"
        ]))

    code = clean(obj.get("C"))

    if not code:
        code = clean(first_value(obj, [
            "code",
            "Code",
            "matchCode",
            "MatchCode",
            "eventCode",
            "EventCode",
            "id",
            "Id"
        ]))

    markets = extract_all_markets(obj)

    return {
        "home": home,
        "away": away,
        "date": date,
        "time": match_time,
        "league": league,
        "league_code": league_code,
        "match_name": f"{home} - {away}",
        "code": code,
        "odds": extract_main_odds(obj),
        "markets": markets,
        "market_count": len(markets),
        "type": 1
    }


def parse_nesine(payload):
    matches = []
    seen = set()

    if not isinstance(payload, dict):
        return matches

    sg = payload.get("sg")

    if not isinstance(sg, dict):
        sg = payload.get("SG")

    if not isinstance(sg, dict):
        return matches

    events = sg.get("EA")

    if not isinstance(events, list):
        events = sg.get("ea")

    if not isinstance(events, list):
        events = []

    leagues = sg.get("LA")

    if not isinstance(leagues, list):
        leagues = sg.get("la")

    if not isinstance(leagues, list):
        leagues = []

    league_map = make_league_map(leagues)

    for obj in events:
        match = normalize_match(obj, league_map)

        if not match:
            continue

        key = (
            match["code"],
            match["date"],
            match["time"],
            match["home"].casefold(),
            match["away"].casefold()
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
            x.get("home", "")
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
        timeout=30
    )

    response.raise_for_status()

    if not response.content:
        raise ValueError("Nesine boş veri döndürdü")

    text = response.content.decode(
        "utf-8-sig",
        errors="replace"
    ).strip()

    if not text:
        raise ValueError("Nesine boş veri döndürdü")

    payload = json.loads(text)

    matches = parse_nesine(payload)

    result = {
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": VERSION,
        "source": NESINE_URL,
        "fetched_at": now_iso(),
        "count": len(matches),
        "matches": matches
    }

    cache["time"] = time.time()
    cache["data"] = result

    return result


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": VERSION,
        "message": "Nesine veri servisi çalışıyor."
    })


@app.route("/api/nesine")
def nesine():
    try:
        return jsonify(fetch_nesine())

    except requests.RequestException as error:
        return jsonify({
            "ok": False,
            "project": "Nesine Veri Sistemi",
            "version": VERSION,
            "error": f"Nesine bağlantı hatası: {error}",
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


@app.route("/api/version")
def version():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "project": "Nesine Veri Sistemi"
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
