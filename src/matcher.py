"""
Release listesini takip edilen sanatçı/label listesi ile filtreler.

Eşleştirme stratejisi: büyük/küçük harf duyarsız, KELİME SINIRI EŞLEŞMESİ.
"Ede" listesindeki sanatçı "Ede - Track" yakalar ama "Dedeman" değil.

Tek karakterli isimler veya sayılarla başlayan "isimler" özel davranır:
- "12 BPM" gibi gürültü isimleri sadece tam başa eşleşir
- Normal isimler word-boundary ile eşleşir
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .sources import Release

log = logging.getLogger(__name__)


@dataclass
class Watchlist:
    artists: list[str]
    labels: list[str]
    soundcloud_users: list[str]


def _read_list(path: Path) -> list[str]:
    if not path.exists():
        log.warning("%s yok, boş liste döndürülüyor", path)
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def load_watchlist(config_dir: Path) -> Watchlist:
    return Watchlist(
        artists=_read_list(config_dir / "artists.txt"),
        labels=_read_list(config_dir / "labels.txt"),
        soundcloud_users=_read_list(config_dir / "soundcloud.txt"),
    )


def _make_pattern(name: str) -> re.Pattern:
    """
    Kelime sınırlı, case-insensitive regex pattern üretir.

    "Ede" → r"(?<![\w&])Ede(?![\w])" → "Ede - Track" yakalar, "Dedeman" yakalamaz.
    Özel karakterleri (& gibi) escape eder.

    Negatif lookbehind/lookahead'de \w kullanarak harf+rakam+_ engellenir;
    & gibi karakterler ile birleşik isimler için (&ME) başlangıçta & de izinli sayılır.
    """
    escaped = re.escape(name)
    # Sol sınır: önce harf/rakam OLMAMALI ama & olabilir (örn. "feat. &ME")
    # Sağ sınır: sonra harf/rakam OLMAMALI
    pattern = r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])"
    return re.compile(pattern, re.IGNORECASE)


# Watchlist büyük olabilir (~2000 isim). Pattern'ları cache'leyelim.
_pattern_cache: dict[str, re.Pattern] = {}


def _get_pattern(name: str) -> re.Pattern:
    if name not in _pattern_cache:
        _pattern_cache[name] = _make_pattern(name)
    return _pattern_cache[name]


def match_release(release: Release, wl: Watchlist) -> tuple[bool, list[str]]:
    """Release watchlist'teki herhangi bir şeyle eşleşiyor mu?"""
    reasons: list[str] = []

    # SoundCloud release'leri zaten takip listesinden geldi
    if release.source.startswith("soundcloud:"):
        username = release.source.split(":", 1)[1]
        reasons.append(f"soundcloud:{username}")
        return True, reasons

    # Sanatçı/title/raw_summary'de sanatçı ismi ara (kelime sınırlı)
    artist_blob = " | ".join([
        release.artist,
        release.release_title,
        release.title,
        release.raw_summary,
    ])

    for artist_name in wl.artists:
        # Çok kısa isimleri (1-2 karakter) atla - false positive cenneti
        if len(artist_name) < 4:
            continue
        if _get_pattern(artist_name).search(artist_blob):
            reasons.append(f"artist:{artist_name}")

    # Label sadece label/title alanlarında, kelime sınırlı
    label_blob = f"{release.label} | {release.title}"
    for label_name in wl.labels:
        if len(label_name) < 4:
            continue
        if _get_pattern(label_name).search(label_blob):
            reasons.append(f"label:{label_name}")

    return (len(reasons) > 0, reasons)


def filter_matches(releases: list[Release], wl: Watchlist) -> list[tuple[Release, list[str]]]:
    out: list[tuple[Release, list[str]]] = []
    for r in releases:
        ok, reasons = match_release(r, wl)
        if ok:
            out.append((r, reasons))
    log.info("Eşleşen release: %d / %d", len(out), len(releases))
    return out
