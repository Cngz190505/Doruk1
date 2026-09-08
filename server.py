from flask import Flask, jsonify
import requests
import os

app = Flask(__name__)

@app.route("/")
def anasayfa():
    return jsonify({"durum": "calisiyor"})

@app.route("/veri")
def veri_cek():
    hedef_adres = "https://www.atyarisi.com/tjk-at-yarisi-bulteni"
    cevap = requests.get(hedef_adres, timeout=15)
    return jsonify({
        "durum_kodu": cevap.status_code,
        "ilk_1000_karakter": cevap.text[:1000]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
