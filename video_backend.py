from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v5"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    )
}


class ChannelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.collecting = False
        self.finished = False

        self.active_url = None
        self.active_text = []

        self.heading_depth = 0
        self.heading_text = []

        self.items = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        # Kanal listesinden sonraki bölümün başladığını yakala
        if tag in ("h1", "h2", "h3"):
            if self.collecting and self.items:
                self.heading_depth = 1
                self.heading_text = []
            return

        if self.finished:
            return

        if tag != "a":
            return

        data = dict(attrs)
        href = data.get("href", "").strip()

        if not href:
            return

        full_url = urljoin(SOURCE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower() != "www.canlitv.diy":
            return

        # İlk gerçek kanal TRT 1 ile listeyi başlat
        if not self.collecting:
            self.active_url = full_url
            self.active_text = []
            return

        self.active_url = full_url
        self.active_text = []

    def handle_data(self, data):
        text = data.strip()

        if self.heading_depth:
            if text:
                self.heading_text.append(text)
            return

        if self.active_url is not None and text:
            self.active_text.append(text)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in ("h1", "h2", "h3") and self.heading_depth:
            self.heading_depth = 0

            # TRT 1 bulunduysa ve kanal listesi başladıysa
            # sonraki başlıkta listeyi kapat.
            if self.items:
                self.finished = True
                self.active_url = None
                self.active_text = []
            return

        if tag != "a":
            return

        if self.active_url is None:
            return

        title = " ".join(self.active_text)
        title = re.sub(r"\s+", " ", title).strip()

        # TRT 1'i başlangıç noktası olarak kullan
        if not self.collecting:
            if title.lower() == "trt 1":
                self.collecting = True
                self.items.append({
                    "title": "TRT 1",
                    "url": self.active_url
                })
            self.active_url = None
            self.active_text = []
            return

        # Kategori linkleri boş olduğu için buraya girmez
        if title:
            self.items.append({
                "title": title,
                "url": self.active_url
            })

        self.active_url = None
        self.active_text = []


def get_channels():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()

    parser = ChannelParser()
    parser.feed(response.text)

    result = []
    seen_urls = set()
    seen_titles = set()

    for item in parser.items:
        url = item["url"]
        title = re.sub(r"\s+", " ", item["title"]).strip()

        if not title:
            continue

        if url in seen_urls:
            continue

        key = title.lower()

        if key in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(key)

        result.append({
            "title": title,
            "url": url
        })

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
