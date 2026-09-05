from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v6"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def valid_host(url):
    host = urlparse(url).netloc.lower()
    return host in ("canlitv.diy", "www.canlitv.diy")


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.started = False
        self.items = []

        self.in_a = False
        self.a_url = ""
        self.a_text = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag != "a":
            return

        data = dict(attrs)
        href = data.get("href", "").strip()

        if not href:
            return

        url = urljoin(SOURCE_URL, href)

        if not valid_host(url):
            return

        self.in_a = True
        self.a_url = url
        self.a_text = []

    def handle_data(self, data):
        if self.in_a:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.a_text.append(text)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.in_a:
            return

        title = re.sub(
            r"\s+",
            " ",
            " ".join(self.a_text)
        ).strip()

        url = self.a_url

        self.in_a = False
        self.a_url = ""
        self.a_text = []

        if not title:
            return

        # Listeyi TRT 1 ile başlat
        if not self.started:
            if title.casefold() == "trt 1":
                self.started = True
                self.items.append({
                    "title": "TRT 1",
                    "url": url
                })
            return

        # Başladıktan sonra dolu kanal linklerini al
        self.items.append({
            "title": title,
            "url": url
        })


def get_channels():
    r = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30
    )

    r.raise_for_status()

    parser = Parser()
    parser.feed(r.text)

    result = []
    seen_urls = set()
    seen_titles = set()

    for item in parser.items:
        title = item["title"].strip()
        url = item["url"].strip()

        if not title or not url:
            continue

        # Ana navigasyon linklerini çıkar
        path = urlparse(url).path.strip("/").lower()

        blocked = {
            "",
            "tr",
            "tv",
            "genel-tv-kanallari",
            "yerel-tv-kanallari",
            "rating",
            "blog",
            "kameralar",
            "favoriler",
        }

        if path in blocked:
            continue

        title_key = title.casefold()

        if url in seen_urls:
            continue

        if title_key in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title_key)

        result.append({
            "title": title,
            "url": url
        })

        # Kaynak şu an yaklaşık 285 kanal.
        # Sonsuz şekilde sonraki sayfalara taşmaması için sınır.
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


@app.get("/api/debug")
def debug():
    try:
        r = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        html = r.text

        return jsonify({
            "ok": True,
            "status_code": r.status_code,
            "bytes": len(html),
            "has_trt1": "TRT 1" in html,
            "has_showtv": "Show TV" in html,
            "has_kanal7": "Kanal 7" in html
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )
