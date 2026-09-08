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
        sayfa.wait_for_timeout(8000)
        icerik = sayfa.content()
        tarayici.close()

    kucuk_icerik = icerik.lower()
    ganyan_konumu = kucuk_icerik.find("ganyan")

    if ganyan_konumu != -1:
        baslangic = max(0, ganyan_konumu - 300)
        bitis = ganyan_konumu + 1200
        cevre_metin = icerik[baslangic:bitis]
    else:
        cevre_metin = "GANYAN kelimesi bulunamadi"

    orta_nokta = len(icerik) // 2

    return jsonify({
        "toplam_uzunluk": len(icerik),
        "ganyan_bulundu_mu": ganyan_konumu != -1,
        "ganyan_civari": cevre_metin,
        "ortadan_ornek": icerik[orta_nokta:orta_nokta + 1000],
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
