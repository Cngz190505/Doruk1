from datetime import datetime, timezone
from urllib.parse import urlparse
import re
from bs4 import BeautifulSoup

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

TJK_HOSTS = {"www.tjk.org", "tjk.org"}
NESINE_HOSTS = {"www.nesine.com", "nesine.com"}
NESINE_RACE_PATHS = (
    "/at-yarisi",
)

# Bizim Taktik'in kullandığı TJK sayfaları.
# Yarış programına ek olarak at geçmişi, galop ve jokey/antrenör
# istatistiklerinin de proxy'den geçmesine izin veriyoruz.
TJK_ALLOWED_PATHS = (
    "/tr/yarissever/info/sehir/gunlukyarisprogrami",
    "/tr/yarissever/info/page/gunlukyarisprogrami",
    "/tr/yarissever/info/atkosubilgileri",
    "/tr/yarissever/query/page/idmanistatistikleri",
    "/tr/yarissever/query/page/jokeyistatistikleri",
    "/tr/yarissever/query/page/antrenoristatistikleri",
)

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tjk.org/",
    "Connection": "keep-alive",
})


def allowed_upstream(url):
    try:
        u = urlparse(url)
    except Exception:
        return False

    if u.scheme != "https":
        return False

    host = (u.hostname or "").lower()
    path = (u.path or "").lower().rstrip("/")

    if host in TJK_HOSTS:
        return path in TJK_ALLOWED_PATHS

    if host in NESINE_HOSTS:
        return path.startswith("/at-yarisi")

    return False


