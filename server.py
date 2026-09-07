from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "Doruk1",
        "message": "Bizim Taktik backend çalışıyor."
    })

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "status": "healthy"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
