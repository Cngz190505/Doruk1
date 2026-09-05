/**
 * Sahadan.com Iddaa Programi Backend
 * ------------------------------------
 * Bu sunucu, sahadan.com'un "genis-iddaa-programi" sayfasini periyodik olarak
 * ceker, HTML'i parse eder ve /api/iddaa-programi endpoint'inden JSON olarak sunar.
 *
 * ONEMLI: Sahadan sayfa yapisini zaman zaman degistirebilir. Eger asagidaki
 * parseMatches() fonksiyonu veri donduremezse, tarayicida sayfayi acip
 * (F12 -> Elements / "Incele") bir mac satirinin gercek class/etiket
 * yapisini kontrol edip selector'lari guncellemen gerekir.
 */

const express = require("express");
const axios = require("axios");
const cheerio = require("cheerio");
const cors = require("cors");

const app = express();
app.use(cors());
app.use(express.static("public")); // frontend'i de bu sunucudan servis ediyoruz

const SOURCE_URL = "https://www.sahadan.com/genis-iddaa-programi";

// Basit bellek-ici cache (Sahadan'i her istekte yormamak icin)
let cache = {
  data: null,
  fetchedAt: 0,
};
const CACHE_TTL_MS = 2 * 60 * 1000; // 2 dakika

async function fetchSahadanHtml() {
  const response = await axios.get(SOURCE_URL, {
    headers: {
      // Bazi siteler bot gibi gorunen isteklere farkli/eksik icerik donduruyor.
      // Gercek bir tarayici User-Agent'i kullanmak faydali olur.
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "tr-TR,tr;q=0.9",
    },
    timeout: 15000,
  });
  return response.data;
}

/**
 * HTML'i parse edip mac listesine cevirir.
 * NOT: Asagidaki selector'lar tahmini/genel bir yapidir. Sahadan'in gercek
 * HTML class isimlerini gormek icin tarayicida "Incele" yapip bu fonksiyonu
 * ona gore duzeltmen gerekebilir. Yardimci notlar asagida yorum satirlarinda.
 */
function parseMatches(html) {
  const $ = cheerio.load(html);
  const matches = [];

  // TIPIK YAPI: her mac genelde bir <tr> veya <div> satirinda durur ve icinde
  // saat, takim isimleri ve oranlar bulunur. Sahadan'da satirlar genelde
  // ".match-row", ".iddaa-row" veya benzeri bir class ile gelir.
  // Once genel bir tablo satiri denemesi yapiyoruz:
  $("tr").each((_, row) => {
    const text = $(row).text().trim();
    if (!text) return;

    // Satirda saat formatini ariyoruz (orn: 19:30) - macin oldugu satirlari
    // digerlerinden (lig basligi, filtre satiri vb.) ayirt etmek icin.
    const timeMatch = text.match(/\b([0-2][0-9]:[0-5][0-9])\b/);
    if (!timeMatch) return;

    const cells = $(row)
      .find("td")
      .map((__, td) => $(td).text().trim())
      .get()
      .filter(Boolean);

    if (cells.length < 3) return;

    matches.push({
      raw: cells, // parse tam oturana kadar ham hücreleri de gönderiyoruz
    });
  });

  return matches;
}

app.get("/api/iddaa-programi", async (req, res) => {
  try {
    const now = Date.now();
    if (cache.data && now - cache.fetchedAt < CACHE_TTL_MS) {
      return res.json({ cached: true, fetchedAt: cache.fetchedAt, matches: cache.data });
    }

    const html = await fetchSahadanHtml();
    const matches = parseMatches(html);

    cache = { data: matches, fetchedAt: now };

    res.json({ cached: false, fetchedAt: now, matches });
  } catch (err) {
    console.error("Sahadan cekme hatasi:", err.message);
    res.status(500).json({ error: "Veri cekilemedi", detail: err.message });
  }
});

app.get("/api/health", (req, res) => res.json({ status: "ok" }));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Sunucu ${PORT} portunda calisiyor`);
});
