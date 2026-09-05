from flask import Flask, jsonify, send_from_directory, request
import requests, re, html as html_lib, json
from bs4 import BeautifulSoup
from datetime import datetime
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

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


_FETCH_CACHE = {}
_FETCH_LOCK = threading.Lock()
_FETCH_TTL = 600

def fetch(url):
    now = time.time()
    with _FETCH_LOCK:
        item = _FETCH_CACHE.get(url)
        if item and now - item[0] < _FETCH_TTL:
            return item[1]
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    text = r.text
    with _FETCH_LOCK:
        _FETCH_CACHE[url] = (time.time(), text)
    return text


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
    ("IlkGol", ["1", "Olmaz", "2"]),
    ("2_5", ["Alt", "Ust"]),
    ("Ev_1_5", ["Alt", "Ust"]),
    ("Dep_1_5", ["Alt", "Ust"]),
    ("MS_ve_2_5", ["1-Alt", "X-Alt", "2-Alt", "1-Ust", "X-Ust", "2-Ust"]),
    ("ToplamGol", ["0-1", "2-3", "4-5", "6+"]),
]


def token_value(x):
    if x.startswith('-'):
        return None
    return x.replace(',', '.')


def parse_market_tokens(tokens):
    """Geniş İddaa tablosundaki sabit sütun sırasını marketlere dönüştürür.
    Sahadan bazı kapalı marketleri --/--- olarak verir; bunlar None tutulur.
    Toplam 35 oran pozisyonu vardır; Sahadan geniş programındaki tüm sabit market sütunları okunur.
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


def norm_slug(s):
    import unicodedata
    s=clean(s).lower()
    s=unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode('ascii')
    s=re.sub(r'[^a-z0-9]+','-',s).strip('-')
    return s


def extract_detail_urls(raw):
    """Programdaki maç detay bağlantılarını çıkar.

    Kritik düzeltme: Sahadan güncel programda maç linkleri artık her zaman
    /iddaa/ içermiyor. Örn. /mac/home-vs-away/<id>. Eski sürüm bu nedenle
    193 maçın tamamında detail_url üretemiyordu. Hem /iddaa/ hem de doğrudan
    /mac/.../<id> biçimlerini kabul ediyoruz; istatistik/karşılaştırma alt
    sayfalarını ayrıca kullanmıyoruz.
    """
    from urllib.parse import urljoin, urlparse, unquote
    soup=BeautifulSoup(raw,'html.parser')
    urls=[]
    seen=set()
    for a in soup.find_all('a', href=True):
        href=a.get('href','').strip()
        if '/mac/' not in href.lower():
            continue
        if href.startswith(('javascript:','#','mailto:')):
            continue
        href=urljoin('https://www.sahadan.com/', href)
        path=unquote(urlparse(href).path)
        # Sadece ana maç detay URL'si: /mac/<home-vs-away>/...
        if '/mac/' not in path.lower():
            continue
        after=path.lower().split('/mac/',1)[-1]
        if not after or '-vs-' not in after:
            continue
        first=after.split('/')[0]
        if not first or '-vs-' not in first:
            continue
        # İstatistik/karşılaştırma alt sayfalarını alma. /iddaa/<id> kabul.
        segments=after.split('/')
        if any(x.lower() in {'karsilastirma','istatistikler','form','iddaa'} for x in segments[1:-1]):
            # /iddaa/<id> ana detay URL'sidir; diğerleri alt sayfadır.
            if len(segments)>=2 and segments[1].lower()=='iddaa':
                pass
            elif len(segments)>=2 and re.fullmatch(r'[a-z0-9]+', segments[1], re.I):
                pass
            else:
                continue
        if href not in seen:
            seen.add(href); urls.append(href)
    return urls


def attach_detail_urls(items, raw):
    urls=extract_detail_urls(raw)
    if not urls:
        return items
    # URL slug typically contains both team names: /mac/home-vs-away/iddaa/...
    indexed=[]
    for u in urls:
        from urllib.parse import unquote
        path=unquote(u).lower().split('/mac/',1)[-1]
        indexed.append((norm_slug(path),u))
    used=set()
    for m in items:
        hs=norm_slug(m.get('home',''))
        ays=norm_slug(m.get('away',''))
        best=None; bestscore=0
        for slug,u in indexed:
            if u in used: continue
            score=0
            if hs and hs in slug: score+=2
            if ays and ays in slug: score+=2
            # Partial team token matching for abbreviated names.
            if score<4:
                hparts=[x for x in hs.split('-') if len(x)>=4][:3]
                aparts=[x for x in ays.split('-') if len(x)>=4][:3]
                if hparts and any(x in slug for x in hparts): score+=1
                if aparts and any(x in slug for x in aparts): score+=1
            if score>bestscore:
                bestscore=score; best=u
        if best and bestscore>=3:
            m['detail_url']=best
            used.add(best)
        else:
            m['detail_url']=None
    return items


def parse_detail_markets(raw):
    """Bireysel Sahadan maç sayfasındaki İddaa sekmesinde görünen tüm marketleri yakalar.
    Her başlık '... MBS n' şeklindedir; altındaki li satırları 'seçenek + oran' olarak saklarız.
    Böylece yeni/ek marketler için sabit şema gerekmez.
    """
    soup=BeautifulSoup(raw,'html.parser')
    markets=[]
    # Başlıklar farklı HTML seviyelerinde olabilir; MBS metni en güçlü işarettir.
    heads=[]
    for h in soup.find_all(re.compile(r'^h[1-6]$')):
        t=clean(h.get_text(' ',strip=True))
        if re.search(r'\bMBS\s*\d+',t,re.I):
            heads.append(h)
    # Fallback: metin içinde MBS başlıklarını bulmak için div/p etiketlerini de tara.
    if not heads:
        for el in soup.find_all(['div','p','span']):
            t=clean(el.get_text(' ',strip=True))
            if re.search(r'\bMBS\s*\d+',t,re.I) and len(t)<180:
                heads.append(el)
    seen_titles=set()
    for h in heads:
        title=clean(h.get_text(' ',strip=True))
        title=re.sub(r'\s+\d{3,6}\s+MBS\s*\d+\s*$','',title,flags=re.I).strip()
        if not title or title in seen_titles: continue
        seen_titles.add(title)
        options=[]
        # Önce yakın sonraki kardeş/kapları tara.
        parent=h.parent
        candidates=[]
        if parent:
            candidates.extend(parent.find_all('li'))
            # Bazı tasarımlarda li parent dışında, aynı section içinde.
            sec=parent.find_parent(['section','article','div'])
            if sec:
                candidates.extend(sec.find_all('li'))
        # Sadece başlıktan sonra gelen ilk seçenekleri kullan; sonraki markete taşmasını engelle.
        seen_opt=set()
        for li in candidates:
            txt=clean(li.get_text(' ',strip=True))
            if not txt or txt in seen_opt: continue
            mm=re.search(r'^(.*?)\s+(\d{1,3}[.,]\d{1,2}|-)\s*$',txt)
            if not mm: continue
            label=clean(mm.group(1)); odd=mm.group(2).replace(',','.')
            if label and len(label)<100:
                options.append({'label':label,'odds':None if odd=='-' else odd})
                seen_opt.add(txt)
        if options:
            markets.append({'name':title,'options':options})
    return markets

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
                items = attach_detail_urls(items, raw)
                return items, url, len(raw), None
            errors.append(f'{url}: veri yapısı bulunamadı')
        except Exception as e:
            errors.append(f'{url}: {type(e).__name__}: {e}')
    return [], URLS[0], 0, '; '.join(errors)


_BATCH = {
    'state': 'idle',
    'started_at': None,
    'finished_at': None,
    'total': 0,
    'done': 0,
    'results': [],
    'errors': [],
}
_BATCH_LOCK = threading.Lock()

def _compact_analysis(p):
    pred=p.get('prediction') or {}
    h=p.get('home') or {}; a=p.get('away') or {}
    hd=h.get('details') or {}; ad=a.get('details') or {}
    comp=p.get('historical_market_comparison') or []
    green=sorted([x for x in comp if x.get('signal')=='green'], key=lambda x:x.get('edge_pct') if x.get('edge_pct') is not None else -999, reverse=True)[:8]
    return {
        'ok': True, 'match': p.get('match'), 'prediction': pred,
        'home': {'last5': h.get('last5',[]), 'details': hd},
        'away': {'last5': a.get('last5',[]), 'details': ad},
        'h2h_last5': p.get('h2h_last5',[])[:5],
        'current_markets': p.get('current_markets',[]),
        'historical_market_comparison': comp,
        'green_signals': green,
        'history_matches_used': p.get('history_matches_used',0),
        'fetched_at': p.get('fetched_at'),
    }

def _run_batch(matches):
    with _BATCH_LOCK:
        _BATCH.update({'state':'running','started_at':datetime.now().isoformat(timespec='seconds'),'finished_at':None,'total':len(matches),'done':0,'results':[],'errors':[]})
    out=[]
    def one(i,m):
        url=m.get('detail_url')
        if not url:
            raise ValueError('detail_url yok')
        return i,_compact_analysis(technical_analysis_v9(url))
    # Two concurrent workers: the analysis of one match fans out to many Sahadan pages; this avoids rate-limit/connection overload on Render free instances.
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures={ex.submit(one,i,m):(i,m) for i,m in enumerate(matches)}
        for fut in as_completed(futures):
            i,m=futures[fut]
            try:
                idx,r=fut.result(); out.append((idx,r))
            except Exception as e:
                with _BATCH_LOCK:
                    _BATCH['errors'].append({'index':i,'error':f'{type(e).__name__}: {e}','home':m.get('home'),'away':m.get('away'),'detail_url':m.get('detail_url')})
            finally:
                with _BATCH_LOCK: _BATCH['done'] += 1
    out.sort(key=lambda z:z[0])
    results=[r for _,r in out]
    with _BATCH_LOCK:
        _BATCH['results']=results
        _BATCH['state']='done'
        _BATCH['finished_at']=datetime.now().isoformat(timespec='seconds')

@app.get('/api/analyze-all')
def analyze_all():
    global _BATCH
    with _BATCH_LOCK:
        state=_BATCH['state']
        if state=='running':
            return jsonify({'ok':True,'state':'running','total':_BATCH['total'],'done':_BATCH['done']})
    matches,source,size,err=get_program()
    if not matches:
        return jsonify({'ok':False,'error':err or 'Program bulunamadı'}),502
    detail_count=sum(1 for m in matches if m.get('detail_url'))
    if detail_count == 0:
        return jsonify({'ok':False,'state':'not_started','total':len(matches),'with_detail_urls':0,'error':'Program maçları bulundu ancak maç detay bağlantıları bulunamadı. Sahadan link yapısı değişmiş olabilir.'}),502
    with _BATCH_LOCK:
        _BATCH['state']='starting'; _BATCH['total']=len(matches); _BATCH['done']=0
    threading.Thread(target=_run_batch,args=(matches,),daemon=True).start()
    return jsonify({'ok':True,'state':'started','total':len(matches),'with_detail_urls':detail_count,'source':source})

@app.get('/api/analyze-all/status')
def analyze_all_status():
    with _BATCH_LOCK:
        b=dict(_BATCH)
    # UI needs results even while running; return a snapshot.
    return jsonify({'ok':True,**b})

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
        "parser_version": "v9-history-odds-analysis",
        "source": source,
        "html_size": size,
        "count": len(matches),
        "matches": matches,
        "error": err,
        "fetched_at": datetime.now().isoformat(timespec='seconds')
    })

@app.get('/api/match-markets')
def match_markets():
    url=request.args.get('url','').strip()
    from urllib.parse import urlparse
    p=urlparse(url)
    if p.scheme not in ('http','https') or p.netloc.lower() not in ('www.sahadan.com','sahadan.com') or '/mac/' not in p.path.lower() or '/iddaa/' not in p.path.lower():
        return jsonify({'ok':False,'error':'Geçersiz Sahadan maç adresi'}),400
    try:
        raw=fetch(url)
        markets=parse_detail_markets(raw)
        return jsonify({'ok':True,'url':url,'market_count':len(markets),'markets':markets,'fetched_at':datetime.now().isoformat(timespec='seconds')})
    except Exception as e:
        return jsonify({'ok':False,'error':f'{type(e).__name__}: {e}'}),502

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

# --- Teknik analiz v8 ---
from urllib.parse import urlparse


def find_stat_url(detail_url):
    p = urlparse(detail_url)
    parts = p.path.strip('/').split('/')
    if 'mac' in parts:
        i = parts.index('mac')
        # İddaa URL: /mac/<home-vs-away>/iddaa/<match-id>
        # İstatistik URL: /mac/<home-vs-away>/<match-id>/istatistikler/sezon
        if len(parts) >= i + 4 and parts[i+2].lower() == 'iddaa':
            return "https://www.sahadan.com/" + "/".join(parts[:i+2] + [parts[i+3], 'istatistikler', 'sezon'])
        if len(parts) >= i + 3:
            return "https://www.sahadan.com/" + "/".join(parts[:i+3]) + "/istatistikler/sezon"
    return None


def extract_team_links(raw, home, away):
    soup = BeautifulSoup(raw, 'html.parser')
    out = {'home': None, 'away': None}
    hs, ays = norm_slug(home), norm_slug(away)
    for a in soup.find_all('a', href=True):
        href = a.get('href','')
        if '/takim/' not in href.lower():
            continue
        txt = clean(a.get_text(' ', strip=True))
        ns = norm_slug(txt)
        if href.startswith('/'):
            href='https://www.sahadan.com'+href
        if out['home'] is None and (ns == hs or (ns and hs and (ns in hs or hs in ns))):
            out['home']=href
        if out['away'] is None and (ns == ays or (ns and ays and (ns in ays or ays in ns))):
            out['away']=href
    return out


def parse_stat_blocks(raw, team_side):
    """Sahadan /istatistikler/sezon metninden teknik istatistik bloklarını çıkarır."""
    soup=BeautifulSoup(raw,'html.parser')
    text=clean(soup.get_text(' ', strip=True))
    result={'win':None,'draw':None,'loss':None,'ht_win':None,'ht_draw':None,'ht_loss':None,
            'btts_yes':None,'btts_no':None,'goal_minutes':{},'win_margin':{},'loss_margin':{}}
    side_label='İç Saha' if team_side=='home' else 'Deplasman'
    # İlgili takım başlıklarının olduğu bölümü bulmak yerine genel metinden takım + blokları yakala.
    # Yüzdeleri doğrudan başlıklardan sonra okuyabilmek için satırlaştırılmış metin de kullanılır.
    lines=[clean(x) for x in soup.stripped_strings if clean(x)]
    # Goal-minute table: başlık sonrası 6 satır aralığı.
    gm_key=f'Gol dakikaları ({side_label})'
    for idx,line in enumerate(lines):
        if line.startswith('Gol dakikaları') and side_label in line:
            j=idx+1
            while j < len(lines) and len(result['goal_minutes'])<6:
                if re.fullmatch(r'\d+\s*-\s*\d+',lines[j]):
                    band=lines[j]
                    nums=[]
                    for k in range(j+1,min(j+5,len(lines))):
                        if re.fullmatch(r'\d+',lines[k]): nums.append(int(lines[k]))
                    if len(nums)>=3:
                        result['goal_minutes'][band]={'scored':nums[0],'conceded':nums[1],'total':nums[2]}
                    j += 3
                else:
                    j += 1
    # More robust regex from visible text for W/D/L percentage triplets.
    # Use known labels and first occurrences tied to the side name.
    m=re.search(rf'(?:Maç Sonucu\s*\({re.escape(side_label)}\)).{{0,500}}?', text, re.I)
    if m:
        block=m.group(0)
    # Extract counts around labels using line order.
    for idx,line in enumerate(lines):
        if line == f'{side_label}' and idx+1 < len(lines):
            pass
    # Fallback: parse percentages from a compact normalized block around side-specific label.
    def get_triplet(label):
        mm=re.search(rf'{re.escape(label)}\s+\({re.escape(side_label)}\)(.*?)\s+(?:{re.escape(label)}\s+\(|\Z)',text,re.I)
        if not mm: return None
        b=mm.group(1)
        vals=[]
        for name in ['Galibiyet','Beraberlik','Mağlubiyet']:
            q=re.search(rf'{name}:\s*(\d+).*?%(\d+)',b,re.I)
            vals.append(int(q.group(2)) if q else None)
        return vals
    vals=get_triplet('Maç Sonucu')
    if vals: result['win'],result['draw'],result['loss']=vals
    vals=get_triplet('İlk Yarı Sonucu')
    if vals: result['ht_win'],result['ht_draw'],result['ht_loss']=vals
    # BTTS
    mm=re.search(rf'Karşılıklı Gol\s*\({re.escape(side_label)}\)(.*?)(?:Karşılıklı Gol\s*\(|Gol dakikaları)',text,re.I)
    if mm:
        b=mm.group(1)
        q=re.search(r'Var:\s*\d+.*?%(\d+)',b,re.I); result['btts_yes']=int(q.group(1)) if q else None
        q=re.search(r'Yok:\s*\d+.*?%(\d+)',b,re.I); result['btts_no']=int(q.group(1)) if q else None
    return result


def parse_last_results(raw, team_name, limit=5):
    """Takım sayfasındaki maç linklerini ve skorlarını en yeni 5 kayıt olarak yaklaşık çıkarır."""
    soup=BeautifulSoup(raw,'html.parser')
    team_slug=norm_slug(team_name)
    rows=[]; seen=set()
    for a in soup.find_all('a',href=True):
        href=a.get('href','')
        if '/mac/' not in href.lower(): continue
        if href.startswith('/'):
            href='https://www.sahadan.com'+href
        txt=clean(a.get_text(' ',strip=True))
        parent=clean(a.parent.get_text(' ',strip=True)) if a.parent else txt
        blob=(txt+' '+parent)
        if not re.search(r'\b\d+\s*-\s*\d+\b',blob):
            # score may be in ancestor
            anc=a.find_parent(['li','tr','div'])
            blob += ' '+(clean(anc.get_text(' ',strip=True)) if anc else '')
        sm=re.search(r'\b(\d+)\s*-\s*(\d+)\b',blob)
        if not sm: continue
        if href in seen: continue
        seen.add(href)
        # Date in row, if present.
        dm=re.search(r'\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)\b',blob)
        date=dm.group(1) if dm else ''
        # Determine whether team was home from URL slug.
        path=urlparse(href).path.lower()
        slug=path.split('/mac/',1)[-1].split('/')[0]
        ns=norm_slug(team_name)
        home_first = ns and slug.startswith(ns+'-vs-')
        # fallback by text
        if not home_first:
            home_first = not (re.search(r'vs-[^/]*'+re.escape(team_slug),slug))
        gf=int(sm.group(1)) if home_first else int(sm.group(2))
        ga=int(sm.group(2)) if home_first else int(sm.group(1))
        result='W' if gf>ga else 'D' if gf==ga else 'L'
        rows.append({'date':date,'score':f'{gf}-{ga}','gf':gf,'ga':ga,'result':result,'url':href})
    return rows[-limit:]


def _num(v, default=0.0):
    if v is None or v == '':
        return float(default)
    try:
        return float(str(v).replace(',', '.').replace('%','').strip())
    except (TypeError, ValueError):
        return float(default)

def score_team(stats,last5,side):
    stats=stats or {}
    last5=last5 or []
    clean=[]
    for x in last5:
        if not isinstance(x,dict):
            continue
        clean.append({**x, 'gf':_num(x.get('gf')), 'ga':_num(x.get('ga')), 'result':x.get('result') or 'D'})
    last5=clean
    form=sum(3 if x['result']=='W' else 1 if x['result']=='D' else 0 for x in last5)
    form_pct=100.0*form/max(1,3*len(last5))
    recent2=last5[:2]
    momentum=100.0*sum(3 if x['result']=='W' else 1 if x['result']=='D' else 0 for x in recent2)/max(1,6)
    gf=sum(_num(x.get('gf')) for x in last5)/max(1,len(last5)); ga=sum(_num(x.get('ga')) for x in last5)/max(1,len(last5))
    attack=min(100.0,gf/2.5*100.0); defense=max(0.0,100.0-ga/2.5*100.0)
    ht=_num(stats.get('ht_win'))*1.0 + _num(stats.get('ht_draw'))*0.35
    btts=_num(stats.get('btts_yes'))
    timing=sum(v.get('scored',0) for v in (stats.get('goal_minutes') or {}).values())
    late=sum(v.get('scored',0) for k,v in (stats.get('goal_minutes') or {}).items() if k.startswith(('60','75')))
    # Son 5 özel göstergeler
    btts5=sum(1 for x in last5 if x.get('gf',0)>0 and x.get('ga',0)>0)
    over25=sum(1 for x in last5 if x.get('gf',0)+x.get('ga',0)>=3)
    under25=len(last5)-over25
    ht_goal5=sum(1 for x in last5 if x.get('ht_score') and sum(map(int,x['ht_score'].split('-')))>0)
    comeback=0; rescued=0
    for x in last5:
        ht=x.get('ht_score')
        if not ht or '-' not in ht: continue
        try: htg,hta=map(int,ht.split('-'))
        except: continue
        if htg<hta and x.get('gf',0)>=x.get('ga',0): comeback+=1
        if htg<hta and x.get('gf',0)>x.get('ga',0): rescued+=1
    total=0.25*_num(form_pct)+0.20*_num(momentum)+0.20*_num(attack)+0.20*_num(defense)+0.10*_num(ht)+0.05*_num(btts)
    return round(max(0,min(100,total)),1), {
      'form_pct':round(form_pct,1),'momentum':round(momentum,1),'avg_gf':round(gf,2),'avg_ga':round(ga,2),
      'attack':round(attack,1),'defense':round(defense,1),'ht_signal':round(ht,1),'btts_yes':btts,
      'goal_count_for_timing':timing,'late_goal_share':round(late/max(1,timing)*100,1),
      'last5_btts_pct':round(btts5/max(1,len(last5))*100,1),'last5_over25_pct':round(over25/max(1,len(last5))*100,1),
      'last5_under25_pct':round(under25/max(1,len(last5))*100,1),'last5_ht_goal_pct':round(ht_goal5/max(1,len(last5))*100,1),
      'last5_comeback':comeback,'last5_comeback_win':rescued
    }


# --- v9 geçmiş oran karşılaştırma motoru ---
_ANALYSIS_CACHE = {}

def normalize_label(s):
    s=clean(s).lower()
    for a,b in [('ı','i'),('ş','s'),('ğ','g'),('ü','u'),('ö','o'),('ç','c')]: s=s.replace(a,b)
    return re.sub(r'\s+',' ',s).strip()

def market_map(markets):
    return {normalize_label(m.get('name','')):{normalize_label(o.get('label','')):o.get('odds') for o in (m.get('options') or [])} for m in (markets or []) if m.get('name')}

def first_market(maps,names):
    for n in names:
        nn=normalize_label(n)
        for k,v in maps.items():
            if k==nn or nn in k or k in nn: return v
    return None

def option_odds(opts,labels):
    if not opts:return None
    for lab in labels:
        n=normalize_label(lab)
        for k,v in opts.items():
            if k==n:return v
    return None

def outcome_for_market(market_name,option_label,score,ht_score=None):
    if not score or '-' not in score:return None
    try:hg,ag=map(int,score.split('-',1))
    except:return None
    mn=normalize_label(market_name); op=normalize_label(option_label)
    if 'mac sonucu' in mn or mn=='ms': return {'1':hg>ag,'x':hg==ag,'2':hg<ag}.get(op)
    if 'karsilikli gol' in mn or mn=='kg':
        yes=hg>0 and ag>0
        return yes if op=='var' else (not yes if op=='yok' else None)
    total=hg+ag
    for line,n in [('2,5',3),('2.5',3),('1,5',2),('1.5',2),('3,5',4),('3.5',4)]:
        if line in mn and ('alt' in op or 'ust' in op): return total<n if 'alt' in op else total>=n
    if 'ilk yari sonucu' in mn or mn in ('iy','1. yari sonucu'):
        if not ht_score or '-' not in ht_score:return None
        try:hh,ah=map(int,ht_score.split('-',1))
        except:return None
        return {'1':hh>ah,'x':hh==ah,'2':hh<ah}.get(op)
    if 'ilk yari' in mn and ('1,5' in mn or '1.5' in mn) and ('alt' in op or 'ust' in op):
        if not ht_score or '-' not in ht_score:return None
        try:hh,ah=map(int,ht_score.split('-',1))
        except:return None
        return (hh+ah<2) if 'alt' in op else (hh+ah>=2)
    return None

def parse_ht_score(blob):
    if not blob:return None
    m=re.search(r'(?:İY|İlk Yarı)\s*(\d+)\s*[-:]\s*(\d+)',blob,re.I)
    return f'{m.group(1)}-{m.group(2)}' if m else None

def parse_last_results_v9(raw,team_name,limit=5):
    soup=BeautifulSoup(raw,'html.parser'); ns=norm_slug(team_name); rows=[]; seen=set()
    for a in soup.find_all('a',href=True):
        href=a.get('href','')
        if '/mac/' not in href.lower():continue
        if href.startswith('/'):href='https://www.sahadan.com'+href
        anc=a.find_parent(['li','tr','article','div']); blob=clean((anc or a).get_text(' ',strip=True))
        if len(blob)>900:blob=clean(a.get_text(' ',strip=True))
        sm=re.search(r'\b(\d+)\s*[-:]\s*(\d+)\b',blob)
        if not sm or href in seen:continue
        seen.add(href); slug=urlparse(href).path.lower().split('/mac/',1)[-1].split('/')[0]
        left=slug.split('-vs-',1)[0] if '-vs-' in slug else ''
        home_first=bool(ns and (left==ns or left.startswith(ns+'-') or ns.startswith(left+'-')))
        hg,ag=int(sm.group(1)),int(sm.group(2)); gf,ga=(hg,ag) if home_first else (ag,hg)
        ht=parse_ht_score(blob)
        if ht and not home_first:
            x,y=ht.split('-');ht=f'{y}-{x}'
        dm=re.search(r'\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)\b',blob)
        rows.append({'date':dm.group(1) if dm else '','score':f'{gf}-{ga}','gf':gf,'ga':ga,'result':'W' if gf>ga else 'D' if gf==ga else 'L','ht_score':ht,'url':href})
    return rows[-limit:]

def comparison_url_v9(detail_url):
    parts=urlparse(detail_url).path.strip('/').split('/');
    if 'mac' not in parts:return None
    i=parts.index('mac')
    if len(parts)>=i+4 and parts[i+2].lower()=='iddaa':return 'https://www.sahadan.com/'+'/'.join(parts[:i+2]+[parts[i+3],'karsilastirma'])
    return None

def parse_h2h_v9(raw,home,away,limit=5):
    soup=BeautifulSoup(raw,'html.parser'); hs,aws=norm_slug(home),norm_slug(away);out=[];seen=set()
    for a in soup.find_all('a',href=True):
        href=a.get('href','')
        if '/mac/' not in href.lower():continue
        if href.startswith('/'):href='https://www.sahadan.com'+href
        slug=urlparse(href).path.lower().split('/mac/',1)[-1].split('/')[0]
        if '-vs-' not in slug:continue
        l,r=slug.split('-vs-',1)
        if not ((hs in l or l in hs) and (aws in r or r in aws)) and not ((aws in l or l in aws) and (hs in r or r in hs)):continue
        if href in seen:continue
        anc=a.find_parent(['li','tr','article','div']);blob=clean((anc or a).get_text(' ',strip=True));sm=re.search(r'\b(\d+)\s*[-:]\s*(\d+)\b',blob)
        if not sm:continue
        seen.add(href);out.append({'score':f'{sm.group(1)}-{sm.group(2)}','url':href})
    return out[-limit:]

def historical_market_comparison(current_markets,history_details):
    rows=[]
    for m in current_markets or []:
        mn=m.get('name','')
        for o in m.get('options') or []:
            if o.get('odds') in (None,'','-'):continue
            hist=[];hits=[]
            for h in history_details:
                hv=first_market(market_map(h.get('markets')), [mn])
                ho=option_odds(hv,[o.get('label','')])
                if ho in (None,'','-'):continue
                try:hist.append(float(ho))
                except:pass
                outcome=outcome_for_market(mn,o.get('label',''),h.get('score'),h.get('ht_score'))
                if outcome is not None:hits.append(1 if outcome else 0)
            current=float(o['odds']); avg=round(sum(hist)/len(hist),2) if hist else None
            hit=round(sum(hits)/len(hits)*100,1) if hits else None; implied=round(100/current,1)
            edge=round(hit-implied,1) if hit is not None else None
            signal='green' if edge is not None and edge>=5 else 'red' if edge is not None and edge<=-5 else 'yellow'
            rows.append({'market':mn,'option':o.get('label'),'current_odds':current,'historical_avg_odds':avg,'historical_odds_count':len(hist),'historical_hit_rate':hit,'current_implied_pct':implied,'edge_pct':edge,'signal':signal})
    return rows

def technical_analysis_v9(detail_url):
    now=time.time();cached=_ANALYSIS_CACHE.get(detail_url)
    if cached and now-cached[0]<600:return cached[1]
    raw=fetch(detail_url);soup=BeautifulSoup(raw,'html.parser');p=urlparse(detail_url);parts=p.path.strip('/').split('/');slug=parts[parts.index('mac')+1] if 'mac' in parts and len(parts)>parts.index('mac')+1 else ''
    bits=slug.split('-vs-');home=clean(bits[0].replace('-',' ')) if len(bits)==2 else '';away=clean(bits[1].replace('-',' ')) if len(bits)==2 else ''
    links=[]
    for a in soup.find_all('a',href=True):
        if '/takim/' not in a.get('href','').lower():continue
        h=clean(a.get_text(' ',strip=True));u=a.get('href');
        if u.startswith('/'):u='https://www.sahadan.com'+u
        if h and u and all(u!=z[1] for z in links):links.append((h,u))
    if len(links)>=2:home,away=links[0][0],links[1][0]
    current=parse_detail_markets(raw);stat_url=find_stat_url(detail_url);stat_raw=fetch(stat_url) if stat_url else raw;hs=parse_stat_blocks(stat_raw,'home');aws=parse_stat_blocks(stat_raw,'away')
    histories={}
    for side,team in [('home',home),('away',away)]:
        tu=next((u for h,u in links if norm_slug(h)==norm_slug(team)),None);histories[side]=[]
        if tu:
            try:histories[side]=parse_last_results_v9(fetch(tu),team,5)
            except Exception:pass
    history_details=[]
    for side in ('home','away'):
        for r in histories[side]:
            try:r['markets']=parse_detail_markets(fetch(r['url']));history_details.append(r)
            except Exception:pass
    hscore,hd=score_team(hs,histories['home'],'home');ascore,ad=score_team(aws,histories['away'],'away');edge=round(hscore-ascore,1)
    result='Dengeli / X eğilimi' if abs(edge)<7 else ('1 eğilimi' if edge>0 else '2 eğilimi')
    avg_total=(hd['avg_gf']+hd['avg_ga']+ad['avg_gf']+ad['avg_ga'])/2;btts=((hd.get('btts_yes') or 0)+(ad.get('btts_yes') or 0))/2
    goal='ÜST eğilimi' if avg_total>=2.6 or btts>=65 else 'ALT eğilimi' if avg_total<=2.0 and btts<=45 else 'Kararsız'
    h2h=[];cu=comparison_url_v9(detail_url)
    if cu:
        try:h2h=parse_h2h_v9(fetch(cu),home,away,5)
        except Exception:pass
    comp=historical_market_comparison(current,history_details)
    payload={'ok':True,'version':'v9-history-odds-analysis','match':{'home':home,'away':away,'detail_url':detail_url},'prediction':{'home_score':hscore,'away_score':ascore,'edge':edge,'result_signal':result,'goal_signal':goal},'home':{'last5':histories['home'],'stats':hs,'details':hd},'away':{'last5':histories['away'],'stats':aws,'details':ad},'h2h_last5':h2h,'current_markets':current,'historical_market_comparison':comp,'green_signals':sorted([x for x in comp if x['signal']=='green'],key=lambda x:x['edge_pct'] or -999,reverse=True)[:12],'history_matches_used':len(history_details),'fetched_at':datetime.now().isoformat(timespec='seconds')}
    _ANALYSIS_CACHE[detail_url]=(now,payload);return payload

def technical_analysis(detail_url):
    raw=fetch(detail_url)
    soup=BeautifulSoup(raw,'html.parser')
    # Başlık/ilk metin ile takım adlarını teyit et.
    title=clean(soup.title.get_text(' ',strip=True)) if soup.title else ''
    team_links=extract_team_links(raw, '', '')
    # URL slug takım adları için güvenilir yedek.
    p=urlparse(detail_url); seg=p.path.strip('/').split('/')
    slug=seg[seg.index('mac')+1] if 'mac' in seg and len(seg)>seg.index('mac')+1 else ''
    bits=slug.split('-vs-')
    home=clean(bits[0].replace('-',' ')) if len(bits)==2 else ''
    away=clean(bits[1].replace('-',' ')) if len(bits)==2 else ''
    # Sayfadaki ilk iki takım bağlantısını kullan.
    links=[]
    for a in soup.find_all('a',href=True):
        if '/takim/' in a.get('href','').lower():
            h=clean(a.get_text(' ',strip=True)); u=a.get('href')
            if u.startswith('/'): u='https://www.sahadan.com'+u
            if h and u and all(u!=x[1] for x in links): links.append((h,u))
    if len(links)>=2:
        home,away=links[0][0],links[1][0]
    # Stat page: goal minutes + season form.
    stat_url=find_stat_url(detail_url)
    stat_raw=fetch(stat_url) if stat_url else raw
    hs=parse_stat_blocks(stat_raw,'home'); aws=parse_stat_blocks(stat_raw,'away')
    # Team fixture pages
    def team_page(team):
        ns=norm_slug(team)
        for h,u in links:
            if norm_slug(h)==ns: return u
        return None
    histories={}
    for side,team in [('home',home),('away',away)]:
        tu=team_page(team)
        if tu:
            try: histories[side]=parse_last_results(fetch(tu),team,5)
            except Exception: histories[side]=[]
        else: histories[side]=[]
    hscore,hdetail=score_team(hs,histories['home'],'home')
    ascore,adetail=score_team(aws,histories['away'],'away')
    edge=round(hscore-ascore,1)
    if abs(edge)<7: result='Dengeli / X eğilimi'
    elif edge>0: result='1 eğilimi'
    else: result='2 eğilimi'
    # Goals signal from recent averages + BTTS.
    avg_total=(hdetail['avg_gf']+hdetail['avg_ga']+adetail['avg_gf']+adetail['avg_ga'])/2
    btts_avg=((hdetail['btts_yes'] or 0)+(adetail['btts_yes'] or 0))/2
    goal_signal='ÜST eğilimi' if avg_total>=2.6 or btts_avg>=65 else 'ALT eğilimi' if avg_total<=2.0 and btts_avg<=45 else 'Kararsız'
    return {'ok':True,'match':{'home':home,'away':away,'detail_url':detail_url},'prediction':{'home_score':hscore,'away_score':ascore,'edge':edge,'result_signal':result,'goal_signal':goal_signal},'home':{'last5':histories['home'],'stats':hs,'details':hdetail},'away':{'last5':histories['away'],'stats':aws,'details':adetail},'fetched_at':datetime.now().isoformat(timespec='seconds')}


@app.get('/api/technical-analysis')
def technical_analysis_api():
    url=request.args.get('url','').strip()
    p=urlparse(url)
    if p.scheme not in ('http','https') or p.netloc.lower() not in ('www.sahadan.com','sahadan.com') or '/mac/' not in p.path.lower():
        return jsonify({'ok':False,'error':'Geçersiz Sahadan maç adresi'}),400
    try:
        return jsonify(technical_analysis_v9(url))
    except Exception as e:
        return jsonify({'ok':False,'error':f'{type(e).__name__}: {e}'}),502
