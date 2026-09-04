from flask import Flask, jsonify, send_from_directory
import requests
import re

app = Flask(__name__)
BASE_URL = "https://www.atyarisi.com/"
JS_URL = "https://sc.atyarisi.com/10973417184/www/CCAll.min.js?v=10973417184"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/javascript,*/*;q=0.8",
})

def fetch(url, timeout=30):
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def contexts(text, patterns, radius=450, max_each=3):
    out = []
    for pattern in patterns:
        count = 0
        try:
            matches = list(re.finditer(pattern, text, re.I | re.S))
        except re.error:
            matches = []
        for m in matches[:max_each]:
            start = max(0, m.start() - radius)
            end = min(len(text), m.end() + radius)
            snippet = text[start:end].replace("\n", " ")
            out.append({
                "pattern": pattern,
                "context": snippet
            })
            count += 1
    return out

def extract_suffixes(text, var_name):
    # Examples:
    # TjkApiUrl + "/something"
    # TjkApiUrl+"/something"
    # TjkGwApiUrl + '/something'
    patterns = [
        rf'{var_name}\s*\+\s*["\']([^"\']+)["\']',
        rf'["\']([^"\']+)["\']\s*\+\s*{var_name}',
        rf'{var_name}\s*\+\s*`([^`]+)`',
    ]
    found = []
    for p in patterns:
        for m in re.finditer(p, text, re.I):
            val = m.group(1)
            if val not in found:
                found.append(val)
    return found[:100]

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/test-source")
def test_source():
    try:
        html = fetch(BASE_URL)
        return jsonify({
            "ok": True,
            "status": 200,
            "html_size": len(html),
            "source": BASE_URL
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/api/find-tjk-api")
def find_tjk_api():
    try:
        html = fetch(BASE_URL)
        js = fetch(JS_URL)

        combined = html + "\n" + js

        patterns = [
            r'TjkApiUrl',
            r'TjkGwApiUrl',
            r'ProgramManager\.Init',
            r'ProgramManager\.GetAllEvents',
            r'ProgramManager\.GetProgramEventsByNIDOrEventId',
            r'ProgramManager\.GetProgramEventByNIdOrEventId',
            r'FullProgramUrl',
            r'DeltaProgramUrl',
            r'GetProgram',
            r'GetProgramEvents',
            r'\$\.ajax',
            r'\$\.get',
            r'\$\.post',
            r'fetch\(',
            r'Core\.AjaxCall',
            r'AjaxCall',
            r'WebSocket',
            r'Socket',
        ]

        result = {
            "ok": True,
            "html_size": len(html),
            "js_size": len(js),
            "tjk_urls": {
                "TjkApiUrl": "https://tjkbulten.atyarisi.com/api",
                "TjkGwApiUrl": "https://tjkgw.atyarisi.com/api"
            },
            "api_suffixes": {
                "TjkApiUrl": extract_suffixes(combined, "TjkApiUrl"),
                "TjkGwApiUrl": extract_suffixes(combined, "TjkGwApiUrl")
            },
            "matches": contexts(combined, patterns, radius=500, max_each=2)
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502

@app.route("/api/find-program-source")
def find_program_source():
    # Backward-compatible route.
    return find_tjk_api()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
