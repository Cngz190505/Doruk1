import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

app = Flask(__name__)

NESINE_URL = "https://www.nesine.com/at-yarisi"
TJK_URL = "https://www.tjk.org/TR/kurumsal/Info/Page/GunlukYarisProgrami"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def number(text):
    text = clean(text).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def parse_tjk_program(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # TJK program tables contain a header with "At İsmi" and "Gny".
    for table in soup.find_all("table"):
        headers = [clean(x.get_text(" ", strip=True)) for x in table.find_all("th")]
        if not headers or not any("At İsmi" in h for h in headers):
            continue

        name_i = next((i for i, h in enumerate(headers) if "At İsmi" in h), None)
        no_i = next((i for i, h in enumerate(headers) if h == "N" or h.startswith("N ")), None)
        jockey_i = next((i for i, h in enumerate(headers) if "Jokey" in h), None)
        gny_i = next((i for i, h in enumerate(headers) if "Gny" in h), None)
        agf_i = next((i for i, h in enumerate(headers) if "AGF" in h), None)
        hp_i = next((i for i, h in enumerate(headers) if h == "HP" or "HP" in h), None)

        # Find the race number from the nearest heading/text before this table.
        race_no = None
        node = table
        for _ in range(12):
            node = node.find_previous()
            if not node:
                break
            text = clean(node.get_text(" ", strip=True))
            m = re.search(r"(\d+)\.\s*Koşu\b", text)
            if m:
                race_no = int(m.group(1))
                break

        for tr in table.find_all("tr"):
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if not cells or name_i is None or name_i >= len(cells):
                continue

            horse = cells[name_i]
            if not horse or horse.lower() in {"at ismi", "at"}:
                continue

            horse_no = None
            if no_i is not None and no_i < len(cells):
                m = re.search(r"\d+", cells[no_i])
                if m:
                    horse_no = int(m.group())

            ganyan = None
            if gny_i is not None and gny_i < len(cells):
                ganyan = number(cells[gny_i])

            agf = None
            if agf_i is not None and agf_i < len(cells):
                agf = number(cells[agf_i])

            jockey = cells[jockey_i] if jockey_i is not None and jockey_i < len(cells) else None
            hp = number(cells[hp_i]) if hp_i is not None and hp_i < len(cells) else None

            # Only accept rows that look like horse rows.
            if horse_no is None and ganyan is None and jockey is None:
                continue

            rows.append({
                "race_no": race_no,
                "horse_no": horse_no,
                "horse": horse,
                "jockey": jockey,
                "hp": hp,
                "ganyan": ganyan,
                "agf": agf,
            })

    # De-duplicate rows.
    result = []
    seen = set()
    for item in rows:
        key = (
            item["race_no"],
            item["horse_no"],
            item["horse"],
            item["ganyan"],
            item["agf"],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "Doruk1",
        "message": "Bizim Taktik backend çalışıyor.",
        "endpoints": {
            "health": "/api/health",
            "live_races": "/api/races/live",
            "nesine_races": "/api/nesine/races"
        }
    })


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "status": "healthy"})


@app.get("/api/races/live")
def live_races():
    city = request.args.get("city", "Bursa").strip()
    date_text = request.args.get("date", "").strip()

    if not date_text:
        # Turkey local date, without adding a timezone dependency.
        date_text = datetime.now().strftime("%d/%m/%Y")

    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", date_text):
        return jsonify({
            "ok": False,
            "error": "date DD/MM/YYYY formatında olmalı."
        }), 400

    url = (
        f"{TJK_URL}?QueryParameter_Tarih={quote(date_text)}"
        f"&SehirAdi={quote(city)}"
    )

    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "source": "tjk_public",
            "error": "Yarış verisine erişilemedi.",
            "detail": str(exc),
        }), 502

    races = parse_tjk_program(response.text)

    return jsonify({
        "ok": True,
        "source": "tjk_public",
        "market_source": "TJK",
        "city": city,
        "date": date_text,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(races),
        "races": races
    })


# Eski frontend bağlantısını bozmamak için aynı veri endpointine yönlendiriyoruz.
@app.get("/api/nesine/races")
def nesine_races():
    return live_races()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
