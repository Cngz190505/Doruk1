from flask import Flask, jsonify, send_from_directory
import requests, re, html as html_lib, json
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    return response

URLS = [
    "https://www.sahadan.com/genis-iddaa-programi",
    "https://www.sahadan.com/iddaa-programi",
]
TIME_RE = re.compile(r'\b(?:[01]\d|2[0-3]):[0-5]\d\b')
ODD_RE = re.compile(r'(?<!\d)(\d{1,3}[.,]\d{1,2})(?!\d)')
CODE_RE = re.compile(r'\b\d{4,8}\b')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=35)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def clean(s):
    s = html_lib.unescape(s or "")
    s = s.replace("\\u0026", "&").replace("\\u003c", "<").replace("\\u003e", ">")
    s = re.sub(r'\\n|\\t|\\r', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def odds(s):
    vals = []
    for x in ODD_RE.findall(s):
        try:
            v = float(x.replace(',', '.'))
        except ValueError:
            continue
        # İddaa oranları için makul aralık; tarih/sayı vb. gürültüyü at
        if 1.01 <= v <= 99.99:
            vals.append(x.replace(',', '.'))
    return vals


def parse_row_text(s):
    """Sahadan'ın metinleştirilmiş maç satırlarını yakalar.
    Örnek: '... 15.47 X 3.84 2 1.30'
    Takım isimleri HTML'de ayrı düğümlerdeyse parse_dom() devreye girer.
    """
    s = clean(s)
    tm = TIME_RE.search(s)
    if not tm:
        return None
    tail = s[tm.end():]
    os_ = odds(tail)
    if len(os_) < 3:
        return None
    # İlk üç oranı MS 1/X/2 olarak al.
    pos = []
    for x in os_[:3]:
        p = tail.find(x)
        if p >= 0:
            pos.append(p)
    if len(pos) != 3:
        return None
    team_part = clean(tail[:min(pos)])
    team_part = re.sub(r'\b[123]\b\s*$', '', team_part).strip()
    team_part = re.sub(r'\b(?:1|2|3)\s*$', '', team_part).strip()
    if len(team_part) < 3:
        return None
    # Ayırıcı olabilirse önce kullan
    for sep in [' - ', '–', ' — ', ' vs ', ' VS ', '  v  ']:
        if sep in team_part:
            a,b = team_part.split(sep,1)
            return make_match(tm.group(), a, b, os_[:3], None)
    return None


def make_match(time, home, away, ms_odds, code=None, league=None):
    home, away = clean(home), clean(away)
    if not home or not away or home.lower() == away.lower():
        return None
    if len(home) < 2 or len(away) < 2:
        return None
    return {
        "time": time,
        "league": league or "",
        "home": home,
        "away": away,
        "code": code or "",
        "odds": {"1": ms_odds[0], "X": ms_odds[1], "2": ms_odds[2]},
    }


def parse_dom(raw):
    soup = BeautifulSoup(raw, "html.parser")
    out=[]
    # En küçük anlamlı kapsayıcıları tarıyoruz. Her maç kartında saat + 3 oran bulunuyor.
    for el in soup.find_all(['article','li','tr','div','section']):
        txt = clean(el.get_text(' ', strip=True))
        if len(txt) > 1200 or len(txt) < 8:
            continue
        tm = TIME_RE.search(txt)
        if not tm:
            continue
        os_ = odds(txt[tm.end():])
        if len(os_) < 3:
            continue
        # Çocuk düğümlerden takım adaylarını çıkar: saat/oran/kod/etiket olmayan kısa metinler.
        parts=[]
        for node in el.find_all(string=True):
            t=clean(str(node))
            if not t or TIME_RE.fullmatch(t) or ODD_RE.fullmatch(t) or CODE_RE.fullmatch(t):
                continue
            if t in {'1','X','2','Maç Sonucu','İlk Yarı Sonucu','Hand. Maç Sonucu'}:
                continue
            if 1 <= len(t) <= 90 and not re.fullmatch(r'[0-9.,Xx/\-]+', t):
                parts.append(t)
        # Aynı metnin tekrarlarını ve UI etiketlerini temizle
        uniq=[]
        for p in parts:
            if p not in uniq and p.lower() not in {'iddaa','futbol','canlı'}:
                uniq.append(p)
        # En olası iki takım: son iki aday. Kod varsa kodu ayrıca yakala.
        if len(uniq) >= 2:
            home, away = uniq[-2], uniq[-1]
            code_match = CODE_RE.search(txt)
            m = make_match(tm.group(), home, away, os_[:3], code_match.group() if code_match else None)
            if m: out.append(m)
    return out


def parse_scripts(raw):
    soup=BeautifulSoup(raw,'html.parser')
    out=[]
    # Script metinlerini de tara; önceki sürümün kritik eksiği buydu.
    blobs=[]
    for sc in soup.find_all('script'):
        t=sc.string or sc.get_text()
        if t and any(k in t.lower() for k in ['iddaa','match','fixture','odds','home','away','next_f']):
            blobs.append(t)
    for blob in blobs:
        b=clean(blob)
        # Saat çevresindeki pencere: Next/RSC verisinde takım adları ve oranlar çoğu zaman yan yana.
        for tm in list(TIME_RE.finditer(b)):
            start=max(0,tm.start()-900); end=min(len(b),tm.end()+900)
            w=b[start:end]
            os_=odds(w)
            if len(os_) < 3: continue
            # JSON key'leri varsa doğrudan yakala
            home=re.search(r'"(?:home|homeTeam|homeTeamName|evSahibi|homeName)"\s*:\s*"([^"]{2,100})"',w,re.I)
            away=re.search(r'"(?:away|awayTeam|awayTeamName|deplasman|awayName)"\s*:\s*"([^"]{2,100})"',w,re.I)
            code=re.search(r'"(?:matchCode|iddaaCode|code|eventCode)"\s*:\s*"?(\d{4,8})',w,re.I)
            league=re.search(r'"(?:leagueName|competitionName|league|competition)"\s*:\s*"([^"]{2,120})"',w,re.I)
            if home and away:
                m=make_match(tm.group(),home.group(1),away.group(1),os_[:3],code.group(1) if code else None,league.group(1) if league else None)
                if m: out.append(m)
    return out



EMBEDDED_MATCH_RE = re.compile(
    r'^(?P<league>.*?)\s+(?:[123])\s+'
    r'(?P<home>[^\n]{2,120}?)\s+v\s+'
    r'(?P<away>[^\n]{2,120}?)\s+-\s+1\s+'
    r'(?P<o1>\d{1,3}[.,]\d{1,2})\s+X\s+'
    r'(?P<ox>\d{1,3}[.,]\d{1,2})\s+2\s+'
    r'(?P<o2>\d{1,3}[.,]\d{1,2})',
    re.I
)


def normalize_league(s):
    s = clean(s)
    # Sahadan'ın metin ağacında lig adı breadcrumb + satır olarak iki kez gelebiliyor.
    words = s.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            s = ' '.join(words[:mid])
    s = re.sub(r'\s+[123]\s*$', '', s).strip()
    return s


def repair_match(m):
    """DOM'dan yanlış sınırlarla gelen kaydı gerçek MS 1/X/2 satırından düzelt."""
    if not isinstance(m, dict):
        return None
    blobs = [clean(m.get('away','')), clean(m.get('home',''))]
    # Öncelik: away alanında görülen gerçek maç satırı; gerekirse iki alanı birleştir.
    for blob in blobs + [' '.join(x for x in blobs if x)]:
        mm = EMBEDDED_MATCH_RE.search(blob)
        if not mm:
            continue
        gd = mm.groupdict()
        return {
            'time': m.get('time',''),
            'league': normalize_league(gd['league']),
            'home': clean(gd['home']),
            'away': clean(gd['away']),
            'code': clean(m.get('code','')),
            'odds': {
                '1': gd['o1'].replace(',', '.'),
                'X': gd['ox'].replace(',', '.'),
                '2': gd['o2'].replace(',', '.')
            }
        }
    return None

def dedupe(items):
    seen=set(); out=[]
    for m in items:
        key=(m.get('time',''),clean(m.get('home','')).lower(),clean(m.get('away','')).lower())
        if key in seen: continue
        seen.add(key); out.append(m)
    return out


VISIBLE_MATCH_RE = re.compile(
    r"(?P<league>[A-Za-zÇĞİÖŞÜçğıöşü0-9.&\'/-]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü0-9.&\'/-]+){1,8}?)\s+"
    r"(?P=league)\s+[123]\s+"
    r"(?P<home>[^\n]{2,100}?)\s+v\s+"
    r"(?P<away>[^\n]{2,100}?)\s+-\s+1\s+"
    r"(?P<o1>\d{1,3}[.,]\d{1,2})\s+X\s+"
    r"(?P<ox>\d{1,3}[.,]\d{1,2})\s+2\s+"
    r"(?P<o2>\d{1,3}[.,]\d{1,2})",
    re.I
)

MARKET_TOKEN_RE = re.compile(r'(?:\d{1,2}[.,]\d{1,2}|-+)', re.I)

MARKET_SCHEMA = [
    ("MS", ["1", "X", "2"]),
    ("IY", ["1", "X", "2"]),
    ("Handikap", ["H1", "HX", "H2"]),
    ("KG", ["Var", "Yok"]),
    ("CifteSans", ["1X", "12", "X2"]),
    ("IY_1_5", ["Alt", "Ust"]),
    ("2_5", ["Alt", "Ust"]),
    ("Ev_1_5", ["Alt", "Ust"]),
    ("Dep_1_5", ["Alt", "Ust"]),
    ("ToplamGol", ["0-1", "2-3", "4-5", "6+"]),
]


def token_value(x):
    if x.startswith('-'):
        return None
    return x.replace(',', '.')


def parse_market_tokens(tokens):
    """Geniş İddaa tablosundaki sabit sütun sırasını marketlere dönüştürür.
    Sahadan bazı kapalı marketleri --/--- olarak verir; bunlar None tutulur.
    Toplam 26 oran pozisyonu vardır: 3+3+3+2+3+2+2+2+2+4.
    """
    pos = 0
    markets = {}
    flat = []
    for market_name, labels in MARKET_SCHEMA:
        group = tokens[pos:pos + len(labels)]
        if len(group) < len(labels):
            group = group + ['--'] * (len(labels) - len(group))
        values = {}
        for label, raw in zip(labels, group):
            value = token_value(raw)
            values[label] = value
            flat.append(value)
        markets[market_name] = values
        pos += len(labels)
    return markets, flat


def parse_visible_text(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    text = clean(soup.get_text(' ', strip=True))
    out=[]
    for mm in VISIBLE_MATCH_RE.finditer(text):
        gd=mm.groupdict()
        before=text[max(0,mm.start()-100):mm.start()]
        times=TIME_RE.findall(before)
        if not times:
            continue
        # İlk 3 oran regex ile ayrı yakalandı. Sonraki tüm market tokenları
        # 'Tümü' etiketine kadar olan maç bloğundan alınır.
        after_start = mm.end()
        end_mark = text.find('Tümü', after_start)
        if end_mark < 0:
            end_mark = min(len(text), after_start + 500)
        segment = text[after_start:end_mark]
        tokens = MARKET_TOKEN_RE.findall(segment)
        # MS zaten regex grubunda; kalan 23 sütunu segmentten al.
        ms = [gd['o1'], gd['ox'], gd['o2']]
        all_tokens = ms + tokens
        markets, flat = parse_market_tokens(all_tokens[:26])
        out.append({
            'time': times[-1],
            'league': normalize_league(gd['league']),
            'home': clean(gd['home']),
            'away': clean(gd['away']),
            'code': '',
            'odds': markets['MS'],
            'markets': markets,
            'market_odds_flat': flat,
            'market_count': sum(v is not None for v in flat),
        })
    return dedupe(out)

def get_program():
    errors=[]
    for url in URLS:
        try:
            raw=fetch(url)
            # Önce görünen sayfa metninden doğrudan gerçek maç satırlarını çıkar.
            items=parse_visible_text(raw)
            if not items:
                # Fallback: script/DOM verisini eski yöntemle onar.
                raw_items=parse_scripts(raw) + parse_dom(raw)
                repaired=[]
                for item in raw_items:
                    fixed=repair_match(item)
                    if fixed:
                        repaired.append(fixed)
                items=dedupe(repaired)
            if items:
                return items, url, len(raw), None
            errors.append(f'{url}: veri yapısı bulunamadı')
        except Exception as e:
            errors.append(f'{url}: {type(e).__name__}: {e}')
    return [], URLS[0], 0, '; '.join(errors)


@app.get('/')
def index():
    return send_from_directory('.', 'index.html')

@app.get('/api/health')
def health():
    return jsonify({"ok":True,"service":"iddaa-program-backend","time":datetime.now().isoformat(timespec='seconds')})

@app.get('/api/iddaa-program')
def iddaa_program():
    matches, source, size, err = get_program()
    return jsonify({
        "ok": True,
        "parser_version": "v3-market-placeholder-fix",
        "source": source,
        "html_size": size,
        "count": len(matches),
        "matches": matches,
        "error": err,
        "fetched_at": datetime.now().isoformat(timespec='seconds')
    })

@app.get('/api/iddaa-debug')
def debug():
    result=[]
    for url in URLS:
        try:
            raw=fetch(url)
            soup=BeautifulSoup(raw,'html.parser')
            text=clean(soup.get_text(' ',strip=True))
            result.append({
                'url':url,'html_size':len(raw),
                'title':clean(soup.title.get_text()) if soup.title else '',
                'times':TIME_RE.findall(text)[:30],
                'odds_sample':ODD_RE.findall(text)[:40],
                'script_count':len(soup.find_all('script')),
                'text_sample':text[:3000]
            })
        except Exception as e:
            result.append({'url':url,'error':f'{type(e).__name__}: {e}'})
    return jsonify({'ok':True,'sources':result})

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=10000)
