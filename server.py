from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

TJK_HOSTS = {"www.tjk.org", "tjk.org"}
NESINE_HOSTS = {"www.nesine.com", "nesine.com"}

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


def fetch_upstream(url):
    last_error = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=(15, 75), allow_redirects=True)
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
        })
    if not allowed_upstream(target):
        return jsonify({"ok": False, "error": "İzin verilmeyen kaynak adresi."}), 400
    try:
        upstream = fetch_upstream(target)
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "TJK/Nesine bağlantısı kurulamadı.",
            "detail": str(exc),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), 502
    content_type = upstream.headers.get("Content-Type", "text/html; charset=utf-8")
    response = Response(upstream.content, status=upstream.status_code, content_type=content_type)
    response.headers["X-Backend-Source"] = "Doruk1"
    return response


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "status": "healthy",
        "tjk_proxy": "active",
    })


@app.get("/api/nesine/races")
def nesine_races():
    url = request.args.get("url", "https://www.nesine.com/at-yarisi").strip()
    if not allowed_upstream(url):
        return jsonify({"ok": False, "error": "Geçersiz Nesine adresi."}), 400
    try:
        r = fetch_upstream(url)
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "Nesine bağlantısı kurulamadı.",
            "detail": str(exc),
        }), 502
    return jsonify({
        "ok": True,
        "source": "nesine",
        "status_code": r.status_code,
        "content_type": r.headers.get("Content-Type"),
        "bytes": len(r.content),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
