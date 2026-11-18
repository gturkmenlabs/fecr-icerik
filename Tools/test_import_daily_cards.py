"""import_daily_cards.py testleri: python3 -m pytest Tools/fecr-icerik (ağ ve çizim sahte)."""
import hashlib
import json
import sys
import tempfile
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_daily_cards as importer  # noqa: E402

BASMALA = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
ARABIC = {"1": [{"chapter": 1, "verse": 1, "text": BASMALA}],
          "94": [{"chapter": 94, "verse": 1, "text": f"{BASMALA} أَلَمْ"},
                 {"chapter": 94, "verse": 5, "text": "فَإِنَّ مَعَ ٱلْعُسْرِ يُسْرًا"},
                 {"chapter": 94, "verse": 6, "text": "إِنَّ مَعَ ٱلْعُسْرِ يُسْرًا"}]}
TURKISH = {"1": [{"chapter": 1, "verse": 1, "text": "Bismillah"}],
           "94": [{"chapter": 94, "verse": 1, "text": "Açmadık mı?"},
                  {"chapter": 94, "verse": 5, "text": "Zorlukla beraber kolaylık vardır."},
                  {"chapter": 94, "verse": 6, "text": "Gerçekten kolaylık vardır."}]}
TANZIL = ("# Tanzil Quran Text (Uthmani, Version 1.1)\n#  - Permission is granted to copy and distribute verbatim copies\n"
          "#    of this text, but CHANGING IT IS NOT ALLOWED.\n"
          + "".join(f"{c}|{v['verse']}|{v['text']}\n" for c, verses in ARABIC.items() for v in verses)).encode()
NAMES = [f"Sure{n}" for n in range(1, 115)]
NAMES[93] = "İnşirâh"


def archive(**overrides):
    data = {"schema_version": 1, "lisans": "Koşullar", "kaynak": "HadeethEnc.com — Nebevi Hadisler Ansiklopedisi Tercümesi",
            "yayinci": "HadeethEnc.com", "surum": "v1.71.0",
            "belge": "# Last update: x (v1.71.0)\n# PLEASE DON'T REMOVE THIS IMPORTANT INFORMATION!",
            "hadisler": [{"publisher_id": str(n), "no": str(n), "ozgun": {
                "title": f"Hadis {n}", "title_ar": f"حديث {n}", "grade": "[Sahih Hadis]", "takhrij": "[Buhârî rivayet etmiştir]",
                "link": f"https://hadeethenc.com/tr/browse/hadith/{n}"}} for n in (10, 11, 12)]}
    data.update(overrides)
    return data


def photo_info(license_="cc0", restrictions="", mime="image/jpeg", width=3000, height=2000,
               thumb="https://thumb.wikimedia.org/x.jpg"):
    return {"mime": mime, "width": width, "height": height, "thumburl": thumb, "sha1": "abc",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
            "extmetadata": {"License": {"value": license_}, "LicenseShortName": {"value": license_.upper()},
                            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:A">Ayşe</a>'},
                            "Restrictions": {"value": restrictions}}}


class Web:
    """Sahte ağ: meal dosyası (SHA-256 yamalanarak), Commons yanıtları başlığa göre."""

    def __init__(self, photos):
        self.photos, self.fetched = photos, []

    def __call__(self, url):
        self.fetched.append(url)
        if url == importer.TURKISH_URL:
            return json.dumps(TURKISH).encode()
        if url.startswith(importer.COMMONS_API):
            title = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["titles"][0]
            info = self.photos.get(title)
            if isinstance(info, Exception):
                raise info
            page = {"title": title, "missing": True} if info is None else {"title": title, "imageinfo": [info]}
            return json.dumps({"query": {"pages": [page]}}).encode()
        if "wikimedia.org" in url:
            return b"\xff\xd8 jpeg"
        raise OSError(url)


def fake_render(repo, specs):
    for spec in specs:
        Path(json.loads(Path(spec).read_text(encoding="utf-8"))["cikti"]).write_bytes(b"\xff\xd8 kart")


def make_repo(tmp, photos=("File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg"), hadith=None):
    repo = Path(tmp)
    (repo / "Tools" / "kaynak").mkdir(parents=True)
    pool = {"sure_adlari": NAMES, "ayet": ["94:5-6", "94:1"], "dua_ayet": ["94:6"], "dua_hadis": ["12"],
            "hadis": ["10", "11"], "fotograf": list(photos)}
    (repo / importer.POOL_FILE).write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    (repo / importer.HADITH_FILE).write_text(json.dumps(hadith or archive(), ensure_ascii=False), encoding="utf-8")
    (repo / importer.ARABIC_FILE).write_bytes(TANZIL)
    return repo


def patch_hashes(monkeypatch):
    monkeypatch.setattr(importer, "ARABIC_SHA256", hashlib.sha256(TANZIL).hexdigest())
    monkeypatch.setattr(importer, "TURKISH_SHA256", hashlib.sha256(json.dumps(TURKISH).encode()).hexdigest())


def state(repo):
    return json.loads((repo / importer.STATE_FILE).read_text(encoding="utf-8"))


def test_quran_card_keeps_text_and_splits_opening_basmala():
    arabic, turkish = importer.verse_index(ARABIC), importer.verse_index(TURKISH)
    card = importer.quran_card("94:5-6", arabic, turkish, NAMES)
    assert card["metin"] == "Zorlukla beraber kolaylık vardır. Gerçekten kolaylık vardır."
    assert card["arapca"] == "فَإِنَّ مَعَ ٱلْعُسْرِ يُسْرًا ﴿٥﴾ إِنَّ مَعَ ٱلْعُسْرِ يُسْرًا ﴿٦﴾"
    assert card["kunye"] == "İnşirâh Sûresi, 94:5-6"
    opening = importer.quran_card("94:1", arabic, turkish, NAMES)
    assert opening["arapca"] == f"{BASMALA}\nأَلَمْ ﴿١﴾"
    assert importer.opening_basmala(1, BASMALA, arabic) is None


def test_tanzil_file_is_read_verbatim_and_checked(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        try:
            importer.tanzil_index(repo)  # Gerçek SHA-256 sahte dosyayla uyuşmaz.
            raise AssertionError("yanlış dosya kabul edildi")
        except importer.SourceError:
            pass
        patch_hashes(monkeypatch)
        assert importer.tanzil_index(repo) == importer.verse_index(ARABIC)


def test_quran_card_refuses_footnotes_and_missing_verses():
    arabic, turkish = importer.verse_index(ARABIC), importer.verse_index(TURKISH)
    turkish[(94, 5)] = "Metin<sup>1</sup>"
    for ref in ("94:5", "94:7"):
        try:
            importer.quran_card(ref, arabic, turkish, NAMES)
        except (KeyError, ValueError):
            continue
        raise AssertionError(ref)


def test_hadith_archive_requires_publisher_version_and_document():
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp, hadith=archive(belge="kısaltılmış"))
        try:
            importer.hadith_archive(repo)
        except importer.SourceError:
            return
    raise AssertionError("eksik belge kabul edildi")


def test_hadith_card_cites_publisher_version_and_link():
    card = importer.hadith_card("10", archive())
    assert card["metin"] == "Hadis 10" and card["arapca"] == "حديث 10"
    assert card["kunye"] == "Sahih Hadis · Buhârî rivayet etmiştir"
    assert card["kaynak"] == "HadeethEnc.com · Nebevi Hadisler Ansiklopedisi Tercümesi v1.71.0 · hadeethenc.com/tr/browse/hadith/10"


def test_photo_verdict_accepts_only_free_unrestricted_jpeg_from_wikimedia():
    assert importer.photo_verdict(photo_info()) is None
    assert importer.photo_verdict(photo_info("pd", thumb="https://upload.wikimedia.org/x.jpg")) is None
    assert importer.photo_verdict(photo_info("cc-by-sa-4.0")) == "lisans"
    assert importer.photo_verdict(photo_info(restrictions="personality")) == "lisans"
    assert importer.photo_verdict(photo_info(mime="image/png")) == "bicim"
    assert importer.photo_verdict(photo_info(width=9000, height=1500)) == "bicim"
    assert importer.photo_verdict(photo_info(thumb="https://example.com/x.jpg")) == "adres"


