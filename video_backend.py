from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://www.canlitv.diy/tr"
VERSION = "canlitv-mobile-v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
    )
}


class ChannelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.current = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        data = dict(attrs)
        href = data.get("href", "")

        if not href:
            return

        full = urljoin(SOURCE_URL, href)
        parsed = urlparse(full)

        if parsed.netloc.lower() != "www.canlitv.diy":
            return

        if not parsed.path.endswith("-izle"):
            return

        self.current = full
        self.text = []

    def handle_data(self, data):
        if self.current:
            value = data.strip()

            if value:
                self.text.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current:
            title = " ".join(self.text).strip()

            if title:
                self.items.append({
                    "title": title,
                    "url": self.current
                })

            self.current = None
            self.text = []


def get_channels():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=20
    )

    response.raise_for_status()

    parser = ChannelParser()
    parser.feed(response.text)

    result = []
    seen = set()

    for item in parser.items:
        if item["url"] in seen:
            continue

        seen.add(item["url"])
        result.append(item)

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
