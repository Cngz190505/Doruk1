import json
import re
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

app = Flask(__name__)

NESINE_URL = "https://www.nesine.com/at-yarisi"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
})


def _walk(value: Any):
    """Yield every nested dict/list item."""
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        m = re.search(r"\d+(?:\.\d+)?", s)
        if m:
            try:
                return float(m.group())
            except ValueError:
                pass
    return None


def _horse_name(obj):
    if not isinstance(obj, dict):
        return None
    for key in (
        "horseName", "HorseName", "atAdi", "AtAdi", "atAd", "AtAd",
        "name", "Name", "horse", "Horse", "runnerName", "RunnerName"
    ):
        value = obj.get(key)
        if isinstance(value, str) and 1 < len(value.strip()) < 100:
            text = value.strip()
            # Avoid treating generic labels as horses.
            if text.lower() not in {
                "ganyan", "plase", "ikili", "üçlü", "dörtlü", "altılı"
            }:
                return text
    return None


def _odds(obj):
    if not isinstance(obj, dict):
        return None

    preferred = (
        "ganyan", "Ganyan", "odds", "Odds", "odd", "Odd",
        "winOdds", "WinOdds", "oran", "Oran", "price", "Price"
    )
    for key in preferred:
        if key in obj:
            n = _number(obj[key])
            if n is not None and n > 0:
                return n

    # Sometimes odds are nested in a market object.
    for key, value in obj.items():
        k = str(key).lower()
        if any(token in k for token in ("ganyan", "odds", "oran", "price")):
            n = _number(value)
            if n is not None and n > 0:
                return n
    return None


def _extract_from_json(value):
    horses = []
    seen = set()

    for obj in _walk(value):
        if not isinstance(obj, dict):
            continue
        name = _horse_name(obj)
        odds = _odds(obj)
        if not name or odds is None:
            continue

        key = (name.casefold(), odds)
        if key in seen:
            continue
        seen.add(key)

        race_no = None
        for k in ("raceNo", "RaceNo", "kosuNo", "KosuNo", "raceNumber", "RaceNumber"):
            if k in obj:
                try:
                    race_no = int(_number(obj[k]))
                except (TypeError, ValueError):
                    race_no = None
                break

        horse_no = None
        for k in ("horseNo", "HorseNo", "atNo", "AtNo", "programNo", "ProgramNo", "number", "Number"):
            if k in obj:
                try:
                    horse_no = int(_number(obj[k]))
                except (TypeError, ValueError):
                    horse_no = None
                break

        horses.append({
            "race_no": race_no,
            "horse_no": horse_no,
            "horse": name,
            "ganyan": odds,
        })

    return horses


def _extract_page(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    # JSON-LD
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        raw = raw.strip()

        if script.get("type") == "application/ld+json":
            try:
                candidates.append(json.loads(raw))
            except Exception:
                pass

        # Common hydration/state containers.
        if any(token in raw for token in (
            "__NEXT_DATA__", "__INITIAL_STATE__", "__PRELOADED_STATE__",
            "initialState", "initialData", "race", "horse", "ganyan"
        )):
            for candidate in (raw,):
                # Try complete JSON first.
                try:
                    candidates.append(json.loads(candidate))
                    continue
                except Exception:
                    pass

                # Try common assignment forms: NAME = {...};
                matches = re.findall(
                    r"(?:__NEXT_DATA__|__INITIAL_STATE__|__PRELOADED_STATE__|"
                    r"initialState|initialData)\s*=\s*(\{.*?\})\s*;?\s*$",
                    candidate,
                    flags=re.S,
                )
                for match in matches:
                    try:
                        candidates.append(json.loads(match))
                    except Exception:
                        pass

    horses = []
    for candidate in candidates:
        horses.extend(_extract_from_json(candidate))

    # De-duplicate.
    unique = []
    seen = set()
    for item in horses:
        key = (item["race_no"], item["horse_no"], item["horse"], item["ganyan"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "Doruk1",
        "message": "Bizim Taktik backend çalışıyor.",
        "endpoints": {
            "health": "/api/health",
            "nesine_races": "/api/nesine/races"
        }
    })


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "status": "healthy"
    })


@app.get("/api/nesine/races")
def nesine_races():
    """
    Gerçek Nesine at yarışı sayfasından erişilebilen veriyi alır.
    Üyelik girişi, CAPTCHA veya erişim kontrolü aşılmaz.
    """
    url = request.args.get("url", NESINE_URL)

    if not url.startswith("https://www.nesine.com/at-yarisi"):
        return jsonify({
            "ok": False,
            "error": "Sadece Nesine at yarışı adresine izin veriliyor."
        }), 400

    try:
        response = SESSION.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "source": "nesine",
            "error": "Nesine verisine erişilemedi.",
            "detail": str(exc),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }), 502

    horses = _extract_page(response.text)

    return jsonify({
        "ok": True,
        "source": "nesine",
        "source_url": response.url,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(horses),
        "races": horses
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
