from flask import Flask, jsonify, send_from_directory
import json
import os

app = Flask(__name__, static_folder=".")

VERSION = "canlitv-static-v1"
CHANNELS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "channels.json"
)


def load_channels():
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("channels", [])


@app.route("/")
def home():
    return send_from_directory(".", "video.html")


@app.route("/api/health")
def health():
    try:
        channels = load_channels()

        return jsonify({
            "ok": True,
            "service": "canlitv-backend",
            "version": VERSION,
            "count": len(channels)
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/api/version")
def version():
    return jsonify({
        "version": VERSION
    })


@app.route("/api/channels")
def channels():
    try:
        items = load_channels()

        return jsonify({
            "ok": True,
            "source": "https://www.canlitv.diy/tr",
            "count": len(items),
            "channels": items
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "channels": []
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
