from flask import Flask, jsonify, send_from_directory, request
import requests
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)

SAHADAN_URL = "https://www.sahadan.com/iddaa-programi"

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Referer": "https://www.sahadan.com/",
})


def fetch_sahadan():
    response = session.get(SAHADAN_URL, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def clean(text):
    return " ".join(text.split())


def parse_matches(html):
    """
    İlk sürüm: Sahadan sayfasındaki HTML tablolarını tarar.
    Sayfa yapısı değişirse /api/iddaa-debug ham HTML ile teşhis yapılabilir.
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    # Önce tabloları dene.
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if len(cells) < 3:
                continue

            text = " | ".join(cells)

            # Saat + iki takım adı olan satırları yakalamaya çalış.
            time_value = None
            for cell in cells:
                if len(cell) == 5 and cell[2] == ":" and cell[:2].isdigit() and cell[3:].isdigit():
                    time_value = cell
                    break

            if not time_value:
                continue

            # 1-X-2 oranlarını ayıklamak için ondalık değerleri bul.
            odds = []
            for cell in cells:
                try:
                    value = float(cell.replace(",", "."))
                    if 1.01 <= value <= 100:
                        odds.append(cell)
                except ValueError:
                    pass

            # Takım isimleri için saatten sonraki metinleri aday kabul et.
            after_time = []
            seen_time = False
            for cell in cells:
                if cell == time_value:
                    seen_time = True
                    continue
                if seen_time:
                    after_time.append(cell)

            if len(after_time) >= 2:
                matches.append({
                    "time": time_value,
                    "home": after_time[0],
                    "away": after_time[1],
                    "odds_raw": odds[:20],
                    "raw_cells": cells,
                })

    # Aynı satırların tekrarlarını kaldır.
    unique = []
    seen = set()
    for item in matches:
        key = (
            item["time"],
            item["home"],
            item["away"],
            tuple(item["odds_raw"]),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "iddaa-program-backend",
        "time": datetime.now().isoformat(timespec="seconds"),
    })


@app.route("/api/iddaa-program")
def iddaa_program():
    try:
        html = fetch_sahadan()
        matches = parse_matches(html)

        return jsonify({
            "ok": True,
            "source": SAHADAN_URL,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(matches),
            "matches": matches,
        })

    except requests.RequestException as e:
        return jsonify({
            "ok": False,
            "error": "Sahadan'a erişilemedi",
            "detail": str(e),
        }), 502

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "Program ayrıştırılırken hata oluştu",
            "detail": str(e),
        }), 500


@app.route("/api/iddaa-debug")
def iddaa_debug():
    """Parser çalışmazsa ham sayfanın ilk 10000 karakterini teşhis için döndürür."""
    try:
        html = fetch_sahadan()
        return jsonify({
            "ok": True,
            "source": SAHADAN_URL,
            "html_size": len(html),
            "html_preview": html[:10000],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
