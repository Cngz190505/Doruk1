from flask import Flask, jsonify
import requests
import json
import time
from datetime import datetime

app = Flask(__name__)

NESINE_URL = "https://bulten.nesine.com/api/bulten/getprebultenfull"
VERSION = "nesine-markets-test-v2"
CACHE_SECONDS = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nesine.com/",
    "Origin": "https://www.nesine.com",
    "Connection": "keep-alive",
}

session = requests.Session()
session.headers.update(HEADERS)

cache = {"time": 0, "data": None}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_odd(value):
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def make_league_map(leagues):
    result = {}
    for league in leagues or []:
        if not isinstance(league, dict):
            continue
        code = clean(
            league.get("C")
            or league.get("LC")
            or league.get("ID")
            or league.get("Id")
        )
        name = clean(
            league.get("N")
            or league.get("NAME")
            or league.get("Name")
            or league.get("LN")
        )
        if code and name:
            result[code] = name
    return result


def normalize_selection(item, index):
    if not isinstance(item, dict):
        return {
            "index": index,
            "label": str(index + 1),
            "odd": normalize_odd(item),
            "raw_keys": [],
        }

    label = clean(
        item.get("N")
        or item.get("NAME")
        or item.get("Name")
        or item.get("NM")
        or item.get("NO")
        or item.get("M")
        or item.get("MS")
        or item.get("MST")
        or item.get("MT")
    )

    odd = normalize_odd(
        item.get("O")
        if item.get("O") is not None
        else item.get("ODD")
    )

    # Nesine'de seçim adı bazen başka bir alanın içinde bulunabiliyor.
    # Görünür bir metin bulamazsak sayısal seçim sırasını koruyoruz.
    if not label:
        label = str(index + 1)

    return {
        "index": index,
        "label": label,
        "odd": odd,
        "raw_keys": sorted(list(item.keys())),
    }


def extract_market(market):
    if not isinstance(market, dict):
        return None

    mtid = clean(market.get("MTID"))

    if not mtid:
        return None

    # İsim doğrudan geliyorsa kullan.
    name = clean(
        market.get("N")
        or market.get("NAME")
        or market.get("Name")
        or market.get("MN")
        or market.get("MarketName")
        or market.get("MNAME")
        or market.get("MT")
        or market.get("MST")
    )

    oca = market.get("OCA")
    selections = []

    if isinstance(oca, list):
        for i, item in enumerate(oca):
            selections.append(normalize_selection(item, i))

    # OCA yoksa market içindeki olası seçim dizilerini ara.
    if not selections:
        for key in ("OUTCOMES", "outcomes", "SELECTIONS", "selections", "O"):
            value = market.get(key)
            if isinstance(value, list):
                for i, item in enumerate(value):
                    selections.append(normalize_selection(item, i))
                if selections:
                    break

    # Ad hâlâ yoksa marketin tüm alanlarını dışarı veriyoruz.
    # Böylece sonraki eşleştirmede hangi alanın isim taşıdığı görülebilir.
    possible_name_fields = {}
    for key, value in market.items():
        if key == "OCA":
            continue
        if isinstance(value, (str, int, float, bool)):
            text = clean(value)
            if text:
                possible_name_fields[key] = text

    return {
        "mtid": mtid,
        "name": name,
        "selection_count": len(selections),
        "selections": selections,
        "market_keys": sorted(list(market.keys())),
        "possible_name_fields": possible_name_fields,
        "raw": market,
    }


def extract_markets(obj):
    if not isinstance(obj, dict):
        return []

    markets = obj.get("MA")
    if not isinstance(markets, list):
        markets = obj.get("ma")

    if not isinstance(markets, list):
        return []

    result = []
    seen = set()

    for market in markets:
        parsed = extract_market(market)
        if not parsed:
            continue

        key = parsed["mtid"]
        if key in seen:
            # Aynı MTID tekrar gelirse ikinci kaydı kaybetmemek için
            # sadece ilkini tutuyoruz.
            continue

        seen.add(key)
        result.append(parsed)

    return result


