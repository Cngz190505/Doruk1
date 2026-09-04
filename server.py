from flask import Flask, jsonify, send_from_directory
import requests
import re
import os

app = Flask(__name__)

SOURCE_URL = "https://www.atyarisi.com/tjk-at-yarisi-programi"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


def context(text, pos, radius=500):
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)

    s = text[start:end]
    s = re.sub(r"\s+", " ", s)

    return s[:1200]


@app.get("/api/find-program-source")
def find_program_source():

    try:
        page = session.get(
            SOURCE_URL,
            timeout=30
        )

        html = page.text

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            re.I
        )

        scripts = [
            x if x.startswith("http") else
            "https://www.atyarisi.com/" + x.lstrip("/")
            for x in scripts
        ]

        results = []

        # HTML + JS dosyalarını incele
        sources = [("HTML", html)]

        for url in scripts:

            try:
                r = session.get(url, timeout=30)

                if r.status_code == 200:
                    sources.append((url, r.text))

            except Exception:
                pass

        keywords = [
            "ProgramManager",
            "ProgramManager.Init",
            "GetProgram",
            "GetAllEvents",
            "GetProgramEvents",
            "GetProgramEvent",
            "FullProgramUrl",
            "DeltaProgramUrl",
            "ProgramUrl",
            "PreProgram",
            "LiveProgram",
            "ProgramApi",
            "RaceApi",
            "RaceUrl",
            "TjkApi",
            "TJK",
            "Kosu",
            "Yaris",
        ]

        for source_name, text in sources:

            lower = text.lower()

            for keyword in keywords:

                start = 0

                while True:

                    pos = lower.find(keyword.lower(), start)

                    if pos == -1:
                        break

                    results.append({
                        "source": source_name,
                        "keyword": keyword,
                        "context": context(text, pos)
                    })

                    start = pos + len(keyword)

                    # Aynı kelimeden çok fazla döndürme
                    if len(results) >= 120:
                        break

                if len(results) >= 120:
                    break

            if len(results) >= 120:
                break

        # Özellikle URL değişkenlerini ayrıca yakala
        variables = []

        patterns = [
            r'(FullProgramUrl|DeltaProgramUrl|ProgramUrl|ProgramApi|RaceApi|RaceUrl|TjkApi)\s*[:=]\s*([^,;}\n]+)',
            r'var\s+([A-Za-z0-9_]*(?:Program|Race|Yaris|Kosu|Tjk|TJK)[A-Za-z0-9_]*)\s*=\s*([^;]+)',
        ]

        for source_name, text in sources:

            for pattern in patterns:

                for match in re.findall(
                    pattern,
                    text,
                    re.I
                ):

                    variables.append({
                        "source": source_name,
                        "name": match[0],
                        "value": match[1][:700]
                    })

        return jsonify({
            "ok": True,
            "page_status": page.status_code,
            "html_size": len(page.content),
            "script_count": len(scripts),

            "important_variables": variables[:100],

            "program_matches": results[:120],

            "message": (
                "ProgramManager ve program API kaynakları "
                "aranıyor. Büyük yarış verisi döndürülmedi."
            )
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
