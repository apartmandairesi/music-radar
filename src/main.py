"""
Music Radar - ana orkestratör.

Sıra:
  1. Watchlist'i yükle (artists.txt, labels.txt, soundcloud.txt)
  2. 5 blog'tan release'leri çek
  3. SoundCloud kullanıcılarından track'leri çek
  4. Tarih filtresi (LOOKBACK_DAYS - varsayılan 14 gün)
  5. Watchlist ile eşleştir
  6. seen.json'da olmayanları seç (= yeni)
  7. Dinleme linklerini ekle
  8. Mail at
  9. seen.json'u güncelle (workflow git commit eder)

Çevre değişkenleri:
  LOOKBACK_DAYS: kaç gün geriye bakılsın (varsayılan 14)
  Mail gönderimi için mailer.py'ye bak.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .enricher import enrich
from .mailer import send_mail
from .matcher import filter_matches, load_watchlist
from .sources import fetch_blog_releases, fetch_soundcloud_releases
from .state import SeenStore


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("music_radar")

    project_root = Path(__file__).resolve().parent.parent
    config_dir = project_root / "config"
    state_path = project_root / "data" / "seen.json"

    lookback_days = int(os.environ.get("LOOKBACK_DAYS", "14"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    log.info("Lookback: %d gün (cutoff %s)", lookback_days, cutoff.isoformat())

    # 1) Watchlist
    wl = load_watchlist(config_dir)
    log.info(
        "Watchlist: %d sanatçı, %d label, %d SoundCloud kullanıcısı",
        len(wl.artists), len(wl.labels), len(wl.soundcloud_users),
    )

    if not (wl.artists or wl.labels or wl.soundcloud_users):
        log.warning("Watchlist tamamen boş! config/ klasöründeki dosyaları doldur.")
        # Yine de devam et - boş rapor gelsin ki kullanıcı setup'ın çalıştığını görsün

    # 2-3) Veri çek
    all_releases = []
    all_releases.extend(fetch_blog_releases())
    all_releases.extend(fetch_soundcloud_releases(wl.soundcloud_users))

    # 4) Tarih filtresi - sadece son N gün
    recent = [r for r in all_releases if r.published >= cutoff]
    log.info("Tarih filtresi sonrası: %d / %d", len(recent), len(all_releases))

    # 5) Watchlist ile eşleştir
    matches = filter_matches(recent, wl)

    # 6) seen.json'da olmayanlar
    state = SeenStore(state_path)
    new_matches = [(r, reasons) for r, reasons in matches if not state.is_seen(r)]
    log.info("Yeni (daha önce raporlanmamış): %d / %d", len(new_matches), len(matches))

    # 7) Dinleme linkleri
    enrich(new_matches)

    # 8) Mail at
    mail_ok = send_mail(new_matches)
    if not mail_ok:
        log.error("Mail başarısız! seen.json güncellenmeyecek - kullanıcı yine raporu alsın.")
        return 1

    # 9) State güncelle
    for r, _ in new_matches:
        state.mark_seen(r)
    state.prune(max_age_days=180)
    state.save()

    log.info("Tamamlandı. %d yeni release raporlandı.", len(new_matches))
    return 0


if __name__ == "__main__":
    sys.exit(main())