def test_run_writes_three_cards_and_evidence(monkeypatch):
    patch_hashes(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        web = Web({t: photo_info() for t in ("File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg")})
        assert importer.run(repo, "2026-11-18", web, fake_render) == 0
        for path in importer.OUTPUTS.values():
            assert (repo / path).read_bytes().startswith(b"\xff\xd8")
        saved = state(repo)
        assert saved["son"]["tarih"] == "2026-11-18"
        cards = saved["son"]["kartlar"]
        assert [c["tur"] for c in cards] == ["ayet", "hadis", "dua"]
        assert len({c["fotograf"]["baslik"] for c in cards}) == 3
        assert all(c["fotograf"]["lisans"] == "cc0" and c["fotograf"]["yazar"] == "Ayşe" for c in cards)

        # Aynı gün yeniden çalışınca hiçbir şey indirilmez.
        again = Web({})
        assert importer.run(repo, "2026-11-18", again, fake_render) == 0
        assert again.fetched == []


def test_rotation_prefers_unused_then_oldest(monkeypatch):
    patch_hashes(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        web = Web({t: photo_info() for t in ("File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg")})
        importer.run(repo, "2026-11-18", web, fake_render)
        first = state(repo)["son"]["kartlar"]
        importer.run(repo, "2026-11-19", web, fake_render)
        second = state(repo)["son"]["kartlar"]
        assert first[0]["kayit"] != second[0]["kayit"]  # iki ayetten diğeri
        assert first[1]["kayit"] != second[1]["kayit"]  # iki hadisten diğeri
        assert first[2]["kayit"] != second[2]["kayit"]  # ayet duası ↔ hadis duası
        unused = {"File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg"} - {c["fotograf"]["baslik"] for c in first}
        assert unused <= {c["fotograf"]["baslik"] for c in second}


def test_license_change_is_excluded_permanently_and_skipped(monkeypatch):
    patch_hashes(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        web = Web({"File:A.jpg": photo_info("cc-by-sa-4.0"), "File:B.jpg": photo_info(), "File:C.jpg": photo_info(),
                   "File:D.jpg": photo_info()})
        assert importer.run(repo, "2026-11-18", web, fake_render) == 0
        saved = state(repo)
        assert saved["dislanan_fotograf"] == ["File:A.jpg"]
        assert "File:A.jpg" not in {c["fotograf"]["baslik"] for c in saved["son"]["kartlar"]}


def test_failure_leaves_previous_cards_untouched(monkeypatch):
    patch_hashes(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp, photos=("File:A.jpg", "File:B.jpg"))
        (repo / "Ayet").mkdir()
        (repo / importer.OUTPUTS["ayet"]).write_bytes(b"dun")
        web = Web({"File:A.jpg": photo_info(), "File:B.jpg": OSError("ağ")})
        assert importer.run(repo, "2026-11-18", web, fake_render) == 2
        assert (repo / importer.OUTPUTS["ayet"]).read_bytes() == b"dun"
        assert not (repo / importer.STATE_FILE).exists()



def test_render_failure_writes_nothing(monkeypatch):
    patch_hashes(monkeypatch)

    def broken_render(repo, specs):
        raise OSError("swift yok")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        web = Web({t: photo_info() for t in ("File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg")})
        assert importer.run(repo, "2026-11-18", web, broken_render) == 2
        assert not any((repo / p).exists() for p in importer.OUTPUTS.values())
        assert not (repo / importer.STATE_FILE).exists()


def test_wrong_quran_hash_is_rejected(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        web = Web({t: photo_info() for t in ("File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg")})
        assert importer.run(repo, "2026-11-18", web, fake_render) == 2  # Gerçek SHA-256 sahte dosyayla uyuşmaz.
        assert not any(url.startswith(importer.COMMONS_API) for url in web.fetched)
