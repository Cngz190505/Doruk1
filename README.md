# Sahadan İddaa Programı - Backend + Mobil Arayüz

## Dosyalar
- `server.js` → Sahadan'ı çekip JSON API sunan backend
- `public/index.html` → Mobilde açılan arayüz (backend'in kendisi bunu servis eder)
- `package.json` → Bağımlılıklar

## 1) Yerel test (opsiyonel)
```
npm install
npm start
```
Sonra tarayıcıda `http://localhost:3000` adresine git.

## 2) GitHub'a yükleme
Bu 3 dosyayı (server.js, package.json, public/index.html klasörüyle birlikte)
mevcut Render reponun köküne ekle ve GitHub'a push'la.

## 3) Render ayarları
- **Build Command:** `npm install`
- **Start Command:** `npm start`
- **Environment:** Node

Render otomatik olarak `PORT` değişkenini verir, kod bunu zaten kullanıyor.

## 4) Deploy sonrası
Render sana bir URL verecek, örn: `https://senin-servisin.onrender.com`
Bu adrese girdiğinde direkt mobil arayüz açılacak ve arka planda
`/api/iddaa-programi` endpoint'inden veri çekecek.

## ÖNEMLİ: Selector'ları tamamlama
Şu an `server.js` içindeki `parseMatches()` fonksiyonu maçları satır satır
buluyor ama hücreleri ham (raw) olarak döndürüyor — yani "saat, takım, oran"
diye ayrıştırılmamış halde. Bunun sebebi: Sahadan'ın gerçek HTML class
isimlerini görmeden kesin selector yazmak riskli (site küçük güncellemelerle
class isimlerini değiştirebiliyor).

Tamamlamak için:
1. Deploy ettikten sonra `/api/iddaa-programi` adresini tarayıcıda aç, dönen
   JSON'daki `raw` dizisine bak (örn: `["19:30", "Galatasaray", "Fenerbahçe",
   "2.10", "3.20", "3.40"]` gibi bir şey göreceksin).
2. Bu diziye göre `server.js` içinde `matches.push({...})` kısmını
   `{ time: cells[0], home: cells[1], away: cells[2], odds1: cells[3], ... }`
   şeklinde güncelle.
3. `public/index.html` içindeki kart gösterimini de buna göre güncelle
   (örnek kod içinde yorum olarak belirtildi).

Bu adımı birlikte de yapabiliriz — deploy ettikten sonra dönen ham JSON'u
bana yapıştırırsan selector'ları senin için netleştiririm.

## Yasal not
Sahadan'ın kullanım şartlarına ve `robots.txt` kurallarına dikkat et,
isteklerini makul aralıklarla (kod içinde 2 dakikalık cache zaten var) yap.
