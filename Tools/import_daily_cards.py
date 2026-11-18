#!/usr/bin/env python3
"""Günün kartları (fecr-icerik deposuna taşınır).

Her çalışmada İstanbul gününe ait üç paylaşım kartı üretir ve uygulamanın görsel şeridinde en başta
görünmeleri için şu adlarla yazar:
`Ayet/00-gunun-ayeti.jpg`, `Hadis/00-gunun-hadisi.jpg`, `Dua/00-gunun-duasi.jpg`.

    python3 import_daily_cards.py <fecr-icerik klonu> [--today YYYY-MM-DD]

Çıkış kodu: 0 = bugünün kartları yayında (yeni yazıldı ya da zaten vardı), 2 = kartlar tamamlanamadı
(kaynak erişilemedi ya da çizim başarısız; hiçbir dosya değişmedi, dünkü kartlar korunur).

Kurallar:
- Metin üretilmez, kısaltılmaz, değiştirilmez.
  - Ayetlerde Tanzil Arapçası (CC BY 3.0) ve QuranEnc Rowwad meali (1.0.4) kullanılır.
    - Arapça metin, depodaki resmî Tanzil Uthmani 1.1 dosyasından (`Tools/kaynak/quran-uthmani.txt`)
      telif bloğuyla birlikte alınır.
    - Meal, `risan/quran-json` deposunun sabit bir sürümünden alınır.
    - İki dosya da SHA-256 ile doğrulanır.
  - Hadislerde `Tools/kaynak/hadeethenc-tr.json` (uygulamadaki paketli HadeethEnc arşivinin kopyası)
    kaydının başlığı ile Arapça başlığı kullanılır.
    Kartın üstünde yayıncı, eser ve sürüm yazar.
- Metinler yalnızca `daily_cards_pool.json` dosyasında elle seçilmiş ayet, dua ve hadislerden alınır.
- Fotoğraflar yalnızca aynı dosyada elle seçilmiş Wikimedia Commons dosyalarından alınır.
  - Lisans her çalışmada Commons API'sinden yeniden okunur.
  - Yalnızca `cc0` ve `pd` lisanslı, kullanım kısıtı olmayan dosyalar kullanılır.
  - Lisansı değişen dosya bir daha denenmez.
  - Fotoğrafçı ve lisans kartın üzerinde yazar.
- Her türde önce hiç gösterilmeyen, sonra en uzun süredir gösterilmeyen kayıt seçilir.
- Kanıt `Tools/daily_cards_state.json` dosyasına yazılır: seçilen kayıtlar, Commons sayfası, lisans,
  yazar ve özgün dosyanın SHA-1'i.

Çizim `render_daily_card.swift` ile yapılır (macOS; Arapça harf birleştirmesi CoreText ile).
Yazı tipleri `Tools/fonts/` klasöründedir (SIL OFL 1.1, lisans dosyalarıyla).
Yalnızca standart kütüphane kullanılır.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")
USER_AGENT = "FecrIcerik/1.0 (+https://github.com/gturkmenlabs/fecr-icerik)"
POOL_FILE = "Tools/daily_cards_pool.json"
STATE_FILE = "Tools/daily_cards_state.json"
# Uygulamadaki paketli HadeethEnc arşivinin kopyası. `Hadis/` altına konmaz: orası uygulamanın "Güncelle" kaynağıdır.
HADITH_FILE = "Tools/kaynak/hadeethenc-tr.json"
FONTS_DIR = "Tools/fonts"
RENDERER = "Tools/render_daily_card.swift"
OUTPUTS = {"ayet": "Ayet/00-gunun-ayeti.jpg", "hadis": "Hadis/00-gunun-hadisi.jpg", "dua": "Dua/00-gunun-duasi.jpg"}
BADGES = {"ayet": "GÜNÜN AYETİ", "hadis": "GÜNÜN HADİSİ", "dua": "GÜNÜN DUASI"}

# Tanzil'in resmî Uthmani 1.1 dosyası (txt-2, telif bloğuyla değiştirilmeden; uygulamadaki arabic.json'un kaynağı).
# `risan/quran-json` kopyası vakıf/hizb/secde işaretlerini çıkardığı için Arapça için kullanılmaz.
ARABIC_FILE = "Tools/kaynak/quran-uthmani.txt"
ARABIC_SHA256 = "4b91f9e6e8ac645d039e4ed85b3be492e795232a31cd22d668ac58238722e26f"
# QuranEnc Rowwad 1.0.4; güncel QuranEnc metniyle kelimesi kelimesine aynı (2026-11-18 karşılaştırması).
TURKISH_URL = ("https://raw.githubusercontent.com/risan/quran-json/b197d1ba6711767490c627065c01868f8eb488c7"
               "/data/quranenc/turkish_rwwad.json")
TURKISH_SHA256 = "a12c7e334500160b3234fc4129e32498faabe2c0d6f1e91a04f71cfcd72d2ab2"
QURAN_SOURCE = "Arapça: Tanzil.net, Uthmani 1.1 (CC BY 3.0) · Meal: Rowwad Tercüme Merkezi, Türkçe 1.0.4 · QuranEnc.com"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FREE_LICENSES = {"cc0", "pd"}
MEDIA_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}  # Commons küçük resimleri thumb.* adresinden verir.
CARD_HEIGHT = 1920
MAX_ASPECT = 2.4  # Daha geniş panoramalar dikey kartta aşırı büyütülür.
MAX_PHOTO_TRIES = 12

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


class SourceError(Exception):
    """Kaynak alınamadı ya da doğrulanamadı: hiçbir dosya değiştirilmez."""


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def verified(getter, url: str, sha256: str) -> bytes:
    data = getter(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SourceError(f"{url} beklenen dosya değil (SHA-256 uyuşmuyor)")
    return data


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def spoken_date(iso: str) -> str:
    day = datetime.strptime(iso, "%Y-%m-%d")
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


# MARK: - Metin kaynakları

def parse_ref(ref: str):
    chapter, verses = ref.split(":")
    first, _, last = verses.partition("-")
    return int(chapter), int(first), int(last or first)


def verse_index(data: dict) -> dict:
    return {(int(chapter), verse["verse"]): verse["text"] for chapter, verses in data.items() for verse in verses}


def tanzil_index(repo: Path) -> dict:
    """Depodaki Tanzil txt-2 dosyası (`sure|ayet|metin`); SHA-256 ve telif bloğu doğrulanır."""
    try:
        raw = (repo / ARABIC_FILE).read_bytes()
    except OSError as error:
        raise SourceError(f"{ARABIC_FILE} okunamadı") from error
    if hashlib.sha256(raw).hexdigest() != ARABIC_SHA256:
        raise SourceError(f"{ARABIC_FILE} beklenen Tanzil dosyası değil (SHA-256 uyuşmuyor)")
    text = raw.decode("utf-8")
    if "Tanzil Quran Text (Uthmani" not in text or "CHANGING IT IS NOT ALLOWED" not in text:
        raise SourceError("Tanzil telif bloğu yok")
    verses = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            sura, aya, verse = line.split("|", 2)
            verses[(int(sura), int(aya))] = verse
    return verses


def fold(text: str) -> str:
    """Harekesiz karşılaştırma (uygulamadaki `QuranSearchIndex.fold` gibi): işaretler atılır, ٱ → ا."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn").replace("ٱ", "ا")


