from flask import Flask, jsonify, send_from_directory
import requests
import re
import os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

SOURCE_URL = "https://www.atyarisi.com/tjk-at-yarisi-programi"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

TIMEOUT = 30

# Yarış programını bulmak için aranacak kelimeler
RACE_KEYWORDS = [
    "program",
    "preprogram",
    "liveprogram",
    "race",
    "races",
    "yaris",
    "yarış",
    "kosu",
    "koşu",
    "horse",
    "at",
    "jockey",
    "hipodrom",
    "hippodrome",
    "tjk",
    "raceid",
    "raceId",
    "programid",
    "programId",
]

# Endpoint olma ihtimali yüksek ifadeler
URL_PATTERNS = [
    r'https?://[^"\']+',
    r'["\']([^"\']*(?:program|race|yaris|kosu|horse|jockey|hipodrom|tjk)[^"\']*)["\']',
    r'url\s*:\s*["\']([^"\']+)["\']',
    r'endpoint\s*[:=]\s*["\']([^"\']+)["\']',
    r'baseUrl\s*[:=]\s*["\']([^"\']+)["\']',
]

session = requests.Session()
session.headers.update(HEADERS)


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/test-source")
def test_source():
    """Atyarisi program sayfasının erişilebilir olduğunu kontrol eder."""
    try:
        r = session.get(
            SOURCE_URL,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        return jsonify({
            "status": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("content-type"),
            "html_size": len(r.content),
            "html_start": r.text[:1000]
        })

    except requests.RequestException as e:
        return jsonify({
            "error": str(e)
        }), 502


def extract_script_urls(html, base_url):
    """HTML içindeki JS dosyalarını çıkarır."""
    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.I
    )

    result = []

    for src in scripts:
        full_url = urljoin(base_url, src)

        if full_url not in result:
            result.append(full_url)

    return result


def compact_context(text, position, radius=280):
    """Bulunan kelimenin etrafından kısa bir bölüm döndürür."""
    start = max(0, position - radius)
    end = min(len(text), position + radius)

    snippet = text[start:end]

    # Telefon ekranında daha rahat okunması için
    snippet = re.sub(r"\s+", " ", snippet)

    return snippet[:650]


def find_keyword_matches(text, source_name):
    """Yarışla ilgili kelimeleri bulur."""
    matches = []

    lower_text = text.lower()

    for keyword in RACE_KEYWORDS:
        start = 0

        while True:
            pos = lower_text.find(keyword.lower(), start)

            if pos == -1:
                break

            matches.append({
                "source": source_name,
                "keyword": keyword,
                "context": compact_context(text, pos)
            })

            start = pos + len(keyword)

            # Aynı dosyada aşırı sonuç üretmesini engelle
            if len(matches) >= 40:
                break

        if len(matches) >= 40:
            break

    return matches


def find_endpoint_candidates(text, source_name):
    """Program/race ile ilişkili olabilecek URL ve endpoint ifadelerini bulur."""
    results = []

    for pattern in URL_PATTERNS:
        try:
            found = re.findall(pattern, text, flags=re.I)
        except Exception:
            continue

        for item in found:
            if isinstance(item, tuple):
                item = item[0]

            if not item:
                continue

            lower = item.lower()

            interesting = any(
                x in lower
                for x in [
                    "program",
                    "race",
                    "yaris",
                    "yarış",
                    "kosu",
                    "koşu",
                    "horse",
                    "jockey",
                    "hipodrom",
                    "tjk",
                ]
            )

            if not interesting:
                continue

            if item not in [x["candidate"] for x in results]:
                results.append({
                    "source": source_name,
                    "candidate": item[:500]
                })

            if len(results) >= 80:
                return results

    return results


@app.get("/api/debug-config")
def debug_config():
    """
    HTML içerisindeki önemli yapılandırma değişkenlerini çıkarır.
    Özellikle Program/Race/TJK değişkenlerini arar.
    """
    try:
        r = session.get(
            SOURCE_URL,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        html = r.text

        patterns = [
            r'var\s+([A-Za-z0-9_]*(?:Program|Race|Yaris|Kosu|TJK|Horse|Jockey)[A-Za-z0-9_]*)\s*=\s*([^;]+)',
            r'([A-Za-z0-9_]*(?:Program|Race|Yaris|Kosu|TJK|Horse|Jockey)[A-Za-z0-9_]*)\s*=\s*([^;]+)',
        ]

        variables = []

        for pattern in patterns:
            for match in re.findall(pattern, html, flags=re.I):
                name = match[0]
                value = match[1].strip()

                item = {
                    "name": name,
                    "value": value[:500]
                }

                if item not in variables:
                    variables.append(item)

        return jsonify({
            "status": r.status_code,
            "variables": variables[:100]
        })

    except requests.RequestException as e:
        return jsonify({
            "error": str(e)
        }), 502


@app.get("/api/find-race-api")
def find_race_api():
    """
    At yarışı programının gerçek API çağrısını bulmaya çalışır.

    Büyük JSON verisi indirmez.
    Sadece HTML/JS içerisindeki program/race bağlantılarını
    ve kısa çevre metinlerini gösterir.
    """

    try:
        # 1 — Ana program sayfasını al
        page = session.get(
            SOURCE_URL,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        html = page.text

        script_urls = extract_script_urls(
            html,
            page.url
        )

        # CCAll gibi ana JS dosyalarını öne al
        script_urls = sorted(
            script_urls,
            key=lambda x: (
                0 if "ccall" in x.lower() else
                1 if "program" in x.lower() else
                2
            )
        )

        keyword_results = []
        endpoint_results = []
        downloaded_scripts = []

        # 2 — HTML'de ara
        keyword_results.extend(
            find_keyword_matches(
                html,
                "HTML"
            )
        )

        endpoint_results.extend(
            find_endpoint_candidates(
                html,
                "HTML"
            )
        )

        # 3 — JS dosyalarını tara
        for script_url in script_urls[:25]:

            try:
                js = session.get(
                    script_url,
                    timeout=TIMEOUT
                )

                if js.status_code != 200:
                    continue

                text = js.text

                downloaded_scripts.append({
                    "url": script_url,
                    "status": js.status_code,
                    "size": len(js.content)
                })

                # Yarış kelimeleri
                keyword_results.extend(
                    find_keyword_matches(
                        text,
                        script_url
                    )
                )

                # Endpoint adayları
                endpoint_results.extend(
                    find_endpoint_candidates(
                        text,
                        script_url
                    )
                )

                # Çok fazla sonuç üretmesini önle
                if len(keyword_results) > 150:
                    keyword_results = keyword_results[:150]

                if len(endpoint_results) > 150:
                    endpoint_results = endpoint_results[:150]

            except requests.RequestException:
                continue

        # Tekrarlayan endpointleri temizle
        unique_endpoints = []
        seen = set()

        for item in endpoint_results:
            candidate = item["candidate"]

            if candidate in seen:
                continue

            seen.add(candidate)
            unique_endpoints.append(item)

        return jsonify({
            "ok": True,
            "page_status": page.status_code,
            "page_url": page.url,
            "html_size": len(page.content),

            "script_count": len(script_urls),

            "downloaded_scripts": downloaded_scripts,

            "possible_race_endpoints":
                unique_endpoints[:100],

            "race_keyword_matches":
                keyword_results[:120],

            "next_step":
                "possible_race_endpoints içindeki program/race "
                "adreslerini incele."
        })

    except requests.RequestException as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
        )