def normalize_match(obj, league_map):
    if not isinstance(obj, dict):
        return None

    code = clean(obj.get("C") or obj.get("CODE") or obj.get("Id"))
    home = clean(obj.get("HN") or obj.get("HOME") or obj.get("HomeTeam"))
    away = clean(obj.get("AN") or obj.get("AWAY") or obj.get("AwayTeam"))

    if not code or not home or not away:
        return None

    date = clean(obj.get("D") or obj.get("DATE") or obj.get("Date"))
    tm = clean(obj.get("T") or obj.get("TIME") or obj.get("Time"))
    league_code = clean(obj.get("LC") or obj.get("LeagueCode"))

    league = (
        league_map.get(league_code)
        or clean(obj.get("LN"))
        or clean(obj.get("LEAGUE"))
        or "Lig bilgisi yok"
    )

    return {
        "code": code,
        "date": date,
        "time": tm,
        "home": home,
        "away": away,
        "match_name": f"{home} - {away}",
        "league": league,
        "league_code": league_code,
        "type": obj.get("TYPE"),
        "markets": extract_markets(obj),
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
            match["away"].casefold(),
        )

        if key in seen:
            continue

        seen.add(key)
        matches.append(match)

    if not matches:
        for obj in walk_dicts(payload):
            match = normalize_match(obj, league_map)
            if not match:
                continue

            key = (
                match["code"],
                match["date"],
                match["time"],
                match["home"].casefold(),
                match["away"].casefold(),
            )

            if key in seen:
                continue

            seen.add(key)
            matches.append(match)

    matches.sort(key=lambda x: (
        x.get("date", ""),
        x.get("time", ""),
        x.get("league", ""),
        x.get("home", ""),
    ))

    return matches


def fetch_data():
    current = time.time()

    if cache["data"] is not None and current - cache["time"] < CACHE_SECONDS:
        return cache["data"]

    response = session.get(NESINE_URL, timeout=30)
    response.raise_for_status()

    raw = response.content
    if not raw:
        raise ValueError("Nesine boş veri döndürdü")

    text = raw.decode("utf-8-sig", errors="replace").strip()

    if not text:
        raise ValueError("Nesine boş veri döndürdü")

    payload = json.loads(text)
    matches = parse_nesine(payload)

    result = {
        "ok": True,
        "project": "Nesine Market Test Sistemi",
        "version": VERSION,
        "source": NESINE_URL,
        "fetched_at": now_iso(),
        "count": len(matches),
        "matches": matches,
    }

    cache["time"] = time.time()
    cache["data"] = result

    return result


def mtid_summary(data):
    """Return a small, phone-friendly summary of every MTID.

    We deliberately do not return the full market JSON here.  The goal is to
    identify which MTIDs exist and which fields they carry without making the
    browser load/copy a multi-megabyte response.
    """
    summary = {}

    for match in data.get("matches", []):
        for market in match.get("markets", []):
            mtid = str(market.get("mtid", "")).strip()
            if not mtid:
                continue

            item = summary.setdefault(mtid, {
                "mtid": mtid,
                "count": 0,
                "names_seen": [],
                "field_values": {},
                "selection_counts": {},
                "selection_examples": [],
                "sample_matches": [],
            })
            item["count"] += 1

            name = clean(market.get("name"))
            if name and name not in item["names_seen"]:
                item["names_seen"].append(name)

            for key, value in (market.get("possible_name_fields") or {}).items():
                text = clean(value)
                if not text:
                    continue
                values = item["field_values"].setdefault(key, [])
                if text not in values and len(values) < 12:
                    values.append(text)

            sc = len(market.get("selections") or [])
            key = str(sc)
            item["selection_counts"][key] = item["selection_counts"].get(key, 0) + 1

            if not item["selection_examples"]:
                item["selection_examples"] = [
                    {
                        "label": clean(s.get("label")),
                        "odd": s.get("odd"),
                        "raw_keys": s.get("raw_keys", []),
                    }
                    for s in (market.get("selections") or [])[:10]
                ]

            sample = {
                "code": match.get("code"),
                "home": match.get("home"),
                "away": match.get("away"),
                "date": match.get("date"),
                "time": match.get("time"),
            }
            if len(item["sample_matches"]) < 3 and sample not in item["sample_matches"]:
                item["sample_matches"].append(sample)

    result = list(summary.values())
    result.sort(key=lambda x: int(x["mtid"]) if x["mtid"].isdigit() else x["mtid"])
    return result