def opening_basmala(chapter: int, text: str, arabic: dict):
    """Tanzil metninde 1. ayetin başındaki besmele (Fâtiha ve Tevbe hariç): (besmele, kalan) ya da None.
    Uygulamadaki `QuranLibrary.openingBasmala` ile aynı kural; yalnızca gösterim için ayrılır."""
    if chapter in (1, 9):
        return None
    words = text.split(" ", 4)
    prefix = " ".join(words[:4])
    if len(words) != 5 or fold(prefix) != fold(arabic[(1, 1)]):
        return None
    return prefix, words[4]


def quran_card(ref: str, arabic: dict, turkish: dict, surah_names: list) -> dict:
    """Ayet ya da ayet aralığı; her ayetin sonunda ﴿numara﴾ yazar, metin değişmez.
    1. ayetin başındaki besmele ayrı satıra alınır (besmele + kalan == ayet metni)."""
    chapter, first, last = parse_ref(ref)
    numbers = range(first, last + 1)
    if any((chapter, n) not in arabic or (chapter, n) not in turkish for n in numbers):
        raise KeyError(ref)
    meal = [turkish[(chapter, n)] for n in numbers]
    if any("<" in text or "[" in text for text in meal):
        raise ValueError(f"{ref}: mealde dipnot/işaret var; kısaltmadan gösterilemez")
    header = ""
    verses_ar = []
    for n in numbers:
        text = arabic[(chapter, n)]
        split = opening_basmala(chapter, text, arabic) if n == 1 else None
        if split:
            header, text = split[0] + "\n", split[1]
        # Bölünmez boşluk: numara satır başına tek düşmez.
        verses_ar.append(f"{text} ﴿{str(n).translate(ARABIC_DIGITS)}﴾")
    ar = header + " ".join(verses_ar)
    verses = f"{first}-{last}" if last != first else f"{first}"
    return {"arapca": ar, "metin": " ".join(meal), "kunye": f"{surah_names[chapter - 1]} Sûresi, {chapter}:{verses}",
            "kaynak": QURAN_SOURCE, "ref": ref}


