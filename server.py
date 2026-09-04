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

        script_urls = [
            urljoin(r.url, x)
            for x in scripts
        ]

        patterns = [
            r'https?://[^"\'>\s]+',
            r'["\']([^"\']*(?:api|ajax|fetch|program|race|yaris)[^"\']*)["\']'
        ]

        found = []

        for pattern in patterns:
            matches = re.findall(pattern, html, flags=re.I)

            for item in matches:
                if isinstance(item, tuple):
                    item = item[0]

                if item and item not in found:
                    found.append(item)

        return jsonify({
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "final_url": r.url,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "script_urls": script_urls,
            "possible_api_urls": found[:200],
            "html_start": html[:2000]
        })

    except requests.RequestException as e:
        return jsonify({
            "error": str(e)
        }), 502


def test_api(url):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True
        )

        result = {
            "requested_url": url,
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "final_url": r.url,
            "size": len(r.content)
        }

        try:
            result["json"] = r.json()
        except Exception:
            result["text_start"] = r.text[:5000]

        return jsonify(result)

    except requests.RequestException as e:
        return jsonify({
            "requested_url": url,
            "error": str(e)
        }), 502


@app.get("/api/test-bulten")
def test_bulten():
    return test_api(
        "https://tjkbulten.atyarisi.com/api"
    )


@app.get("/api/test-gw")
def test_gw():
    return test_api(
        "https://tjkgw.atyarisi.com/api"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
