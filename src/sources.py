"""
Release blog'larından ve SoundCloud'dan release verilerini çeker.

Tüm 5 site WordPress üzerinde çalışıyor, dolayısıyla /feed/ endpoint'i
ile RSS olarak çekilebilir. Bu HTML scraping'den çok daha güvenilir.

SoundCloud her kullanıcı için /USERNAME/tracks adresinden RSS sunuyor:
soundcloud.com/USERNAME/tracks → feeds.soundcloud.com/users/soundcloud:users:ID/sounds.rss
Ancak ID'yi bulmak için bir round trip gerekiyor. Basitlik için
HTML'den son release'leri parse ediyoruz.
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

# Verilen 5 site - hepsi WordPress
BLOG_FEEDS = {
    "jkmk": "https://jkmk.net/feed/",
    "elektrobeats": "https://elektrobeats.org/feed/",
    "edmwaves": "https://edmwaves.org/feed/",
    "electrobuzz": "https://www.electrobuzz.net/feed/",
    "themusicfire": "https://themusicfire.net/feed/",
}

# Bazı siteler bot user-agent'larını bloklar; gerçek tarayıcı taklit edelim
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 20


@dataclass
class Release:
    """Tek bir release kaydı."""
    source: str                    # 'edmwaves', 'soundcloud:afterlifeofc' vs.
    title: str                     # Tam başlık: "Artist - Title [Cat#]"
    url: str                       # Release sayfası URL'i
    published: datetime            # Yayın tarihi (UTC)
    artist: str = ""               # Parse edilen sanatçı
    release_title: str = ""        # Parse edilen release başlığı (sanatçı hariç)
    label: str = ""                # Parse edilen label
    genre: str = ""                # Parse edilen genre
    raw_summary: str = ""          # Özet/açıklama (parse için)
    enrichment: dict = field(default_factory=dict)  # Bandcamp/SC/YT linkleri buraya

    def unique_id(self) -> str:
        """seen.json için tekil key. URL en güvenilir."""
        return self.url


def _fetch(url: str, max_retries: int = 2) -> str | None:
    """
    URL'i GET et, başarısız olursa None döndür.

    Bazı siteler bot trafiğini sınırlıyor (özellikle Cloudflare arkasındakiler).
    Retry stratejisi: 403/429/503 alırsak farklı user-agent ile tekrar dene.
    """
    user_agents = [
        HEADERS["User-Agent"],
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    ]

    for attempt in range(max_retries + 1):
        try:
            headers = {**HEADERS, "User-Agent": user_agents[attempt % len(user_agents)]}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503) and attempt < max_retries:
                log.info("Fetch %s status=%s, retry %d/%d", url, r.status_code, attempt + 1, max_retries)
                continue
            log.warning("Fetch %s döndü status=%s (deneme %d)", url, r.status_code, attempt + 1)
            return None
        except requests.RequestException as e:
            log.warning("Fetch %s hata: %s", url, e)
            if attempt >= max_retries:
                return None
    return None


# Release blog'larında genelde şu desen var (edmwaves.org örnek):
#   Artist: yehno
#   Title: Distant EP [ANJEXP088D]
#   Label: Anjunadeep Explorations
#   Genre: Breaks
_FIELD_RE = re.compile(
    r"(?:^|\n)\s*(Artist|Title|Label|Genre|Quality)\s*:\s*(.+?)(?=\n\s*[A-Z]\w+\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_meta(text: str) -> dict[str, str]:
    """Özet/içerik metninden Artist/Title/Label/Genre alanlarını çıkar."""
    meta: dict[str, str] = {}
    for m in _FIELD_RE.finditer(text):
        key = m.group(1).lower()
        val = m.group(2).strip().split("\n")[0].strip()
        meta[key] = val
    return meta


def _parse_title_fallback(title: str) -> tuple[str, str]:
    """
    Başlıktan sanatçı/release ayırmak için fallback.
    Tipik format: "Artist – Release Title [Cat#]" veya "Artist - Title"
    """
    # En dash, em dash, hyphen
    for sep in (" – ", " — ", " - "):
        if sep in title:
            artist, rest = title.split(sep, 1)
            return artist.strip(), rest.strip()
    return "", title.strip()


def fetch_blog_releases() -> list[Release]:
    """5 release blog'unun RSS feed'lerini çek, Release listesine dönüştür."""
    releases: list[Release] = []

    for source_name, feed_url in BLOG_FEEDS.items():
        log.info("Fetching %s ...", source_name)
        content = _fetch(feed_url)
        if not content:
            log.warning("%s erişilemedi, atlanıyor", source_name)
            continue

        parsed = feedparser.parse(content)
        if parsed.bozo:
            log.warning("%s feed bozuk olabilir: %s", source_name, parsed.bozo_exception)

        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # Yayın tarihini parse et
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
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)

            # Özet/içerikten metayı çıkarmaya çalış
            summary = entry.get("summary", "") or entry.get("description", "")
            # HTML temizle
            if summary:
                summary = BeautifulSoup(summary, "html.parser").get_text("\n")

            meta = _parse_meta(summary)

            artist = meta.get("artist", "")
            release_title = meta.get("title", "")
            label = meta.get("label", "")
            genre = meta.get("genre", "")

            # Meta'dan çıkmadıysa başlıktan fallback
            if not artist or not release_title:
                a_fb, t_fb = _parse_title_fallback(title)
                artist = artist or a_fb
                release_title = release_title or t_fb

            releases.append(Release(
                source=source_name,
                title=title,
                url=link,
                published=published_dt,
                artist=artist,
                release_title=release_title,
                label=label,
                genre=genre,
                raw_summary=summary[:500],
            ))

    log.info("Toplam blog release: %d", len(releases))
    return releases


def fetch_soundcloud_releases(usernames: Iterable[str]) -> list[Release]:
    """
    SoundCloud kullanıcı sayfasından son track'leri çek.
    Public RSS yok diye HTML scraping yapıyoruz, biraz kırılgan ama çalışıyor.
    """
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

        # SoundCloud sayfasında <article> içinde track linkleri var
        # ama daha güvenilir yöntem: <meta property="og:..."> ve <script> içindeki JSON
        soup = BeautifulSoup(html, "html.parser")

        # Track linkleri /username/track-slug formatında
        seen_links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith(f"/{username}/"):
                continue
            # Filtreler: /tracks, /sets, /reposts gibi alt sayfaları atla
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

            # SoundCloud'da yayın tarihi HTML'de net görünmüyor; "yeni" tespitini
            # seen.json üzerinden yapacağız, tarih olarak şimdiyi koyalım
            releases.append(Release(
                source=f"soundcloud:{username}",
                title=title,
                url=full_url,
                published=datetime.now(timezone.utc),
                artist=username,
                release_title=title,
            ))

            # Sayfa başına ilk 15 track yeterli
            if len([r for r in releases if r.source == f"soundcloud:{username}"]) >= 15:
                break

    log.info("Toplam SoundCloud release: %d", len(releases))
    return releases
