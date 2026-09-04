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
            timeout=30,
            allow_redirects=True
        )

        html = r.text

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            flags=re.I
        )

        script_urls = []
        for src in scripts:
            script_urls.append(urljoin(r.url, src))

        return jsonify({
            "status": r.status_code,
            "final_url": r.url,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "script_urls": script_urls,
            "html_start": html[:2000]
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.get("/api/find-endpoints")
def find_endpoints():

    try:
        page = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        html = page.text

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            flags=re.I
        )

        script_urls = [
            urljoin(page.url, x)
            for x in scripts
        ]

        results = []

        # Önce HTML'in kendisini tara
        results.append({
            "source": "HTML",
            "url": page.url,
            "matches": find_api_patterns(html)
        })

        # Daha sonra JavaScript dosyalarını tara
        for script_url in script_urls:

            try:
                js = requests.get(
                    script_url,
                    headers=HEADERS,
                    timeout=20
                )

                text = js.text

                matches = find_api_patterns(text)

                if matches:
                    results.append({
                        "source": "JAVASCRIPT",
                        "url": script_url,
                        "size": len(js.content),
                        "matches": matches
                    })

            except Exception as e:
                results.append({
                    "source": "JAVASCRIPT_ERROR",
                    "url": script_url,
                    "error": str(e)
                })

        return jsonify({
            "page_status": page.status_code,
            "page_url": page.url,
            "script_count": len(script_urls),
            "results": results
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


def find_api_patterns(text):

    found = []

    patterns = [

        # Tam URL'ler
        r'https?://[^\'"\s<>]+',

        # API yolları
        r'["\']([^"\']*/api/[^"\']*)["\']',

        # tjkbulten / tjkgw
        r'[^\'"\s<>]{0,150}tjkbulten[^\'"\s<>]{0,250}',
        r'[^\'"\s<>]{0,150}tjkgw[^\'"\s<>]{0,250}',

        # fetch
        r'fetch\s*\([^)]{0,500}\)',

        # axios
        r'axios\.[a-zA-Z]+\s*\([^)]{0,500}\)',

        # AJAX
        r'\$\.ajax\s*\([^)]{0,800}\)',
        r'\$\.get\s*\([^)]{0,500}\)',
        r'\$\.post\s*\([^)]{0,500}\)',

        # Program / yarış endpoint isimleri
        r'["\'][^"\']*(?:program|race|races|yaris|kosu|bulten)[^"\']*["\']'
    ]

    for pattern in patterns:

        try:
            matches = re.findall(
                pattern,
                text,
                flags=re.I
            )

            for item in matches:

                if isinstance(item, tuple):
                    item = item[0]

                if item and item not in found:

                    # Çok uzun ve anlamsız şeyleri alma
                    if len(item) <= 1000:
                        found.append(item)

        except Exception:
            pass

    return found[:300]


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
