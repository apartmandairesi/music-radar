"""
Her release için legal dinleme/preview linkleri arar:
- Bandcamp arama linki
- SoundCloud arama linki
- YouTube arama linki
- Spotify arama linki
- Beatport arama linki (preview için, 2 dakika)

Bu modül 'arama linki' üretir, direkt çalan link değil.
Çünkü doğru linki bulmak her platform için ayrı API entegrasyonu gerektirir
ve birçoğu rate-limited/auth gerektiriyor. Arama linki güvenli, hızlı ve
kullanıcı tek tıkla doğru sonuca ulaşır.

Eğer ileride bir platform için tam çözüm istenirse (örn. Spotify Web API
ile direkt track linki), bu modüle eklenir.
"""
from __future__ import annotations

import logging
from urllib.parse import quote_plus

from .sources import Release

log = logging.getLogger(__name__)


def _q(text: str) -> str:
    """URL query parametresi için escape."""
    return quote_plus(text.strip())


def build_listen_links(release: Release) -> dict[str, str]:
    """
    Release için dinleme/preview platformlarında arama linkleri üret.

    Sanatçı + release başlığını kullanır. Boş alanları sessizce atlar.
    """
    artist = release.artist.strip()
    title = release.release_title.strip()

    # Arama query'si: "Artist Title" en iyi sonucu verir
    parts = [p for p in [artist, title] if p]
    if not parts:
        return {}
    query = " ".join(parts)

    # Sadece sanatçı ile arama (release çok yeniyse platformlarda yoktur,
    # sanatçı sayfası bir fallback)
    artist_query = artist if artist else query

    links = {
        "Bandcamp": f"https://bandcamp.com/search?q={_q(query)}&item_type=t",
        "SoundCloud": f"https://soundcloud.com/search?q={_q(query)}",
        "YouTube": f"https://www.youtube.com/results?search_query={_q(query)}",
        "Spotify": f"https://open.spotify.com/search/{_q(query)}",
        "Beatport (preview)": f"https://www.beatport.com/search?q={_q(query)}",
    }

    return links


def enrich(releases: list[tuple[Release, list[str]]]) -> None:
    """Her eşleşen release için dinleme linklerini hesapla ve enrichment'a ekle."""
    for release, _reasons in releases:
        release.enrichment["listen"] = build_listen_links(release)
    log.info("%d release zenginleştirildi", len(releases))
