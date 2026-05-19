"""
Hangi release'leri daha önce raporladığımızı kalıcı olarak saklar.

Format: data/seen.json
  {
    "<url>": {
      "first_seen": "2026-01-15T10:30:00+00:00",
      "title": "Artist - Title"
    },
    ...
  }

URL'i key olarak kullanıyoruz çünkü en güvenilir tekil tanımlayıcı.
Aynı release birden çok blogda çıkarsa farklı URL'lerle gelir; bu durumda
ikisi de raporlanır (kullanıcı için bilgi: hangi blog'da var).

Sınırlama: seen.json sonsuza dek büyür. Yılda bir manuel temizlik veya
180+ gün öncesi kayıtları otomatik silmek için aşağıda prune() var.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sources import Release

log = logging.getLogger(__name__)


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            log.info("%s yok, boş state ile başlanıyor", self.path)
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            log.info("State yüklendi: %d kayıt", len(self._data))
        except json.JSONDecodeError as e:
            log.error("seen.json bozuk: %s - boş state ile devam", e)
            self._data = {}

    def is_seen(self, release: Release) -> bool:
        return release.unique_id() in self._data

    def mark_seen(self, release: Release) -> None:
        self._data[release.unique_id()] = {
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "title": release.title[:200],
        }

    def prune(self, max_age_days: int = 180) -> int:
        """Eski kayıtları temizle. Kaç adet silindi döner."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        to_remove = []
        for url, meta in self._data.items():
            try:
                seen_at = datetime.fromisoformat(meta["first_seen"])
                if seen_at < cutoff:
                    to_remove.append(url)
            except (KeyError, ValueError):
                continue
        for url in to_remove:
            del self._data[url]
        if to_remove:
            log.info("%d eski kayıt silindi", len(to_remove))
        return len(to_remove)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        log.info("State kaydedildi: %d kayıt", len(self._data))
