"""
Release blog'larından ve SoundCloud'dan release verilerini çeker.

Mimari:
- edmwaves için özel HTML parser (RSS yetersiz, label HTML'de)
- Diğer siteler için RSS + cloudscraper fallback (Cloudflare 403'leri için)
- SoundCloud için HTML scraping (RSS public değil)

Parser stratejisi (_parse_meta):
- HTML'i BS4 ile metne çevir (separator="\n" sayesinde <br>, </p>, ve düz newline
  hepsi tek bir \n haline gelir)
- Her satırda "Artist: ...", "Label: ..." vs. ara
Bu yaklaşım WordPress'in tüm yaygın çıktı varyantlarını handle eder.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

# Cloudflare bypass - opsiyonel, kuruluysa kullan
try:
    import cloudscraper
    _scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "mobile": False})
    HAS_CLOUDSCRAPER = True
except ImportError:
    _scraper = None
    HAS_CLOUDSCRAPER = False

BLOG_FEEDS = {
    "jkmk": "https://jkmk.net/feed/",
    "elektrobeats": "https://elektrobeats.org/feed/",
    "electrobuzz": "https://www.electrobuzz.net/feed/",
    "themusicfire": "https://themusicfire.net/feed/",
}

# edmwaves özel - HTML ana sayfa (RSS'te label boş geliyor)
EDMWAVES_HTML = "https://edmwaves.org/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 25


@dataclass
class Release:
    source: str
    title: str
    url: str
    published: datetime
    artist: str = ""
    release_title: str = ""
    label: str = ""
    genre: str = ""
    raw_summary: str = ""
    enrichment: dict = field(default_factory=dict)

    def unique_id(self) -> str:
        return self.url


def _fetch(url: str, max_retries: int = 2) -> str | None:
    """Standart requests + cloudscraper fallback (Cloudflare 403 için)."""
    user_agents = [
        HEADERS["User-Agent"],
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    last_status = None
    for attempt in range(max_retries + 1):
        try:
            headers = {**HEADERS, "User-Agent": user_agents[attempt % len(user_agents)]}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            last_status = r.status_code
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503) and attempt < max_retries:
                log.info("Fetch %s status=%s, retry %d/%d", url, r.status_code, attempt + 1, max_retries)
                continue
            break
        except requests.RequestException as e:
            log.warning("Fetch %s hata: %s", url, e)

    if last_status in (403, 503) and HAS_CLOUDSCRAPER and _scraper is not None:
        try:
            log.info("Fetch %s: cloudscraper deneniyor (Cloudflare bypass)", url)
            r = _scraper.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                log.info("Fetch %s: cloudscraper basardi", url)
                return r.text
            log.warning("Fetch %s: cloudscraper status=%s", url, r.status_code)
        except Exception as e:
            log.warning("Fetch %s: cloudscraper hata: %s", url, e)

    log.warning("Fetch %s döndü status=%s (tüm denemeler başarısız)", url, last_status)
    return None


# Satır bazında Artist:/Title:/Label:/Genre:/Quality: yakalar
_FIELD_LINE_RE = re.compile(
    r"^\s*(Artist|Title|Label|Genre|Quality)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _parse_meta(text: str) -> dict[str, str]:
    """
    Artist/Title/Label/Genre alanlarını çıkar.

    HTML ise önce BS4 ile düz metne çevir; BS4'in separator="\n" davranışı sayesinde
    <br>, </p>, ve düz \n separator'larının hepsi tek bir \n olur. Ardından satır
    satır regex ile yakala. WordPress'in tüm yaygın çıktı varyantlarını handle eder.
    """
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(separator="\n", strip=True)

    meta: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _FIELD_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1).lower()
        val = m.group(2).strip()
        # Yan etkiyi önlemek için boşları ve "Quality" değerini meta'ya kaydetme
        if not val:
            continue
        # Aynı key birden fazla satırda görünürse ilkini al
        if key in meta:
            continue
        meta[key] = val
    return meta


def _clean_text(text: str) -> str:
    """HTML'i temiz metne çevir."""
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_title_fallback(title: str) -> tuple[str, str]:
    """meta yoksa başlığı 'Artist - Title' olarak böl."""
    for sep in (" – ", " — ", " - "):
        if sep in title:
            artist, rest = title.split(sep, 1)
            return artist.strip(), rest.strip()
    return "", title.strip()


