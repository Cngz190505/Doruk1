import os
from flask import Flask, jsonify, send_file

app = Flask(__name__)

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/api/test")
def test():
    return jsonify({
        "ok": True,
        "message": "server.py çalışıyor",
        "port": os.environ.get("PORT", "10000")
    })

@app.route("/api/live")
def live():
    return jsonify({"error": None, "live": [], "updated": None})

@app.route("/api/results")
def results():
    return jsonify({"error": None, "results": [], "updated": None})

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000"))
    )
