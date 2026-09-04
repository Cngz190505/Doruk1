from flask import Flask, send_from_directory, jsonify
import requests
import re
import os
from urllib.parse import urljoin

app = Flask(__name__)

SOURCE_URL = "https://www.atyarisi.com/tjk-at-yarisi-programi"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"
}


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/find-call")
def find_call():

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
            re.I
        )

        script_urls = [
            urljoin(page.url, x)
            for x in scripts
        ]

        keywords = [
            "SGBultenUrl",
            "FullBultenUrl",
            "getprebultenall",
            "getprebultenv3",
            "getprebultenfull",
            "getprebultendelta"
        ]

        results = []

        for script_url in script_urls:

            try:
                js_response = requests.get(
                    script_url,
                    headers=HEADERS,
                    timeout=20
                )

                js = js_response.text

            except Exception:
                continue

            for keyword in keywords:

                positions = []
                start = 0

                while True:

                    pos = js.lower().find(
                        keyword.lower(),
                        start
                    )

                    if pos == -1:
                        break

                    positions.append(pos)
                    start = pos + len(keyword)

                    if len(positions) >= 5:
                        break

                for pos in positions:

                    before = max(0, pos - 1800)
                    after = min(len(js), pos + 2500)

                    context = js[before:after]

                    results.append({
                        "keyword": keyword,
                        "script": script_url,
                        "context": context
                    })

                    if len(results) >= 25:
                        break

                if len(results) >= 25:
                    break

            if len(results) >= 25:
                break

        return jsonify({
            "ok": True,
            "script_count": len(script_urls),
            "result_count": len(results),
            "results": results
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
                    )