def _build_release(source: str, title: str, url: str, published: datetime, summary: str) -> Release:
    title = _clean_text(title)
    summary_clean = _clean_text(summary) if summary else ""
    meta = _parse_meta(summary)

    artist = meta.get("artist", "")
    release_title = meta.get("title", "")
    label = meta.get("label", "")
    genre = meta.get("genre", "")

    # Quality satır parser'ında filtrelenmedi diye buradan da temizleyelim
    if release_title.lower() == "quality":
        release_title = ""

    if not artist or not release_title:
        a_fb, t_fb = _parse_title_fallback(title)
        artist = artist or a_fb
        release_title = release_title or t_fb

    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    return Release(
        source=source, title=title, url=url, published=published,
        artist=artist, release_title=release_title,
        label=label, genre=genre, raw_summary=summary_clean[:500],
    )


def _fetch_edmwaves_html() -> list[Release]:
    """edmwaves'i HTML olarak çek - RSS'te label yok, HTML'de var."""
    html = _fetch(EDMWAVES_HTML)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    releases: list[Release] = []

    articles = soup.find_all("article")
    if not articles:
        log.warning("edmwaves HTML: <article> bulunamadı, HTML yapısı değişmiş olabilir")
        return []

    for art in articles:
        # Başlık ve link
        h = art.find(["h1", "h2", "h3"])
        if not h:
            continue
        a = h.find("a", href=True)
        if not a:
            continue

        title = a.get_text(strip=True)
        link = a["href"]

        # Tarih
        published_dt = None
        time_tag = art.find("time", datetime=True)
        if time_tag:
            try:
                published_dt = dateparser.parse(time_tag["datetime"])
            except (ValueError, TypeError):
                pass
        if not published_dt:
            url_date = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", link)
            if url_date:
                published_dt = datetime(
                    int(url_date.group(1)), int(url_date.group(2)), int(url_date.group(3)),
                    tzinfo=timezone.utc,
                )
        if not published_dt:
            published_dt = datetime.now(timezone.utc)

        article_html = str(art)
        releases.append(_build_release("edmwaves", title, link, published_dt, article_html))

    log.info("edmwaves HTML: %d release", len(releases))
    return releases


def _fetch_rss(source_name: str, feed_url: str) -> list[Release]:
    """Standart RSS feed parser (jkmk, elektrobeats, electrobuzz, themusicfire için)."""
    content = _fetch(feed_url)
    if not content:
        return []

    parsed = feedparser.parse(content)
    releases: list[Release] = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        published_dt = None
        for k in ("published", "updated", "created"):
            if entry.get(k):
                try:
                    published_dt = dateparser.parse(entry[k])
                    break
                except (ValueError, TypeError):
                    continue
        if not published_dt:
            published_dt = datetime.now(timezone.utc)

        # RSS'te genelde content:encoded daha zengindir
        summary = ""
        if entry.get("content"):
            try:
                summary = entry["content"][0].get("value", "")
            except (IndexError, AttributeError, TypeError):
                pass
        if not summary:
            summary = entry.get("summary", "") or entry.get("description", "")

        releases.append(_build_release(source_name, title, link, published_dt, summary))

    log.info("%s RSS: %d release", source_name, len(releases))
    return releases


def fetch_blog_releases() -> list[Release]:
    releases: list[Release] = []
    log.info("Fetching edmwaves (HTML) ...")
    releases.extend(_fetch_edmwaves_html())
    for source_name, feed_url in BLOG_FEEDS.items():
        log.info("Fetching %s ...", source_name)
        releases.extend(_fetch_rss(source_name, feed_url))

    log.info("Toplam blog release: %d", len(releases))
    return releases


def fetch_soundcloud_releases(usernames: Iterable[str]) -> list[Release]:
    releases: list[Release] = []
    for username in usernames:
        username = username.strip()
        if not username or username.startswith("#"):
            continue

        url = f"https://soundcloud.com/{username}/tracks"
        log.info("Fetching SoundCloud %s ...", username)
        html = _fetch(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        seen_links = set()
        user_count = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith(f"/{username}/"):
                continue
            if any(x in href for x in ("/tracks", "/sets", "/reposts", "/likes", "/followers", "/following")):
                continue
            slug = href.split("/")[-1].split("?")[0]
            if not slug or slug == username:
                continue
            full_url = f"https://soundcloud.com{href}"
            if full_url in seen_links:
                continue
            seen_links.add(full_url)

            title = (a.get("title") or a.get_text(strip=True) or slug.replace("-", " ")).strip()
            if not title:
                continue

            releases.append(Release(
                source=f"soundcloud:{username}",
                title=title, url=full_url,
                published=datetime.now(timezone.utc),
                artist=username, release_title=title,
            ))
            user_count += 1
            if user_count >= 15:
                break

    log.info("Toplam SoundCloud release: %d", len(releases))
    return releases
