from flask import Flask, request, Response
import requests

app = Flask(__name__)

@app.get("/")
def home():
    return app.send_static_file("index.html")

@app.get("/api/proxy")
def proxy():
    url = request.args.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return {"error": "Geçerli bir http/https URL gerekli."}, 400

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; RaceDataTest/1.0)"
            },
            timeout=20
        )
        return Response(
            r.content,
            status=r.status_code,
            content_type=r.headers.get("content-type", "text/plain")
        )
    except requests.RequestException as e:
        return {"error": str(e)}, 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