def parse_nesine_odds(html):
    """Parse publicly returned Nesine fixed-odds HTML/embedded JSON.

    Nesine's horse-racing odds page is rendered dynamically.  We therefore
    inspect both ordinary table/text markup and JSON state embedded in script
    tags.  No login, cookie, CAPTCHA or private API is used.
    """
    soup = BeautifulSoup(html, "html.parser")
    horses = {}
    pairs = {"ikili": [], "sirali_ikili": [], "sirali_uclu": []}

    def to_float(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if not isinstance(v, str):
            return None
        m = re.search(r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)(?!\d)", v.strip())
        if not m:
            return None
        try:
            raw = m.group(1)
            if ',' in raw and '.' in raw:
                raw = raw.replace('.', '').replace(',', '.')
            else:
                raw = raw.replace(',', '.')
            return float(raw)
        except Exception:
            return None

    def add_horse(no, name, odds):
        if no is None or not name:
            return
        n = str(no).strip()
        if not re.fullmatch(r"\d{1,2}", n):
            return
        v = to_float(odds)
        if v is None or v < 1:
            return
        horses[n] = {"no": n, "isim": str(name).strip(), "ganyanSabit": v}

    def add_pair(kind, combo, odds):
        if not combo:
            return
        m = re.search(r"(?<!\d)(\d{1,2})\s*[-/]\s*(\d{1,2})(?!\d)", str(combo))
        if not m:
            return
        v = to_float(odds)
        if v is None or v < 1:
            return
        pairs[kind].append({"kombinasyon": f"{m.group(1)}-{m.group(2)}", "oran": v})

    # 1) Normal HTML tables / rows.
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        text = " ".join(cells)
        if not text:
            continue
        m = re.search(r"(?:^|\s)(\d{1,2})\s+(.{2,80}?)\s+(\d{1,3}(?:[.,]\d{1,2})?)\s*$", text)
        if m and not re.search(r"oran|agf|ganyan|ikili|sıralı", m.group(2), re.I):
            add_horse(m.group(1), m.group(2), m.group(3))
        pm = re.search(r"(\d{1,2})\s*[-/]\s*(\d{1,2})\s+(\d{1,3}(?:[.,]\d{1,2})?)", text)
        if pm:
            low = text.lower()
            kind = "sirali_uclu" if "sıralı üçlü" in low or "sirali üçlü" in low else ("sirali_ikili" if "sıralı ikili" in low or "sirali ikili" in low else "ikili")
            add_pair(kind, pm.group(0), pm.group(3))

    # 2) Plain text in the document (useful when the page is rendered into divs).
    all_text = soup.get_text(" ", strip=True)
    for m in re.finditer(r"(?:^|\s)(\d{1,2})\s+([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9 .'-]{2,60}?)\s+(\d{1,3}(?:[.,]\d{1,2})?)(?=\s|$)", all_text):
        add_horse(m.group(1), m.group(2), m.group(3))
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[-/]\s*(\d{1,2})\s+(\d{1,3}(?:[.,]\d{1,2})?)", all_text):
        add_pair("ikili", m.group(0), m.group(3))

    # 3) Embedded JSON state.  Different builds use different property names,
    # so walk dictionaries recursively and recognise common horse/odds fields.
    def walk(obj):
        if isinstance(obj, dict):
            keys = {str(k).lower(): k for k in obj.keys()}
            no = next((obj[keys[k]] for k in keys if k in ("no","number","horseNo","horseNumber","atNo","horseid".lower())), None)
            name = next((obj[keys[k]] for k in keys if k in ("name","horseName".lower(),"atName".lower(),"horse")), None)
            odds = None
            for k in ("odds","odd","rate","ratio","price","fixedOdds","ganyan","ganyanOdds","fixedOdd"):
                if k.lower() in keys:
                    odds = obj[keys[k]]
                    break
            if no is not None and name is not None and odds is not None:
                add_horse(no, name, odds)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    import json
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw or len(raw) > 2_000_000:
            continue
        candidates = [raw]
        # Pull obvious JSON object/array assignments out of JS wrappers.
        for m in re.finditer(r"(?:=|:)\s*([\[{].*[\]}])\s*;?\s*$", raw, re.S):
            candidates.append(m.group(1))
        for candidate in candidates:
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            walk(obj)

    # De-duplicate pair rows.
    for k in pairs:
        seen = set()
        uniq = []
        for x in pairs[k]:
            key = (x["kombinasyon"], x["oran"])
            if key not in seen:
                seen.add(key)
                uniq.append(x)
        pairs[k] = uniq

    return {
        "horses": list(horses.values()),
        "pairs": pairs,
        "parsed": bool(horses or any(pairs.values())),
        "horse_count": len(horses),
        "pair_count": sum(len(v) for v in pairs.values()),
    }


def fetch_upstream(url):
    last_error = None

    for attempt in range(3):
        try:
            r = session.get(
                url,
                timeout=(15, 75),
                allow_redirects=True,
            )

            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                continue

            return r

        except requests.RequestException as exc:
            last_error = exc

    raise last_error or requests.RequestException("Upstream request failed")


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.route("/", methods=["GET", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return ("", 204)

    target = request.args.get("url", "").strip()

    if not target:
        return jsonify({
            "ok": True,
            "service": "Doruk1",
            "status": "healthy",
            "message": "Bizim Taktik backend çalışıyor.",
            "proxy": "Aktif",
            "tjk_data": "Program + At Geçmişi + Galop + Jokey/Antrenör istatistikleri",
        })

    if not allowed_upstream(target):
        return jsonify({
            "ok": False,
            "error": "İzin verilmeyen kaynak adresi."
        }), 400

    try:
        upstream = fetch_upstream(target)
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "TJK/Nesine bağlantısı kurulamadı.",
            "detail": str(exc),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), 502

    content_type = upstream.headers.get(
        "Content-Type",
        "text/html; charset=utf-8"
    )

    response = Response(
        upstream.content,
        status=upstream.status_code,
        content_type=content_type,
    )
    response.headers["X-Backend-Source"] = "Doruk1"
    return response


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "status": "healthy",
        "tjk_proxy": "active",
        "advanced_data_proxy": "active",
    })


@app.get("/api/nesine/races")
def nesine_races():
    url = request.args.get(
        "url",
        "https://www.nesine.com/at-yarisi"
    ).strip()

    if not allowed_upstream(url):
        return jsonify({
            "ok": False,
            "error": "Geçersiz Nesine adresi."
        }), 400

    try:
        r = fetch_upstream(url)
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "Nesine bağlantısı kurulamadı.",
            "detail": str(exc),
        }), 502

    parsed = parse_nesine_odds(r.text)
    return jsonify({
        "ok": True,
        "source": "nesine",
        "status_code": r.status_code,
        "content_type": r.headers.get("Content-Type"),
        "bytes": len(r.content),
        "odds": parsed,
        "note": "Yalnızca kamuya açık sayfada dönen içerik ayrıştırılır; giriş/protected API kullanılmaz."
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
