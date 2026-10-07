"""import_daily_info.py testleri: python3 -m pytest Tools/fecr-icerik"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_daily_info as importer  # noqa: E402

KUNYE_OK = '<p>Bu sitede "ajans kaynaklı haberler" hariç diğer haberlerin AKTİF LİNK kaynak belirtilerek kullanılması serbesttir.</p>'
BODY = "Özgün paragraf bir. " * 15 + "\r\n\r\n\r\nİkinci paragraf. " * 5


def page(title="Başlık", body=None, section="Dini kavramlar", publisher="Diyanet Haber", source_name=None):
    body = body if body is not None else BODY + f" ({title})"
    news = {"@type": "NewsArticle", "headline": title, "articleBody": body, "articleSection": section,
            "datePublished": "2022-11-05T16:35:38+03:00",
            "publisher": {"name": publisher}, "creator": {"name": "Diyanet Haber"}}
    agency = f'<span class="source-name">{source_name}</span>' if source_name else ""
    return (f'<script type="application/ld+json">{json.dumps(news)}</script>'
            f'<div class="article-source py-3 small ">{agency}</div>')


def rss(*slugs):
    items = "".join(f"<item><link>https://www.diyanethaber.com.tr/{slug}</link></item>" for slug in slugs)
    return f"<rss><channel><title>x</title><link>https://www.diyanethaber.com.tr</link>{items}</channel></rss>"


class Site:
    def __init__(self, feeds, pages, kunye=KUNYE_OK):
        self.feeds, self.pages, self.kunye = feeds, pages, kunye
        self.fetched = []

    def __call__(self, url):
        self.fetched.append(url)
        if url == importer.KUNYE:
            return self.kunye
        match = re.fullmatch(r"https://www\.diyanethaber\.com\.tr/rss/(.+)", url)
        if match:
            return self.feeds.get(match.group(1), rss())
        if url in self.pages:
            return self.pages[url]
        raise OSError(url)


def url(slug):
    return f"{importer.HOST}/{slug}"


def site(**override):
    pages = {url("kavram-1"): page("Kavram 1"), url("kavram-2"): page("Kavram 2"),
             url("hikaye-1"): page("Hikâye 1", section="Bir Hikaye"),
             url("hikaye-2"): page("Hikâye 2", section="Sahabeler")}
    feeds = {"dini-kavramlar": rss("kavram-1", "kavram-2"), "bir-hikaye": rss("hikaye-1"), "sahabeler": rss("hikaye-2")}
    pages.update(override.get("pages", {}))
    feeds.update(override.get("feeds", {}))
    return Site(feeds, pages)


def read(repo):
    return json.loads((repo / importer.INFO_FILE).read_text(encoding="utf-8"))


def assert_app_accepts(payload, today):
    """InfoArchive.init(data:)'nın v2 kurallarının aynası."""
    assert payload["schema_version"] == 2 and payload["yayin_tarihi"] == today
    assert payload["lisans"].strip() and payload["kaynak"].strip()
    entries = payload["bilgiler"]
    assert [e["tur"] for e in entries] == ["bilgi", "hikaye"]
    assert len({e["kaynak_url"] for e in entries}) == 2
    for e in entries:
        assert all(e[k].strip() for k in ("baslik", "metin", "kaynak"))
        assert re.fullmatch(r"https://www\.diyanethaber\.com\.tr/[a-z0-9-]+", e["kaynak_url"])


def test_publishes_valid_pair_and_cleans_body():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        assert importer.run(repo, "2026-10-08", site()) == 0
        payload = read(repo)
        assert_app_accepts(payload, "2026-10-08")
        assert "\r" not in payload["bilgiler"][0]["metin"] and "\n\n\n" not in payload["bilgiler"][0]["metin"]
        assert payload["bilgiler"][1]["kaynak"] == "Diyanet Haber, 5 Kasım 2022"


def test_same_day_is_idempotent_and_makes_no_requests():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        importer.run(repo, "2026-10-08", site())
        before = (repo / importer.INFO_FILE).read_bytes()
        second = site()
        assert importer.run(repo, "2026-10-08", second) == 0
        assert second.fetched == [] and (repo / importer.INFO_FILE).read_bytes() == before


def test_next_day_never_repeats_url_or_text():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        importer.run(repo, "2026-10-08", site())
        first = {e["kaynak_url"] for e in read(repo)["bilgiler"]}
        assert importer.run(repo, "2026-10-09", site()) == 0
        assert not first & {e["kaynak_url"] for e in read(repo)["bilgiler"]}


def test_exhausted_pool_keeps_previous_pair():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        importer.run(repo, "2026-10-08", site())
        importer.run(repo, "2026-10-09", site())
        before = (repo / importer.INFO_FILE).read_bytes()
        assert importer.run(repo, "2026-10-10", site()) == 2
        assert (repo / importer.INFO_FILE).read_bytes() == before and read(repo)["yayin_tarihi"] == "2026-10-09"


def test_rejects_agency_foreign_publisher_and_short_text():
    bad = {url("kavram-1"): page("A", source_name="AA"), url("kavram-2"): page("B", publisher="Başka Site"),
           url("kavram-3"): page(body="Kısa."), url("kavram-4"): page("İyi")}
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        s = site(pages=bad, feeds={"dini-kavramlar": rss("kavram-1", "kavram-2", "kavram-3", "kavram-4")})
        assert importer.run(repo, "2026-10-08", s) == 0
        assert read(repo)["bilgiler"][0]["kaynak_url"] == url("kavram-4")


def test_incomplete_pair_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        s = site(feeds={"bir-hikaye": rss(), "sahabeler": rss()})
        assert importer.run(repo, "2026-10-08", s) == 2
        assert not (repo / importer.INFO_FILE).exists() and not (repo / importer.STATE_FILE).exists()


def test_missing_kunye_permission_blocks_publishing():
    with tempfile.TemporaryDirectory() as tmp:
        s = site()
        s.kunye = "<p>İzin metni yok</p>"
        assert importer.run(Path(tmp), "2026-10-08", s) == 3
        assert not (Path(tmp) / importer.INFO_FILE).exists()


def test_same_article_in_both_feeds_is_not_used_twice():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        s = site(feeds={"dini-kavramlar": rss("hikaye-1"), "bir-hikaye": rss("hikaye-1", "hikaye-2")})
        assert importer.run(repo, "2026-10-08", s) == 0
        assert_app_accepts(read(repo), "2026-10-08")


def test_canonical_url_rules_match_app():
    assert importer.canonical("https://www.diyanethaber.com.tr/yazi-1") == url("yazi-1")
    for bad in ("http://www.diyanethaber.com.tr/a", "https://evil.com/a", "https://www.diyanethaber.com.tr/a?x=1",
                "https://www.diyanethaber.com.tr/", "https://www.diyanethaber.com.tr/a/b"):
        assert importer.canonical(bad) is None
