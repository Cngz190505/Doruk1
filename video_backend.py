from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v2"

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

        self.channels = []

        self.li_depth = 0
        self.current_li = False

        self.first_href = None
        self.first_text = []

        self.li_text = []

        self.in_first_anchor = False

    def handle_starttag(self, tag, attrs):

        tag = tag.lower()

        if tag == "li":

            if self.li_depth == 0:
                self.current_li = True
                self.first_href = None
                self.first_text = []
                self.li_text = []
                self.in_first_anchor = False

            self.li_depth += 1
            return

        if (
            tag == "a"
            and self.current_li
            and self.li_depth == 1
            and self.first_href is None
        ):

            data = dict(attrs)

            href = data.get("href", "")

            if href:
                self.first_href = urljoin(SOURCE_URL, href)
                self.in_first_anchor = True

    def handle_data(self, data):

        if not self.current_li:
            return

        value = data.strip()

        if not value:
            return

        self.li_text.append(value)

        if self.in_first_anchor:
            self.first_text.append(value)

    def handle_endtag(self, tag):

        tag = tag.lower()

        if tag == "a":
            if self.in_first_anchor:
                self.in_first_anchor = False

            return

        if tag == "li":

            if self.li_depth == 1:

                self.process_li()

                self.current_li = False
                self.first_href = None
                self.first_text = []
                self.li_text = []
                self.in_first_anchor = False

            self.li_depth = max(0, self.li_depth - 1)

    def process_li(self):

        if not self.first_href:
            return

        parsed = urlparse(self.first_href)

        if parsed.netloc.lower() != "www.canlitv.diy":
            return

        path = parsed.path.strip("/")

        if not path:
            return

        # Ana menü / kategori / genel sayfaları alma.
        blocked = {
            "tr",
            "tv",
            "genel-tv-kanallari",
            "yerel-tv-kanallari",
            "rating",
            "blog",
            "yayın-akışları",
            "yayın-akislari",
        }

        if path.lower() in blocked:
            return

        # Kanal listesindeki satırlar 1. Kanal şeklinde başlıyor.
        full_text = " ".join(self.li_text).strip()

        if not re.match(r"^\d+\.", full_text):
            return

        title = " ".join(self.first_text).strip()

        if not title:
            title = make_title_from_url(path)

        # Program adları gibi gereksiz ekleri temizle.
        title = clean_title(title)

        if not title:
            return

        self.channels.append({
            "title": title,
            "url": self.first_href
        })


def make_title_from_url(path):

    value = path

    value = re.sub(r"-izle(?:-\d+)?$", "", value, flags=re.I)
    value = re.sub(r"-canli(?:-tv)?$", "", value, flags=re.I)
    value = re.sub(r"-tv$", "", value, flags=re.I)

    value = value.replace("-", " ")

    value = re.sub(r"\s+", " ", value).strip()

    return value.title()


def clean_title(title):

    title = re.sub(r"\s+", " ", title).strip()

    # Eğer anchor içinde program adı da varsa,
    # bilinen program ifadelerini kanal isminden ayırmaya çalış.
    bad_suffixes = [
        " Ana Haber",
        " Haber 19",
        " Haber",
        " Ana Haber Bülteni",
        " Akşam Ajansı",
    ]

    for suffix in bad_suffixes:

        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()

    return title


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
    seen = set()

    for item in parser.channels:

        url = item["url"]

        if url in seen:
            continue

        seen.add(url)

        result.append(item)

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
