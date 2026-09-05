from flask import Flask, jsonify
import requests
from datetime import datetime

app = Flask(__name__)

NESINE_URL = "https://bulten.nesine.com/api/bulten/getprebultenfull"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.nesine.com/",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def clean(value):
    if value is None:
        return ""

    return " ".join(
        str(value)
        .replace("\xa0", " ")
        .split()
    ).strip()


def number(value):
    if value is None:
        return None

    try:
        if isinstance(value, (int, float)):
            return float(value)

        value = str(value).strip()

        if not value or value == "-":
            return None

        value = value.replace(",", ".")

        return float(value)

    except Exception:
        return None


def iso_now():
    return datetime.utcnow().isoformat(
        timespec="seconds"
    ) + "Z"


# =========================================================
# NESİNE VERİSİNİ ÇEK
# =========================================================

def get_nesine_data():

    response = requests.get(
        NESINE_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# 1 / X / 2 ORANLARINI BUL
# =========================================================

def get_match_result_odds(match):

    result = {
        "1": None,
        "X": None,
        "2": None
    }

    markets = match.get("MA") or []

    if isinstance(markets, dict):
        markets = list(
            markets.values()
        )

    for market in markets:

        if not isinstance(market, dict):
            continue

        mtid = str(
            market.get("MTID", "")
        ).strip()

        # MTID 1 = Maç Sonucu
        if mtid != "1":
            continue

        outcomes = (
            market.get("OCA")
            or []
        )

        if isinstance(
            outcomes,
            dict
        ):
            outcomes = list(
                outcomes.values()
            )

        # Normal yapı:
        # OCA[0] = 1
        # OCA[1] = X
        # OCA[2] = 2

        if len(outcomes) >= 3:

            result["1"] = number(
                outcomes[0].get("O")
            )

            result["X"] = number(
                outcomes[1].get("O")
            )

            result["2"] = number(
                outcomes[2].get("O")
            )

        break

    return result


# =========================================================
# MAÇLARI TEMİZ JSON'A ÇEVİR
# =========================================================

def parse_matches(data):

    sg = data.get("sg") or {}

    if not isinstance(sg, dict):
        return []

    raw_matches = (
        sg.get("EA")
        or []
    )

    if isinstance(
        raw_matches,
        dict
    ):
        raw_matches = list(
            raw_matches.values()
        )

    # Ligler
    leagues = {}

    raw_leagues = (
        sg.get("LA")
        or []
    )

    if isinstance(
        raw_leagues,
        dict
    ):
        raw_leagues = list(
            raw_leagues.values()
        )

    for league in raw_leagues:

        if not isinstance(
            league,
            dict
        ):
            continue

        league_id = str(
            league.get("LID", "")
        )

        league_name = clean(
            league.get("N")
        )

        if league_id:
            leagues[league_id] = (
                league_name
            )

    matches = []

    for match in raw_matches:

        if not isinstance(
            match,
            dict
        ):
            continue

        # Futbol
        match_type = match.get(
            "TYPE"
        )

        if str(match_type) != "1":
            continue

        home = clean(
            match.get("HN")
        )

        away = clean(
            match.get("AN")
        )

        if not home or not away:
            continue

        league_code = str(
            match.get("LC", "")
        )

        league_name = leagues.get(
            league_code
        )

        odds = get_match_result_odds(
            match
        )

        matches.append({
            "code": match.get("C"),
            "date": clean(
                match.get("D")
            ),
            "time": clean(
                match.get("T")
            ),
            "home": home,
            "away": away,
            "league_code": league_code,
            "league": league_name,
            "match_name": clean(
                match.get("ENO")
            ),
            "type": match_type,
            "odds": odds
        })

    return matches


# =========================================================
# ANA SAYFA
# =========================================================

@app.get("/")
def home():

    return jsonify({
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": "nesine-v1",
        "message": "Nesine veri servisi çalışıyor.",
        "endpoints": [
            "/api/health",
            "/api/nesine"
        ]
    })


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    return jsonify({
        "ok": True,
        "project": "Nesine Veri Sistemi",
        "version": "nesine-v1",
        "time": iso_now()
    })


# =========================================================
# NESİNE API
# =========================================================

@app.get("/api/nesine")
def nesine():

    try:

        data = get_nesine_data()

        matches = parse_matches(
            data
        )

        return jsonify({
            "ok": True,
            "source": NESINE_URL,
            "fetched_at": iso_now(),
            "count": len(matches),
            "matches": matches
        })

    except requests.exceptions.RequestException as error:

        return jsonify({
            "ok": False,
            "error": "Nesine bağlantı hatası",
            "detail": str(error)
        }), 502

    except ValueError as error:

        return jsonify({
            "ok": False,
            "error": "Nesine JSON verisi okunamadı",
            "detail": str(error)
        }), 502

    except Exception as error:

        return jsonify({
            "ok": False,
            "error": "Beklenmeyen hata",
            "detail": str(error)
        }), 500


# =========================================================
# ÇALIŞTIR
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
