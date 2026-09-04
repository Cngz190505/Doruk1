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
    )
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

        # HTML içinde doğrudan API izlerini bul
        api_matches = find_matches(html)

        return jsonify({
            "status": r.status_code,
            "final_url": r.url,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "script_urls": script_urls,
            "html_api_matches": api_matches
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


def find_matches(text):

    results = []

    patterns = [
        r'https?://[^\'"\s<>]+',
        r'[^\'"\s<>]{0,150}tjkbulten[^\'"\s<>]{0,300}',
        r'[^\'"\s<>]{0,150}tjkgw[^\'"\s<>]{0,300}',
        r'["\']([^"\']*/api/[^"\']*)["\']',
        r'fetch\s*\([^)]{0,400}\)',
        r'axios\.[a-zA-Z]+\s*\([^)]{0,400}\)',
    ]

    for pattern in patterns:
        try:
            matches = re.findall(pattern, text, re.I)

            for item in matches:

                if isinstance(item, tuple):
                    item = item[0]

                if item and item not in results:
                    results.append(item)

        except Exception:
            pass

    return results[:150]


@app.get("/api/find-js-api")
def find_js_api():

    try:

        page = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=20
        )

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            page.text,
            flags=re.I
        )

        script_urls = [
            urljoin(page.url, x)
            for x in scripts
        ]

        results = []

        # Sadece ilk 15 JS dosyasını kontrol ediyoruz.
        # Böylece Render'ın zaman aşımına uğramasını önlüyoruz.
        for url in script_urls[:15]:

            try:

                js = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=8
                )

                matches = find_matches(js.text)

                results.append({
                    "url": url,
                    "status": js.status_code,
                    "size": len(js.content),
                    "matches": matches
                })

            except Exception as e:

                results.append({
                    "url": url,
                    "error": str(e)
                })

        return jsonify({
            "page_status": page.status_code,
            "script_count": len(script_urls),
            "checked": min(15, len(script_urls)),
            "results": results
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


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
