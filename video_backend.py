from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v3"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    )
}


class ChannelParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.items = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        data = dict(attrs)
        href = data.get("href", "")

        if not href:
            return

        full_url = urljoin(SOURCE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower() != "www.canlitv.diy":
            return

        path = parsed.path.lower()

        # Kanal sayfaları bu yapıyı kullanıyor:
        # /trt1-izle
        # /show-tv-izle-1
        # /kanal-7-izle
        if "-izle" not in path:
            return

        self.current_href = full_url
        self.current_text = []

    def handle_data(self, data):

        if self.current_href is None:
            return

        text = data.strip()

        if text:
            self.current_text.append(text)

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href is None:
            return

        title = " ".join(self.current_text).strip()

        title = re.sub(r"\s+", " ", title)

        if title:
            self.items.append({
                "title": title,
                "url": self.current_href
            })

        self.current_href = None
        self.current_text = []


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
        title = item["title"]

        if url in seen_urls:
            continue

        # Boş veya anlamsız başlıkları at.
        if len(title) < 2:
            continue

        # Program/haber sayfalarını mümkün olduğunca ele.
        bad_words = [
            "ana haber",
            "haber 19",
            "akşam ajansı",
            "haber bülteni",
            "spor gündemi",
            "günün programı"
        ]

        lower_title = title.lower()

        if any(word in lower_title for word in bad_words):
            continue

        # Aynı kanalın tekrarlarını temizle.
        title_key = lower_title.strip()

        if title_key in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title_key)

        result.append({
            "title": title,
            "url": url
        })

    return result


@app.get("/")
def home():

    return send_from_directory(
        ".",
        "video.html"
    )


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
