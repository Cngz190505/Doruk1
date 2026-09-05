from flask import Flask, jsonify, send_from_directory
import requests
import re
import html
from urllib.parse import urljoin, urlparse

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v7"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def clean_text(value):
    value = html.unescape(value)

    # İç HTML etiketlerini temizle
    value = re.sub(r"<[^>]+>", " ", value)

    # Fazla boşlukları temizle
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def get_channels():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    source = response.text

    # Bütün <a ...>...</a> bloklarını yakala
    pattern = re.compile(
        r"<a\b([^>]*)>(.*?)</a\s*>",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(source)

    anchors = []

    for attrs, body in matches:

        href_match = re.search(
            r'href\s*=\s*["\']([^"\']+)["\']',
            attrs,
            re.IGNORECASE
        )

        if not href_match:
            continue

        href = href_match.group(1).strip()

        if not href:
            continue

        url = urljoin(SOURCE_URL, href)

        parsed = urlparse(url)

        if parsed.netloc.lower() not in (
            "canlitv.diy",
            "www.canlitv.diy"
        ):
            continue

        title = clean_text(body)

        if not title:
            continue

        anchors.append({
            "title": title,
            "url": url
        })

    # TRT 1'i bul
    start = None

    for i, item in enumerate(anchors):
        if item["title"].casefold() == "trt 1":
            start = i
            break

    if start is None:
        return []

    # TRT 1'den itibaren kanal isimlerini al
    result = []
    seen_urls = set()
    seen_titles = set()

    for item in anchors[start:]:

        title = item["title"].strip()
        url = item["url"].strip()

        if not title or not url:
            continue

        # Menü / navigasyonları ele
        blocked_titles = {
            "canlı tv",
            "reytingler",
            "yayın akışları",
            "blog",
            "televizyonlar",
            "kameralar",
            "favoriler",
            "genel",
            "haber",
            "spor",
            "belgesel",
            "çocuk",
            "dini",
            "yerel",
        }

        if title.casefold() in blocked_titles:
            if result:
                break
            continue

        # Aynı URL'yi tekrar alma
        if url in seen_urls:
            continue

        # Aynı kanal adını tekrar alma
        title_key = title.casefold()

        if title_key in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title_key)

        result.append({
            "title": title,
            "url": url
        })

        # Kaynak sayfadaki mevcut kanal listesinin tamamını
        # alabilecek kadar yüksek sınır.
        if len(result) >= 350:
            break

    return result


@app.get("/")
def home():
    return send_from_directory(".", "video.html")


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "canlitv-backend",
        "version": VERSION
    })


@app.get("/api/version")
def version():
    return jsonify({
        "version": VERSION
    })


@app.get("/api/channels")
def channels():
    try:
        items = get_channels()

        return jsonify({
            "ok": True,
            "source": SOURCE_URL,
            "count": len(items),
            "channels": items
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "channels": []
        }), 502


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )
