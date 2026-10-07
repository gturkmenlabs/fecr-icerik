#!/usr/bin/env python3
"""Günün bilgisi ve hikâyesi içe aktarıcısı (fecr-icerik deposuna taşınır).

Her çalışmada İstanbul gününe tarihli bir bilgi ve bir hikâyeyi Diyanet Haber'den alıp
`Bilgi/bilgiler.json` (sürüm 2) olarak yazar. Şema: Tools/fecr-icerik-sema.md.

    python3 import_daily_info.py <fecr-icerik klonu> [--today YYYY-MM-DD]

Çıkış kodu: 0 = bugünün çifti yayında (yeni yazıldı ya da zaten vardı), 2 = çift tamamlanamadı
(hiçbir dosya değişmedi, eski çift korunur), 3 = künye izni doğrulanamadı.

Kurallar: metin yeniden yazılmaz, özetlenmez, üretilmez; yalnızca yazının kendi metni alınır.
Ajans kaynaklı yazılar, Diyanet Haber yayıncı kanıtı olmayanlar ve daha önce yayınlanmış URL/metin
reddedilir. Yalnızca standart kütüphane kullanılır.
"""
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HOST = "https://www.diyanethaber.com.tr"
KUNYE = f"{HOST}/kunye"
ISTANBUL = ZoneInfo("Europe/Istanbul")
FEEDS = {
    "bilgi": ["dini-kavramlar", "diyanet-bilgi"],
    "hikaye": ["bir-hikaye", "peygamberimizin-hayati", "sahabeler"],
}
INFO_FILE = "Bilgi/bilgiler.json"
STATE_FILE = "Tools/daily_info_state.json"
MIN_BODY = 200
CATEGORY_FETCH_LIMIT = 40
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
LICENSE = ("Diyanet Haber künyesi, ajans kaynaklı haberler hariç içeriğin etkin kaynak bağlantısı "
           f"belirtilerek kullanılmasına izin verir ({KUNYE}). Koşullu izindir; kamu malı değildir.")
SOURCE = f"Diyanet Haber, {HOST}"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "FecrIcerik/1.0 (+https://github.com/gturkmenlabs/fecr-icerik)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def tr_lower(value: str) -> str:
    return value.replace("İ", "i").replace("I", "ı").lower()


def kunye_allows_reuse(page: str) -> bool:
    text = tr_lower(re.sub(r'[\s"“”]+', " ", html.unescape(re.sub(r"<[^>]+>", " ", page))))
    return "aktif link" in text and "ajans kaynaklı haberler hariç" in text and "serbesttir" in text


def canonical(url: str):
    """Uygulamadaki InfoArchive.sourceURL ile aynı kural: https, www.diyanethaber.com.tr, düz yol."""
    match = re.fullmatch(r"https://www\.diyanethaber\.com\.tr/([a-z0-9][a-z0-9-]*)", url.strip())
    return f"{HOST}/{match.group(1)}" if match else None


def feed_items(xml_text: str):
    """RSS bağlantıları, akıştaki sırayla (en yeni önce)."""
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        url = canonical(item.findtext("link") or "")
        if url:
            items.append(url)
    return items


def category_links(page: str):
    found = []
    for match in re.finditer(r'href="(?:https://www\.diyanethaber\.com\.tr)?/([a-z0-9][a-z0-9-]*)"', page):
        url = f"{HOST}/{match.group(1)}"
        if url not in found:
            found.append(url)
    return found


