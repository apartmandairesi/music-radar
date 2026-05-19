"""
Yeni release'lerin HTML mail'ini oluşturur ve SMTP üzerinden gönderir.

Gmail için: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=your@gmail.com,
SMTP_PASS=<App Password> (normal şifre değil! Google → Security → 2FA →
App Passwords kısmından üretilir.)
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape

from .sources import Release

log = logging.getLogger(__name__)


def _render_html(matches: list[tuple[Release, list[str]]]) -> str:
    """Eşleşen release'lerden HTML rapor üret."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    count = len(matches)

    head = f"""\
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Music Radar - {count} yeni release</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #fafafa; color: #222; padding: 24px; }}
  .container {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .release {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 8px; padding: 16px; margin-bottom: 14px; }}
  .release h2 {{ font-size: 16px; margin: 0 0 6px 0; }}
  .release h2 a {{ color: #111; text-decoration: none; }}
  .release h2 a:hover {{ text-decoration: underline; }}
  .fields {{ font-size: 13px; color: #555; margin: 4px 0; }}
  .fields strong {{ color: #333; }}
  .reasons {{ font-size: 12px; color: #888; margin-top: 6px; }}
  .reasons .tag {{ display: inline-block; background: #eef; color: #335; padding: 2px 6px; border-radius: 3px; margin-right: 4px; }}
  .listen {{ margin-top: 10px; font-size: 13px; }}
  .listen a {{ display: inline-block; padding: 4px 10px; background: #f0f0f0; color: #333; text-decoration: none; border-radius: 4px; margin: 2px 4px 2px 0; font-size: 12px; }}
  .listen a:hover {{ background: #e0e0e0; }}
  .empty {{ text-align: center; color: #888; padding: 40px; }}
</style>
</head>
<body><div class="container">
<h1>🎧 Music Radar — {count} yeni release</h1>
<div class="meta">Tarama zamanı: {now}</div>
"""

    if count == 0:
        return head + '<div class="empty">Bu seferki taramada watchlist\'inle eşleşen yeni release yok.</div></div></body></html>'

    body_parts = []
    for release, reasons in matches:
        title = escape(release.title)
        url = escape(release.url)
        source = escape(release.source)
        artist = escape(release.artist) if release.artist else "—"
        rel_title = escape(release.release_title) if release.release_title else "—"
        label = escape(release.label) if release.label else "—"
        genre = escape(release.genre) if release.genre else "—"
        pub = release.published.strftime("%Y-%m-%d")

        reason_tags = "".join(f'<span class="tag">{escape(r)}</span>' for r in reasons)

        listen_html = ""
        listen_links = release.enrichment.get("listen", {})
        if listen_links:
            link_anchors = "".join(
                f'<a href="{escape(u)}" target="_blank" rel="noopener">{escape(name)}</a>'
                for name, u in listen_links.items()
            )
            listen_html = f'<div class="listen">{link_anchors}</div>'

        body_parts.append(f"""\
<div class="release">
  <h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>
  <div class="fields"><strong>Artist:</strong> {artist} &nbsp;·&nbsp; <strong>Title:</strong> {rel_title}</div>
  <div class="fields"><strong>Label:</strong> {label} &nbsp;·&nbsp; <strong>Genre:</strong> {genre} &nbsp;·&nbsp; <strong>Source:</strong> {source} &nbsp;·&nbsp; <strong>Date:</strong> {pub}</div>
  <div class="reasons">Eşleşme: {reason_tags}</div>
  {listen_html}
</div>
""")

    tail = "</div></body></html>"
    return head + "".join(body_parts) + tail


def send_mail(matches: list[tuple[Release, list[str]]]) -> bool:
    """
    Eşleşen release'leri mail at. Eşleşme yoksa yine "boş rapor" gönderir
    (kullanıcı script'in çalıştığından emin olsun diye).

    Returns: True başarılı, False başarısız.
    """
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    mail_to = os.environ.get("MAIL_TO")
    mail_from = os.environ.get("MAIL_FROM") or user

    if not all([host, user, password, mail_to, mail_from]):
        log.error("SMTP env değişkenleri eksik. Mail gönderilmedi.")
        log.error("Gerekli: SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO, MAIL_FROM")
        return False

    html = _render_html(matches)
    count = len(matches)

    msg = EmailMessage()
    msg["Subject"] = f"🎧 Music Radar — {count} yeni release"
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(
        f"{count} yeni release bulundu. HTML versiyonu için mail istemcinizi kullanın."
    )
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        log.info("Mail başarıyla gönderildi: %s", mail_to)
        return True
    except Exception as e:
        log.exception("Mail gönderimi başarısız: %s", e)
        return False