def hadith_archive(repo: Path) -> dict:
    archive = load_json(repo / HADITH_FILE, None)
    if not isinstance(archive, dict):
        raise SourceError(f"{HADITH_FILE} okunamadı")
    surum, belge = archive.get("surum", ""), archive.get("belge", "")
    if (archive.get("yayinci") != "HadeethEnc.com" or not (archive.get("lisans") or "").strip()
            or not (archive.get("kaynak") or "").strip() or re.fullmatch(r"v\d+\.\d+\.\d+", surum) is None
            or f"({surum})" not in belge or "PLEASE DON'T REMOVE" not in belge):
        raise SourceError("HadeethEnc yayıncı, lisans, sürüm veya özgün belge bilgisi eksik")
    return archive


def hadith_card(publisher_id: str, archive: dict) -> dict:
    entry = next((e for e in archive.get("hadisler") or [] if e.get("publisher_id") == publisher_id), None)
    original = (entry or {}).get("ozgun") or {}
    title, title_ar = (original.get("title") or "").strip(), (original.get("title_ar") or "").strip()
    if not title or not title_ar:
        raise KeyError(publisher_id)
    grade = " · ".join(part.strip().strip("[]") for part in (original.get("grade"), original.get("takhrij")) if part)
    eser = archive["kaynak"].split("—")[-1].strip()
    link = original.get("link") or f"https://hadeethenc.com/tr/browse/hadith/{publisher_id}"
    return {"arapca": title_ar, "metin": title, "kunye": grade,
            "kaynak": f"HadeethEnc.com · {eser} {archive['surum']} · {link.removeprefix('https://')}",
            "ref": f"hadeethenc:{publisher_id}"}


# MARK: - Seçim

def rotation(keys: list, used: dict, today: str) -> list:
    """Önce hiç gösterilmeyenler, sonra en eski gösterilenler; eşitlikte güne bağlı sabit karışık sıra."""
    return sorted(keys, key=lambda key: (used.get(key, ""), hashlib.sha256(f"{today}|{key}".encode()).hexdigest()))


def pick_text(kind: str, keys: list, state: dict, today: str, build):
    for key in rotation(keys, state["kullanim"][kind], today):
        try:
            return key, build(key)
        except (KeyError, ValueError):
            continue  # Kaynakta yok ya da kurala uymuyor; sıradakine geç.
    raise SourceError(f"{kind}: havuzda kullanılabilir kayıt kalmadı")


# MARK: - Fotoğraf

def commons_info(title: str, getter) -> dict:
    query = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "titles": title, "prop": "imageinfo",
        "iiprop": "url|sha1|mime|size|extmetadata", "iiurlheight": CARD_HEIGHT,
        "iiextmetadatafilter": "License|LicenseShortName|Artist|Restrictions",
    })
    pages = json.loads(getter(f"{COMMONS_API}?{query}"))["query"]["pages"]
    if not pages or pages[0].get("missing") or not pages[0].get("imageinfo"):
        raise KeyError(title)
    return pages[0]["imageinfo"][0]


def photo_verdict(info: dict) -> str | None:
    """None = kullanılabilir; aksi halde neden. "lisans" kalıcıdır, diğerleri o güne özgüdür."""
    meta = info.get("extmetadata") or {}
    if meta.get("License", {}).get("value") not in FREE_LICENSES or plain(meta.get("Restrictions", {}).get("value")):
        return "lisans"
    if info.get("mime") != "image/jpeg" or not info.get("width") or not info.get("height"):
        return "bicim"
    if info["width"] / info["height"] > MAX_ASPECT:
        return "bicim"
    url = urllib.parse.urlsplit(info.get("thumburl") or "")
    if url.scheme != "https" or url.hostname not in MEDIA_HOSTS:
        return "adres"
    return None


def credit(info: dict) -> str:
    meta = info["extmetadata"]
    artist = plain(meta.get("Artist", {}).get("value")) or "Bilinmiyor"
    if len(artist) > 60:
        artist = artist[:59].rstrip() + "…"
    return f"Fotoğraf: {artist} · {plain(meta.get('LicenseShortName', {}).get('value'))} · Wikimedia Commons"


