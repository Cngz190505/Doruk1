from flask import Flask, jsonify
from playwright.sync_api import sync_playwright
import os

app = Flask(__name__)

@app.route("/")
def anasayfa():
    return jsonify({"durum": "calisiyor"})

@app.route("/veri")
def veri_cek():
    hedef_adres = "https://www.atyarisi.com/tjk-at-yarisi-bulteni"
    with sync_playwright() as p:
        tarayici = p.chromium.launch(
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--single-process",
            ]
        )
        sayfa = tarayici.new_page()
        sayfa.goto(hedef_adres, wait_until="domcontentloaded", timeout=30000)
        sayfa.wait_for_timeout(4000)
        icerik = sayfa.content()
        tarayici.close()
    return jsonify({
        "uzunluk": len(icerik),
        "ilk_1500_karakter": icerik[:1500]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