def article(page: str, url: str):
    """Yazıdan {baslik, metin, bolum, tarih} çıkarır; ajans/yayıncı/uzunluk şartı sağlanmazsa None."""
    news = None
    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "NewsArticle":
            news = data
            break
    if not news:
        return None
    if (news.get("publisher") or {}).get("name") != "Diyanet Haber" or (news.get("creator") or {}).get("name") != "Diyanet Haber":
        return None
    source_block = re.search(r'<div class="article-source[^"]*">(.*?)</div>', page, re.S)
    if source_block and "source-name" in source_block.group(1):
        return None  # Ajans kaynaklı.
    title = html.unescape(re.sub(r"<[^>]+>", "", news.get("headline") or "")).strip()
    body = html.unescape(re.sub(r"<[^>]+>", "", news.get("articleBody") or ""))
    body = re.sub(r"[ \t]+\n", "\n", body.replace("\r\n", "\n").replace("\r", "\n"))
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not title or len(body) < MIN_BODY:
        return None
    date = (news.get("datePublished") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    return {"url": url, "baslik": title, "metin": body, "bolum": news.get("articleSection") or "", "tarih": date}


def digest(value: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", value).strip().encode("utf-8")).hexdigest()


def spoken_date(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day} {MONTHS[month - 1]} {year}"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def pick(kind: str, state: dict, getter, budget: list):
    """Daha önce yayınlanmamış ilk geçerli yazıyı döndürür; RSS bitince kategori sayfalarına bakar."""
    seen_urls, seen_texts, rejected = set(state["urls"]), set(state["texts"]), set(state["rejected"])

    def try_urls(urls):
        for url in urls:
            if url in seen_urls or url in rejected:
                continue
            if budget[0] <= 0:
                return None
            budget[0] -= 1
            try:
                parsed = article(getter(url), url)
            except Exception:
                continue  # Geçici hata; reddedilenlere yazma.
            if not parsed or digest(parsed["metin"]) in seen_texts:
                rejected.add(url)
                continue
            return parsed
        return None

    candidates = []
    for slug in FEEDS[kind]:
        try:
            candidates += [url for url in feed_items(getter(f"{HOST}/rss/{slug}")) if url not in candidates]
        except Exception:
            continue
    found = try_urls(candidates)
    if not found:
        budget[0] = min(budget[0], CATEGORY_FETCH_LIMIT)
        for slug in FEEDS[kind]:
            try:
                found = try_urls([url for url in category_links(getter(f"{HOST}/{slug}")) if url not in candidates])
            except Exception:
                continue
            if found:
                break
    state["rejected"] = sorted(rejected)
    return found


def entry(kind: str, parsed: dict) -> dict:
    result = {"tur": kind, "baslik": parsed["baslik"], "metin": parsed["metin"],
              "kaynak": f"Diyanet Haber, {spoken_date(parsed['tarih'])}", "kaynak_url": parsed["url"]}
    if parsed["bolum"] and not parsed["bolum"].startswith("#"):
        result["kategori"] = parsed["bolum"]
    return result


def run(repo: Path, today: str, getter=fetch) -> int:
    info_path, state_path = repo / INFO_FILE, repo / STATE_FILE
    current = load_json(info_path, {})
    if current.get("schema_version") == 2 and current.get("yayin_tarihi") == today:
        print(f"{today} çifti zaten yayında.")
        return 0
    try:
        if not kunye_allows_reuse(getter(KUNYE)):
            print("Künye izni doğrulanamadı; yayın yapılmadı.", file=sys.stderr)
            return 3
    except Exception as error:
        print(f"Künye okunamadı: {error}", file=sys.stderr)
        return 3
    state = load_json(state_path, {})
    state = {key: list(state.get(key, [])) for key in ("urls", "texts", "rejected")}
    budget = [120]
    chosen = {}
    for kind in ("bilgi", "hikaye"):
        parsed = pick(kind, state, getter, budget)
        if not parsed:
            print("Çift tamamlanamadı (aday havuzu tükendi veya kaynak erişilemedi); eski çift korunuyor.", file=sys.stderr)
            return 2
        chosen[kind] = parsed
        # Aynı yazı iki akışta çıksa bile çift farklı kaynaklardan oluşur.
        state["urls"].append(parsed["url"])
        state["texts"].append(digest(parsed["metin"]))
    payload = {"schema_version": 2, "yayin_tarihi": today, "lisans": LICENSE, "kaynak": SOURCE,
               "bilgiler": [entry(kind, chosen[kind]) for kind in ("bilgi", "hikaye")]}
    for path, value in ((info_path, payload), (state_path, state)):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    print(f"{today}: {chosen['bilgi']['url']} · {chosen['hikaye']['url']}")
    return 0


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 1
    today = datetime.now(ISTANBUL).strftime("%Y-%m-%d")
    if "--today" in argv:
        today = argv[argv.index("--today") + 1]
    return run(Path(argv[0]), today)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
