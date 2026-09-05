from flask import Flask, jsonify, send_from_directory
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin

app = Flask(__name__, static_folder=".")

SOURCE_URL = "https://videos.com/"
VERSION = "video-mobile-v2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
}

class LinkParser(HTMLParser):
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
        if "youtube.com" in href or "youtu.be" in href or "tiktok.com" in href:
            self.current = href
            self.text = []

    def handle_data(self, data):
        if self.current:
            self.text.append(data.strip())

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current:
            title = " ".join(x for x in self.text if x).strip()
            if title:
                self.items.append({
                    "title": title,
                    "url": urljoin(SOURCE_URL, self.current)
                })
            self.current = None
            self.text = []

def get_videos():
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    parser = LinkParser()
    parser.feed(r.text)

    out = []
    seen = set()
    for item in parser.items:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        out.append(item)

    return out[:50]

@app.get("/")
def home():
    return send_from_directory(".", "video.html")

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "video-backend", "version": VERSION})

@app.get("/api/version")
def version():
    return jsonify({"version": VERSION})

@app.get("/api/videos")
def videos():
    try:
        items = get_videos()
        return jsonify({
            "ok": True,
            "source": SOURCE_URL,
            "count": len(items),
            "videos": items
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "videos": []}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
