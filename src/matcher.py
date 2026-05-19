"""
Release listesini takip edilen sanatçı/label listesi ile filtreler.

Eşleştirme stratejisi: büyük/küçük harf duyarsız, kısmi (substring) eşleşme.
'Tale Of Us' kaydı 'Tale Of Us & Mind Against' bir release'i de yakalar.
Bu agresif ama bu domain'de doğru — sanatçılar sık sık birbirleriyle
veya remix'lerde geçer ve kullanıcı bunları kaçırmak istemez.
"""
from __future__ import annotations

import logging
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
    """Yorum satırlarını ve boşları atla, geri kalanı stripped olarak dön."""
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


def _ci_contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring kontrolü."""
    return needle.lower() in haystack.lower()


def match_release(release: Release, wl: Watchlist) -> tuple[bool, list[str]]:
    """
    Release watchlist'teki herhangi bir şeyle eşleşiyor mu?

    Returns:
        (matched, reasons) - reasons örnek: ["artist:Tale Of Us", "label:Afterlife"]
    """
    reasons: list[str] = []

    # SoundCloud kaynaklı release'ler zaten takip listesindeki bir
    # kullanıcıdan geldi, otomatik dahil
    if release.source.startswith("soundcloud:"):
        username = release.source.split(":", 1)[1]
        reasons.append(f"soundcloud:{username}")
        return True, reasons

    # Aranan alanlar: artist, release_title, label, başlığın tamamı
    search_blob = " | ".join([
        release.artist,
        release.release_title,
        release.label,
        release.title,
        release.raw_summary,
    ])

    for artist_name in wl.artists:
        if _ci_contains(search_blob, artist_name):
            reasons.append(f"artist:{artist_name}")

    for label_name in wl.labels:
        # Label eşleştirmesi biraz daha sıkı - sadece label/title alanlarında ara
        # Çünkü "Afterlife" sanatçı ismi olarak da geçebilir
        label_blob = f"{release.label} | {release.title}"
        if _ci_contains(label_blob, label_name):
            reasons.append(f"label:{label_name}")

    return (len(reasons) > 0, reasons)


def filter_matches(releases: list[Release], wl: Watchlist) -> list[tuple[Release, list[str]]]:
    """Tüm release'leri tara, eşleşenleri (release, reasons) tuple'ları olarak dön."""
    out: list[tuple[Release, list[str]]] = []
    for r in releases:
        ok, reasons = match_release(r, wl)
        if ok:
            out.append((r, reasons))
    log.info("Eşleşen release: %d / %d", len(out), len(releases))
    return out
