from flask import Flask, jsonify, send_from_directory
import requests
import re
import json
import time
from datetime import datetime

app = Flask(__name__)

NESINE_URL = "https://bulten.nesine.com/api/bulten/getprebultenfull"
VERSION = "nesine-v5-debug"
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
    "payload": None,
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


def extract_main_odds(obj):

    result = {
        "1": None,
        "X": None,
        "2": None
    }

    if not isinstance(obj, dict):
        return result

    markets = obj.get("MA")

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
                result[key] = normalize_odd(
                    item.get("O")
                )

        break

    return result


def extract_all_markets(obj):

    result = []

    if not isinstance(obj, dict):
        return result

    markets = obj.get("MA")

    if not isinstance(markets, list):
        return result

    for market in markets:

        if not isinstance(market, dict):
            continue

        mtid = clean(market.get("MTID"))

        oca = market.get("OCA")

        if not isinstance(oca, list):
            oca = []

        selections = []

        for index, item in enumerate(oca):

            if not isinstance(item, dict):
                continue

            label = first_value(item, [
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
                "SN"
            ])

            if not label:
                label = str(index + 1)

            selections.append({
                "label": clean(label),
                "odd": normalize_odd(
                    item.get("O")
                )
            })

        market_name = first_value(market, [
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
        ])

        result.append({
            "mtid": mtid,
            "name": clean(market_name),
            "market_keys": list(market.keys()),
            "selection_count": len(selections),
            "selections": selections
        })

    return result


def normalize_match(obj, league_map):

    if not isinstance(obj, dict):
        return None

    home = clean(obj.get("HN"))
    away = clean(obj.get("AN"))

    if not home or not away:
        return None

    code = clean(obj.get("C"))

    if not code:
        return None

    date = clean(obj.get("D"))
    match_time = clean(obj.get("T"))

    league_code = clean(obj.get("LC"))

    league = league_map.get(
        league_code,
        ""
    )

    if not league:

        league = clean(first_value(obj, [
            "LN",
            "league",
            "League",
            "leagueName",
            "LeagueName"
        ]))

    markets = extract_all_markets(obj)

    return {
        "code": code,
        "date": date,
        "time": match_time,
        "home": home,
        "away": away,
        "league": league,
        "league_code": league_code,
        "match_name": f"{home} - {away}",
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

    league_map = make_league_map(
        leagues
    )

    for obj in events:

        match = normalize_match(
            obj,
            league_map
        )

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


def fetch_payload():

    current_time = time.time()

    if (
        cache["payload"] is not None
        and current_time - cache["time"] < CACHE_SECONDS
    ):
        return cache["payload"]

    response = session.get(
        NESINE_URL,
        timeout=30
    )

    response.raise_for_status()

    raw = response.content

    if not raw:
        raise ValueError(
            "Nesine boş veri döndürdü"
        )

    text = raw.decode(
        "utf-8-sig",
        errors="replace"
    ).strip()

    if not text:
        raise ValueError(
            "Nesine boş veri döndürdü"
        )

    payload = json.loads(text)

    cache["time"] = time.time()
    cache["payload"] = payload
    cache["data"] = None

    return payload


def fetch_nesine():

    current_time = time.time()

    if (
        cache["data"] is not None
        and current_time - cache["time"] < CACHE_SECONDS
    ):
        return cache["data"]

    payload = fetch_payload()

    matches = parse_nesine(
        payload
    )

    result = {
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": VERSION,
        "source": NESINE_URL,
        "fetched_at": now_iso(),
        "count": len(matches),
        "matches": matches
    }

    cache["data"] = result

    return result


def find_raw_match(payload, code):

    if not isinstance(payload, dict):
        return None

    sg = payload.get("sg")

    if not isinstance(sg, dict):
        sg = payload.get("SG")

    if not isinstance(sg, dict):
        return None

    events = sg.get("EA")

    if not isinstance(events, list):
        events = sg.get("ea")

    if not isinstance(events, list):
        return None

    for obj in events:

        if not isinstance(obj, dict):
            continue

        if clean(obj.get("C")) == clean(code):
            return obj

    return None


@app.route("/")
def home():

    return send_from_directory(
        ".",
        "index.html"
    )


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

    except Exception as error:

        return jsonify({
            "ok": False,
            "project": "Nesine Veri Sistemi",
            "version": VERSION,
            "error": str(error),
            "count": 0,
            "matches": []
        }), 500


@app.route("/api/nesine/debug/<code>")
def debug_match(code):

    try:

        payload = fetch_payload()

        obj = find_raw_match(
            payload,
            code
        )

        if obj is None:

            return jsonify({
                "ok": False,
                "error": f"{code} kodlu maç bulunamadı."
            }), 404

        markets = obj.get("MA")

        if not isinstance(markets, list):
            markets = []

        debug_markets = []

        for market in markets:

            if not isinstance(market, dict):
                continue

            oca = market.get("OCA")

            if not isinstance(oca, list):
                oca = []

            safe_outcomes = []

            for index, outcome in enumerate(oca):

                if not isinstance(outcome, dict):
                    continue

                values = {}

                for key in outcome.keys():

                    if key in [
                        "O",
                        "N",
                        "NAME",
                        "Name",
                        "name",
                        "ON",
                        "S",
                        "SN",
                        "DESC",
                        "Description",
                        "description",
                        "TITLE",
                        "Title",
                        "title",
                        "V",
                        "V1",
                        "V2"
                    ]:

                        values[key] = outcome[key]

                safe_outcomes.append({
                    "index": index,
                    "keys": list(outcome.keys()),
                    "values": values
                })

            market_name = first_value(
                market,
                [
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
                ]
            )

            debug_markets.append({
                "mtid": clean(
                    market.get("MTID")
                ),
                "market_keys": list(
                    market.keys()
                ),
                "possible_name": market_name,
                "outcomes": safe_outcomes
            })

        return jsonify({

            "ok": True,

            "match": {
                "code": clean(
                    obj.get("C")
                ),
                "date": clean(
                    obj.get("D")
                ),
                "time": clean(
                    obj.get("T")
                ),
                "home": clean(
                    obj.get("HN")
                ),
                "away": clean(
                    obj.get("AN")
                ),
                "league_code": clean(
                    obj.get("LC")
                )
            },

            "market_count": len(
                debug_markets
            ),

            "markets": debug_markets
        })

    except requests.RequestException as error:

        return jsonify({
            "ok": False,
            "error": f"Nesine bağlantı hatası: {error}"
        }), 502

    except Exception as error:

        return jsonify({
            "ok": False,
            "error": str(error)
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
