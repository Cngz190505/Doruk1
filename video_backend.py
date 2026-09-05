from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v4"

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

        self.active_url = None
        self.active_text = []

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

        path = parsed.path.strip("/").lower()

        # Sadece kanal sayfaları.
        # Örnek:
        # /trt1-izle
        # /show-tv-izle-1
        # /kanal-7-izle
        if "-izle" not in path:
            return

        # Yeni geçerli link başladıysa
        # önceki linki kapat.
        if self.active_url is not None:
            self.save_current()

        self.active_url = full_url
        self.active_text = []

    def handle_data(self, data):

        if self.active_url is None:
            return

        text = data.strip()

        if text:
            self.active_text.append(text)

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.active_url is not None:
            self.save_current()

    def save_current(self):

        if self.active_url is None:
            return

        title = " ".join(self.active_text)

        title = re.sub(r"\s+", " ", title).strip()

        if title:

            self.items.append({
                "title": title,
                "url": self.active_url
            })

        self.active_url = None
        self.active_text = []


def clean_title(title):

    title = re.sub(r"\s+", " ", title).strip()

    # Bazı program isimlerini kanal isminden ayır.
    remove_words = [
        " Ana Haber",
        " Haber 19",
        " Akşam Ajansı",
        " Ana Haber Bülteni"
    ]

    for word in remove_words:

        if title.endswith(word):
            title = title[:-len(word)].strip()

    return title


def title_from_url(url):

    path = urlparse(url).path.strip("/")

    path = re.sub(
        r"-izle(?:-\d+)?$",
        "",
        path,
        flags=re.IGNORECASE
    )

    path = path.replace("-", " ")

    path = re.sub(r"\s+", " ", path).strip()

    return path.title()


def get_channels():

    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    parser = ChannelParser()

    parser.feed(response.text)

    # HTML'in sonunda açık kalan bağlantı varsa
    # onu da kaydet.
    if parser.active_url is not None:
        parser.save_current()

    result = []

    seen_urls = set()
    seen_titles = set()

    for item in parser.items:

        url = item["url"]

        title = clean_title(item["title"])

        # Anchor yazısı boşsa URL'den isim oluştur.
        if not title:
            title = title_from_url(url)

        if not title:
            continue

        title_key = title.lower()

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
