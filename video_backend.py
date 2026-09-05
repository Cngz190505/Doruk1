from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re
import html

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v8"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def title_from_url(url):
    path = urlparse(url).path.strip("/")

    if not path:
        return ""

    path = re.sub(
        r"-(?:izle|canli)(?:-\d+)?$",
        "",
        path,
        flags=re.IGNORECASE
    )

    path = re.sub(
        r"-izle-\d+$",
        "",
        path,
        flags=re.IGNORECASE
    )

    path = path.replace("-", " ")
    path = re.sub(r"\s+", " ", path).strip()

    replacements = {
        "trt1": "TRT 1",
        "show tv": "Show TV",
        "star tv": "Star TV",
        "kanal7": "Kanal 7",
        "kanal d": "Kanal D",
        "now tv": "Now TV",
        "tv8": "TV8",
        "ntv": "NTV",
        "cnn turk": "CNN Türk",
        "a haber": "A Haber",
        "a spor": "A Spor",
    }

    key = path.casefold()

    if key in replacements:
        return replacements[key]

    return path.title()


class ChannelParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.started = False
        self.finished = False

        self.in_a = False
        self.a_attrs = {}
        self.a_text = []

        self.in_heading = False
        self.heading_text = []

        self.items = []

    def handle_starttag(self, tag, attrs):

        tag = tag.lower()
        attrs = dict(attrs)

        if tag in ("h1", "h2", "h3"):
            if self.started:
                self.in_heading = True
                self.heading_text = []
            return

        if tag != "a":
            return

        href = attrs.get("href", "")

        if not href:
            return

        full_url = urljoin(SOURCE_URL, href)

        host = urlparse(full_url).netloc.lower()

        if host not in ("canlitv.diy", "www.canlitv.diy"):
            return

        self.in_a = True
        self.a_attrs = attrs
        self.a_text = []

    def handle_data(self, data):

        if self.in_heading:
            text = clean(data)

            if text:
                self.heading_text.append(text)

        elif self.in_a:
            text = clean(data)

            if text:
                self.a_text.append(text)

    def handle_endtag(self, tag):

        tag = tag.lower()

        if tag in ("h1", "h2", "h3") and self.in_heading:
            self.in_heading = False

            heading = clean(" ".join(self.heading_text)).casefold()

            self.heading_text = []

            if self.started and heading:
                if heading in (
                    "canlı tv",
                    "canli tv",
                    "aktif izleyiciler",
                    "son eklenen kanallar"
                ):
                    self.finished = True

            return

        if tag != "a" or not self.in_a:
            return

        attrs = self.a_attrs

        href = attrs.get("href", "")
        url = urljoin(SOURCE_URL, href)

        text = clean(" ".join(self.a_text))

        # Kanal ismini farklı HTML alanlarından bul
        title = text

        if not title:
            for key in (
                "alt",
                "title",
                "data-title",
                "data-name",
                "aria-label"
            ):
                if attrs.get(key):
                    title = clean(attrs.get(key))
                    break

        # Hâlâ isim yoksa URL'den üret
        if not title:
            title = title_from_url(url)

        self.in_a = False
        self.a_attrs = {}
        self.a_text = []

        if not title:
            return

        # TRT 1 ile kanal listesini başlat
        if not self.started:

            if title.casefold() in (
                "trt 1",
                "trt1"
            ):
                self.started = True

                self.items.append({
                    "title": "TRT 1",
                    "url": url
                })

            return

        if self.finished:
            return

        self.items.append({
            "title": title,
            "url": url
        })


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

    blocked = {
        "canlı tv",
        "canli tv",
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

    for item in parser.items:

        title = clean(item["title"])
        url = item["url"].strip()

        if not title or not url:
            continue

        if title.casefold() in blocked:
            continue

        if url in seen_urls:
            continue

        title_key = title.casefold()

        if title_key in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title_key)

        result.append({
            "title": title,
            "url": url
        })

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
