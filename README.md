# 🎧 Music Radar

Favori sanatçı ve label'larından yeni release çıktığında mail atan otomasyon.

5 release blog'unu (jkmk, elektrobeats, edmwaves, electrobuzz, themusicfire) ve istediğin SoundCloud sanatçı/label sayfalarını tarar. Watchlist'inle eşleşen yeni release'leri bulunca dinleme linkleriyle (Bandcamp, SoundCloud, YouTube, Spotify, Beatport preview) mail atar.

**Manuel tetiklenir** — GitHub Actions'ta "Run workflow" butonuna bastığında çalışır. Cron yok, sen ne zaman istersen.

## Mimari

```
[Manuel trigger]
       ↓
[GitHub Actions]
       ↓
   ┌───┴────┬──────────┬──────────┐
   ↓        ↓          ↓          ↓
 5 blog   SoundCloud   artists/   seen.json
  RSS     HTML scrape  labels.txt  (state)
   ↓        ↓          ↓          ↓
   └────────┴──────┬───┘          │
                   ↓               │
            [eşleştirme]           │
                   ↓               │
            [yeni mi? ←────────────┘
            seen.json'a bak]
                   ↓
            [dinleme linkleri ekle]
                   ↓
            [HTML mail at]
                   ↓
            [seen.json'u git'e commit]
```

## Kurulum

### 1. Bu repo'yu GitHub'a yükle

```bash
cd music-radar
git init
git add .
git commit -m "Initial commit"
gh repo create music-radar --private --source=. --push
# veya GitHub'da repo oluştur, sonra:
# git remote add origin git@github.com:USERNAME/music-radar.git
# git branch -M main && git push -u origin main
```

### 2. Gmail App Password oluştur

> Normal Gmail şifren çalışmaz, App Password lazım.

1. https://myaccount.google.com/security adresine git
2. **2-Step Verification**'ı aç (zorunlu önkoşul)
3. **App passwords** linkine tıkla (URL: `https://myaccount.google.com/apppasswords`)
4. App: "Mail", Device: "music-radar" gibi bir şey yaz, **Generate**
5. Çıkan 16 haneli şifreyi kopyala — bir daha gösterilmeyecek

Gmail kullanmıyorsan kendi SMTP sunucunun bilgilerini kullan (Outlook, Yandex, vs).

### 3. GitHub Secrets'ı ayarla

Repo'nun **Settings → Secrets and variables → Actions → New repository secret** sekmesinden şunları ekle:

| Secret adı   | Değer                                  | Örnek                |
|--------------|----------------------------------------|----------------------|
| `SMTP_HOST`  | SMTP sunucu adresi                     | `smtp.gmail.com`     |
| `SMTP_PORT`  | SMTP port (TLS için 587)               | `587`                |
| `SMTP_USER`  | SMTP giriş emaili                      | `you@gmail.com`      |
| `SMTP_PASS`  | App password (2. adımda oluşturduğun)  | `abcd efgh ijkl mnop`|
| `MAIL_FROM`  | Gönderen adresi (genelde SMTP_USER)    | `you@gmail.com`      |
| `MAIL_TO`    | Alıcı adresi (kendin)                  | `you@gmail.com`      |

### 4. Watchlist'i doldur

`config/artists.txt`, `config/labels.txt` ve `config/soundcloud.txt` dosyalarını düzenle. Her satıra bir isim, `#` ile başlayanlar yorum.

**Eşleştirme nasıl çalışır:**
- Büyük/küçük harf duyarsız
- Kısmi (substring) eşleşme — "Tale Of Us" yazarsan "Tale Of Us & Mind Against" remix'ini de yakalar
- Sanatçılar: title, artist, label, summary alanlarında aranır
- Label'lar: sadece label ve title alanlarında aranır (sanatçı ismine yanlış eşleşmeyi önlemek için)

Push et:
```bash
git add config/
git commit -m "Add watchlist"
git push
```

### 5. İlk taramayı çalıştır

GitHub'da repo'na git → **Actions** sekmesi → sol panelden **"Check New Releases"** workflow'unu seç → sağ üstte **Run workflow** butonu → varsayılan ayarlarla **Run workflow**.

3-5 dakika içinde mail kutunda raporu görürsün.

> ⚠️ **İlk taramada büyük olasılıkla çok fazla mail alacaksın** çünkü `seen.json` boş. Her release "yeni" sayılır. Bu yüzden ilk seferinde `lookback_days`'i 3 gibi küçük bir değere set edip çalıştırmanı öneririm — bundan sonraki seferlerde 14 normal kalsın.

## Haftalık Kullanım

1. GitHub → Actions → Check New Releases → **Run workflow**
2. (İstersen) `lookback_days`'i değiştir
3. Bekle, mail gelsin

Hepsi bu. Repo state'i (seen.json) workflow tarafından otomatik güncellenir.

## Watchlist'i güncellemek

`config/*.txt` dosyalarını düzenle, push et. Bir sonraki tarama yeni listeyi kullanır.

```bash
echo "Massano" >> config/artists.txt
echo "Innervisions" >> config/labels.txt
git commit -am "Add Massano + Innervisions" && git push
```

## Sorun giderme

- **Mail gelmedi:** Actions sekmesinde son run'ı aç, log'lara bak. "Mail başarıyla gönderildi" satırı var mı? Yoksa SMTP secret'ları kontrol et.
- **5 sitenin hepsi 403 dönüyor:** Site'ler GitHub Actions IP'lerini topluca bloklamış olabilir. Bu nadir ama mümkün. Çözüm: script'i kendi makinende çalıştır veya bir VPS kullan.
- **Çok az/sıfır eşleşme:** Watchlist'teki isimler ile blog'larda kullanılan isimler farklı yazılıyor olabilir. Bir release sayfasını aç, sanatçı/label nasıl yazılmış, watchlist'i ona göre güncelle.
- **Aynı release'i 2 kere mail aldım:** Farklı blog'larda farklı URL'lerle aynı release var. Bu istenen davranış (hangi blog'da olduğunu görmek için), ama deduplication istersen `state.py`'ı title-bazlı yapacak şekilde değiştirebiliriz.

## Sınırlamalar / Bilinmesi gerekenler

- **Spotify entegrasyonu yok.** Şu an Spotify "arama linki" üretiliyor, direkt track linki değil. Direkt link istersen Spotify Web API entegrasyonu eklenir, Client ID/Secret gerekir.
- **SoundCloud sayfa scraping kırılgan.** SoundCloud HTML'ini değiştirirse kopabilir. RSS olsaydı daha iyi olurdu ama public RSS yok.
- **seen.json sonsuza dek büyür** (180 gün otomatik temizlik var ama). Repo size'ı bir noktada şişerse manuel reset gerekebilir.
- **Beatport vs. legal indirme yok ve eklenmeyecek.** Mail'deki linkler dinleme/preview için; download için verdiğin 5 site zaten release linklerini içeriyor.

## Geliştirme

Lokal test:
```bash
pip install -r requirements.txt
python -m src.main  # SMTP env'leri set etmeden çalıştırırsan mail kısmı fail eder ama scraping çalışır
```

Yapı:
```
src/
├── main.py       Orkestratör
├── sources.py    Blog RSS + SoundCloud scraping
├── matcher.py    Watchlist eşleştirme
├── enricher.py   Dinleme linkleri
├── state.py      seen.json yönetimi
└── mailer.py     HTML mail üretimi + SMTP
```