@app.route("/")
def home():
    return jsonify({
        "ok": True,
        "project": "Nesine Market Test Sistemi",
        "version": VERSION,
        "message": "Ana server.py'ye dokunmadan market testi için ayrı servis.",
        "endpoints": {
            "/api/markets": "Tüm maçlar ve marketler",
            "/api/mtid-summary": "MTID→alan/seçim özeti (telefon için küçük çıktı)",
            "/api/mtid/<id>": "Tek MTID'nin kısa özeti",
            "/api/market-debug/<kod>": "Tek maçın tüm market ham verisi",
            "/api/version": "Versiyon",
            "/api/health": "Sağlık kontrolü",
        },
    })


@app.route("/api/health")
def health():
    try:
        data = fetch_data()
        return jsonify({
            "ok": True,
            "version": VERSION,
            "count": data["count"],
            "message": "Market test servisi çalışıyor.",
        })
    except Exception as error:
        return jsonify({
            "ok": False,
            "version": VERSION,
            "error": str(error),
        }), 500


@app.route("/api/version")
def version():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "project": "Nesine Market Test Sistemi",
    })


@app.route("/api/mtid-summary")
def mtid_summary_route():
    try:
        data = fetch_data()
        summary = mtid_summary(data)
        return jsonify({
            "ok": True,
            "version": VERSION,
            "fetched_at": data.get("fetched_at"),
            "match_count": data.get("count", 0),
            "mtid_count": len(summary),
            "note": "Bu endpoint özellikle telefonda kolay okunup kopyalansın diye küçültülmüştür.",
            "mtids": summary,
        })
    except Exception as error:
        return jsonify({"ok": False, "version": VERSION, "error": str(error)}), 500


@app.route("/api/mtid/<mtid>")
def one_mtid(mtid):
    try:
        data = fetch_data()
        summary = mtid_summary(data)
        for item in summary:
            if str(item.get("mtid")) == str(mtid):
                return jsonify({"ok": True, "version": VERSION, "mtid": item})
        return jsonify({"ok": False, "version": VERSION, "error": f"{mtid} MTID bulunamadı."}), 404
    except Exception as error:
        return jsonify({"ok": False, "version": VERSION, "error": str(error)}), 500


@app.route("/api/markets")
def markets():
    try:
        return jsonify(fetch_data())
    except requests.RequestException as error:
        return jsonify({
            "ok": False,
            "version": VERSION,
            "error": f"Nesine bağlantı hatası: {error}",
            "count": 0,
            "matches": [],
        }), 502
    except Exception as error:
        return jsonify({
            "ok": False,
            "version": VERSION,
            "error": str(error),
            "count": 0,
            "matches": [],
        }), 500


@app.route("/api/market-debug/<code>")
def market_debug(code):
    try:
        data = fetch_data()

        for match in data["matches"]:
            if str(match["code"]) == str(code):
                return jsonify({
                    "ok": True,
                    "version": VERSION,
                    "match": match,
                })

        return jsonify({
            "ok": False,
            "version": VERSION,
            "error": f"{code} kodlu maç bulunamadı.",
        }), 404

    except Exception as error:
        return jsonify({
            "ok": False,
            "version": VERSION,
            "error": str(error),
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
