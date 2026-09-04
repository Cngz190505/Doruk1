from flask import Flask, send_from_directory, jsonify
import requests
import os
import re
from urllib.parse import urljoin

app = Flask(__name__)

SOURCE_URL = "https://www.atyarisi.com/tjk-at-yarisi-programi"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


# ---------------------------------------------------------
# 1) Kaynak site bağlantısını kontrol et
# ---------------------------------------------------------
@app.get("/api/test-source")
def test_source():
    try:
        r = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True
        )

        html = r.text

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            flags=re.I
        )

        script_urls = [urljoin(r.url, x) for x in scripts]

        return jsonify({
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "final_url": r.url,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "script_urls": script_urls[:50],
            "html_start": html[:1000]
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 502


# ---------------------------------------------------------
# 2) Nesine bülten API'sini küçük özet halinde kontrol et
# ---------------------------------------------------------
@app.get("/api/race-data")
def race_data():

    url = "https://bulten.nesine.com/api/bulten/getprebultenall"

    try:
        r = requests.get(
            url,
            headers={
                **HEADERS,
                "Accept": "application/json,text/plain,*/*"
            },
            timeout=30
        )

        if r.status_code != 200:
            return jsonify({
                "ok": False,
                "status": r.status_code,
                "url": url,
                "message": "API cevap vermedi."
            }), 502

        try:
            data = r.json()
        except Exception:
            return jsonify({
                "ok": False,
                "status": r.status_code,
                "message": "API JSON döndürmedi.",
                "text_start": r.text[:500]
            }), 502

        def summarize(obj, depth=0):
            if depth > 3:
                return {
                    "type": type(obj).__name__
                }

            if isinstance(obj, dict):
                result = {
                    "type": "object",
                    "keys": list(obj.keys())[:50]
                }

                for key in list(obj.keys())[:15]:
                    result[key] = summarize(obj[key], depth + 1)

                return result

            if isinstance(obj, list):
                result = {
                    "type": "array",
                    "length": len(obj)
                }

                if obj:
                    result["first_item"] = summarize(
                        obj[0],
                        depth + 1
                    )

                return result

            return {
                "type": type(obj).__name__,
                "value": str(obj)[:200]
            }

        return jsonify({
            "ok": True,
            "status": r.status_code,
            "source": url,
            "summary": summarize(data)
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


# ---------------------------------------------------------
# 3) JavaScript dosyalarında gerçek API çağrılarını bul
# ---------------------------------------------------------
@app.get("/api/find-js-api")
def find_js_api():

    try:
        r = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        html = r.text

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            flags=re.I
        )

        script_urls = [
            urljoin(r.url, x)
            for x in scripts
        ]

        target_words = [
            "getprebultenall",
            "getprebultenv3",
            "getlivebultenv3",
            "getchangedodds",
            "getprebultenfull",
            "getprebultenIdeta"
        ]

        results = []

        for script_url in script_urls[:30]:

            try:
                js = requests.get(
                    script_url,
                    headers=HEADERS,
                    timeout=20
                ).text

                for word in target_words:

                    start = 0

                    while True:

                        pos = js.lower().find(
                            word.lower(),
                            start
                        )

                        if pos == -1:
                            break

                        context_start = max(
                            0,
                            pos - 1200
                        )

                        context_end = min(
                            len(js),
                            pos + 1800
                        )

                        results.append({
                            "script": script_url,
                            "keyword": word,
                            "context": js[
                                context_start:context_end
                            ]
                        })

                        start = pos + len(word)

                        if len(results) >= 20:
                            break

                    if len(results) >= 20:
                        break

            except Exception:
                continue

            if len(results) >= 20:
                break

        return jsonify({
            "ok": True,
            "script_count": len(script_urls),
            "matches": results
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


# ---------------------------------------------------------
# 4) API çağrılarını tek tek kontrol et
# ---------------------------------------------------------
@app.get("/api/test-bultenler")
def test_bultenler():

    endpoints = {
        "prebultenall":
            "https://bulten.nesine.com/api/bulten/getprebultenall",

        "prebultenv3":
            "https://bulten.nesine.com/api/bulten/getprebultenv3",

        "livebultenv3":
            "https://bulten.nesine.com/api/bulten/getlivebultenv3",

        "changedodds":
            "https://bulten.nesine.com/api/bulten/getchangedodds",

        "prebultenfull":
            "https://bulten.nesine.com/api/bulten/getprebultenfull",

        "prebultenIdeta":
            "https://bulten.nesine.com/api/bulten/getprebultenIdeta"
    }

    results = {}

    for name, url in endpoints.items():

        try:
            r = requests.get(
                url,
                headers={
                    **HEADERS,
                    "Accept": "application/json,text/plain,*/*"
                },
                timeout=20
            )

            results[name] = {
                "status": r.status_code,
                "content_type": r.headers.get(
                    "content-type"
                ),
                "size": len(r.content)
            }

        except Exception as e:

            results[name] = {
                "error": str(e)
            }

    return jsonify(results)


# ---------------------------------------------------------
# Render üzerinde çalıştır
# ---------------------------------------------------------
if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
