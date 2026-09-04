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


@app.get("/api/find-config")
def find_config():

    try:
        r = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        html = r.text

        # Sayfanın HTML'i içinde aranacak kelimeler
        keywords = [
            "SGBultenUrl",
            "FullBultenUrl",
            "SGGameUrl",
            "BultenUrl",
            "Race",
            "Horse",
            "Yaris",
            "Yarış",
            "Program",
            "TJK"
        ]

        matches = []

        # Önce doğrudan HTML içinde ara
        for keyword in keywords:

            positions = []
            start = 0

            while True:

                pos = html.lower().find(
                    keyword.lower(),
                    start
                )

                if pos == -1:
                    break

                positions.append(pos)
                start = pos + len(keyword)

                if len(positions) >= 3:
                    break

            for pos in positions:

                before = max(0, pos - 700)
                after = min(len(html), pos + 1200)

                matches.append({
                    "keyword": keyword,
                    "source": "HTML",
                    "context": html[before:after]
                })

                if len(matches) >= 30:
                    break

            if len(matches) >= 30:
                break


        # Sayfadaki script dosyalarını bul
        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            re.I
        )

        script_urls = [
            urljoin(r.url, x)
            for x in scripts
        ]


        # Scriptlerde özellikle URL/config tanımlarını ara
        for script_url in script_urls[:30]:

            try:
                js = requests.get(
                    script_url,
                    headers=HEADERS,
                    timeout=20
                ).text
            except Exception:
                continue

            config_patterns = [
                r'SGBultenUrl.{0,300}',
                r'FullBultenUrl.{0,300}',
                r'SGGameUrl.{0,300}',
                r'BultenUrl.{0,300}',
                r'Race.{0,200}',
                r'Yaris.{0,200}',
                r'Program.{0,200}'
            ]

            for pattern in config_patterns:

                found = re.findall(
                    pattern,
                    js,
                    flags=re.I
                )

                for item in found[:3]:

                    matches.append({
                        "keyword": pattern,
                        "source": script_url,
                        "context": item[:1000]
                    })

                    if len(matches) >= 50:
                        break

                if len(matches) >= 50:
                    break

            if len(matches) >= 50:
                break


        return jsonify({
            "ok": True,
            "status": r.status_code,
            "html_size": len(r.content),
            "script_count": len(script_urls),
            "matches": matches[:50]
        })


    except Exception as e:

        return jsonify({
            "ok": False,
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
