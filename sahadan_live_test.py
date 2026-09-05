
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.sahadan.com/canli-sonuclar"
UA = (
    "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
)

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_match_text(text):
    text = clean(text)

    # Live/finished: Home 1 - 0 Away
    m = re.match(r"^(.*?)\s+(\d+)\s*-\s*(\d+)\s+(.*?)$", text)
    if m:
        return {
            "home": clean(m.group(1)),
            "away": clean(m.group(4)),
            "home_score": int(m.group(2)),
            "away_score": int(m.group(3)),
            "state": "live_or_finished",
        }

    # Scheduled: Home v Away
    m = re.match(r"^(.*?)\s+v\s+(.*?)$", text, flags=re.I)
    if m:
        return {
            "home": clean(m.group(1)),
            "away": clean(m.group(2)),
            "home_score": None,
            "away_score": None,
            "state": "scheduled",
        }

    return None

def extract_live_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    for a in soup.select('a[href*="/mac/"]'):
        href = a.get("href", "")
        text = clean(a.get_text(" ", strip=True))
        if not text:
            continue

        parsed = parse_match_text(text)
        if not parsed:
            continue

        key = (
            href,
            parsed["home"],
            parsed["away"],
            parsed["home_score"],
            parsed["away_score"],
        )
        if key in seen:
            continue
        seen.add(key)

        parent_text = clean(a.parent.get_text(" ", strip=True)) if a.parent else ""
        minute = None
        mm = re.search(r"\b(\d{1,3}(?:\s*\+\s*\d{1,2})?)'\b", parent_text)
        if mm:
            minute = mm.group(1).replace(" ", "") + "'"

        parsed.update({
            "url": urljoin(SOURCE_URL, href),
            "minute": minute,
            "raw": text,
        })
        out.append(parsed)

    return out

def fetch():
    r = requests.get(
        SOURCE_URL,
        headers={
            "User-Agent": UA,
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        },
        timeout=20,
    )
    r.raise_for_status()

    matches = extract_live_matches(r.text)
    return {
        "ok": True,
        "source": SOURCE_URL,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "http_status": r.status_code,
        "html_bytes": len(r.content),
        "match_count": len(matches),
        "live": [m for m in matches if m["state"] == "live_or_finished"],
        "scheduled": [m for m in matches if m["state"] == "scheduled"],
    }

if __name__ == "__main__":
    try:
        print(json.dumps(fetch(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "source": SOURCE_URL,
            "error": f"{type(e).__name__}: {e}",
        }, ensure_ascii=False, indent=2))
        raise