def pick_photos(count: int, pool: list, state: dict, today: str, getter, workdir: Path) -> list:
    excluded = set(state["dislanan_fotograf"])
    chosen = []
    tries = 0
    for title in rotation([t for t in pool if t not in excluded], state["kullanim"]["fotograf"], today):
        if len(chosen) == count or tries >= MAX_PHOTO_TRIES:
            break
        tries += 1
        try:
            info = commons_info(title, getter)
        except KeyError:
            excluded.add(title)  # Commons'tan silinmiş.
            continue
        except Exception:
            continue  # Geçici hata.
        verdict = photo_verdict(info)
        if verdict == "lisans":
            excluded.add(title)
        if verdict:
            continue
        try:
            data = getter(info["thumburl"])
        except Exception:
            continue
        if not data.startswith(b"\xff\xd8"):
            continue
        path = workdir / f"foto-{len(chosen)}.jpg"
        path.write_bytes(data)
        chosen.append({"baslik": title, "dosya": path, "kredi": credit(info), "kanit": {
            "baslik": title, "sayfa": info.get("descriptionurl"), "indirilen": info["thumburl"],
            "ozgun_sha1": info.get("sha1"), "lisans": info["extmetadata"]["License"]["value"],
            "lisans_adi": plain(info["extmetadata"].get("LicenseShortName", {}).get("value")),
            "yazar": plain(info["extmetadata"].get("Artist", {}).get("value")),
        }})
    state["dislanan_fotograf"] = sorted(excluded)
    if len(chosen) < count:
        raise SourceError("Commons'tan yeterli lisanslı fotoğraf alınamadı")
    return chosen


# MARK: - Çizim

def swift_render(repo: Path, specs: list) -> None:
    subprocess.run(["swift", str(repo / RENDERER), str(repo / FONTS_DIR), *map(str, specs)], check=True)


def run(repo: Path, today: str, getter=fetch, render=swift_render) -> int:
    state_path = repo / STATE_FILE
    state = load_json(state_path, {})
    state.setdefault("son", None)
    state.setdefault("kullanim", {})
    for kind in ("ayet", "hadis", "dua", "fotograf"):
        state["kullanim"].setdefault(kind, {})
    state.setdefault("dislanan_fotograf", [])
    if (state["son"] or {}).get("tarih") == today and all((repo / path).exists() for path in OUTPUTS.values()):
        print(f"{today} kartları zaten yayında.")
        return 0

    pool = load_json(repo / POOL_FILE, None)
    if not pool:
        print(f"{POOL_FILE} okunamadı.", file=sys.stderr)
        return 2
    try:
        arabic = tanzil_index(repo)
        turkish = verse_index(json.loads(verified(getter, TURKISH_URL, TURKISH_SHA256)))
        archive = hadith_archive(repo)
        names = pool["sure_adlari"]
        texts = {
            "ayet": pick_text("ayet", pool["ayet"], state, today, lambda ref: quran_card(ref, arabic, turkish, names)),
            "hadis": pick_text("hadis", pool["hadis"], state, today, lambda key: hadith_card(key, archive)),
            "dua": pick_text("dua", pool["dua_ayet"] + [f"h:{key}" for key in pool["dua_hadis"]], state, today,
                             lambda key: hadith_card(key[2:], archive) if key.startswith("h:")
                             else quran_card(key, arabic, turkish, names)),
        }
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            photos = pick_photos(len(OUTPUTS), pool["fotograf"], state, today, getter, workdir)
            specs = []
            for (kind, (_, card)), photo in zip(texts.items(), photos):
                spec = workdir / f"{kind}.json"
                spec.write_text(json.dumps({
                    "arka_plan": str(photo["dosya"]), "cikti": str(workdir / f"{kind}.jpg"), "rozet": BADGES[kind],
                    "tarih": spoken_date(today), "arapca": card["arapca"], "metin": card["metin"],
                    "kunye": card["kunye"], "kaynak": card["kaynak"], "fotograf": photo["kredi"],
                }, ensure_ascii=False), encoding="utf-8")
                specs.append(spec)
            try:
                render(repo, specs)
            except (OSError, subprocess.CalledProcessError) as error:
                raise SourceError(f"çizim başarısız: {error}") from error
            rendered = {kind: workdir / f"{kind}.jpg" for kind in OUTPUTS}
            if not all(path.exists() and path.read_bytes().startswith(b"\xff\xd8") for path in rendered.values()):
                raise SourceError("çizim JPEG üretmedi")
            # Üç kart da hazırsa birlikte yerine konur.
            for kind, path in rendered.items():
                target = repo / OUTPUTS[kind]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), target)
    except SourceError as error:
        print(f"Kartlar tamamlanamadı: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # Ağ hataları vb.
        print(f"Kaynak erişilemedi: {error}", file=sys.stderr)
        return 2

    cards = []
    for (kind, (key, card)), photo in zip(texts.items(), photos):
        state["kullanim"][kind][key] = today
        state["kullanim"]["fotograf"][photo["baslik"]] = today
        cards.append({"tur": kind, "dosya": OUTPUTS[kind], "kayit": card["ref"], "kunye": card["kunye"],
                      "kaynak": card["kaynak"], "fotograf": photo["kanit"]})
    state["son"] = {"tarih": today, "kartlar": cards}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{today} kartları yazıldı: " + ", ".join(card["kayit"] for card in cards))
    return 0


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 1
    today = datetime.now(ISTANBUL).strftime("%Y-%m-%d")
    if "--today" in argv:
        today = argv[argv.index("--today") + 1]
    return run(Path(argv[0]), today)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
