from flask import Flask, jsonify, send_from_directory
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
        "Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.atyarisi.com/"
}

BULTEN_URLS = {
    "prebultenall":
        "https://bulten.nesine.com/api/bulten/getprebultenall",

    "prebultenv3":
        "https://bulten.nesine.com/api/bulten/getprebultenv3",

    "prebultenfull":
        "https://bulten.nesine.com/api/bulten/getprebultenfull",

    "prebultenIdeta":
        "https://bulten.nesine.com/api/bulten/getprebultenIdeta"
}


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/test-source")
def test_source():

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

        return jsonify({
            "status": r.status_code,
            "final_url": r.url,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "script_urls": script_urls
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.get("/api/test-bultenler")
def test_bultenler():

    results = {}

    for name, url in BULTEN_URLS.items():

        try:

            r = requests.get(
                url,
                headers=HEADERS,
                timeout=15
            )

            result = {
                "url": url,
                "status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "size": len(r.content)
            }

            # JSON ise doğrudan göster
            try:
                data = r.json()

                result["response_type"] = "JSON"
                result["data"] = data

            except Exception:

                result["response_type"] = "TEXT"
                result["text_start"] = r.text[:3000]

            results[name] = result

        except Exception as e:

            results[name] = {
                "url": url,
                "error": str(e)
            }

    return jsonify({
        "message": "Bülten endpoint test sonuçları",
        "results": results
    })


@app.get("/api/test-one/<name>")
def test_one(name):

    if name not in BULTEN_URLS:
        return jsonify({
            "error": "Geçersiz endpoint",
            "available": list(BULTEN_URLS.keys())
        }), 400

    url = BULTEN_URLS[name]

    try:

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        result = {
            "name": name,
            "url": url,
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "size": len(r.content)
        }

        try:
            result["json"] = r.json()
        except Exception:
            result["text"] = r.text[:10000]

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "name": name,
            "url": url,
            "error": str(e)
        }), 502


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
