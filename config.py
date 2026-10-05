import json
import os

# İlanlarda taranacak anahtar kelimeler
KEYWORDS = [
    "yazılım",
    "mühendis",
    "bilişim",
    "bilgisayar",
    "programcı",
    "çözümleyici",
    "tekniker",
    "personel"
]

# "Bana uygun" sekmesindeki formun hazır dolu geleceği bilgiler.
# Boş bırakılırsa form boş açılır; kendi bilgilerinizi profil.json dosyasına yazın (git'e eklenmez).
PROFILE = {
    "title": "",
    "departments": [],          # mezun olunan bölüm, örn. ["Yazılım Mühendisliği"]
    "related_departments": [],  # yakın bölüm: başvuru hakkı ilana göre değişir
    "kpss": None,
    "yds": None,                # yabancı dil puanı
    "premium_days": None        # SGK prim günü (360 gün = 1 yıl deneyim)
}

_profile_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profil.json")
if os.path.exists(_profile_file):
    with open(_profile_file, encoding="utf-8") as f:
        PROFILE.update(json.load(f))

TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = "BOT_TOKEN_BURAYA"
TELEGRAM_CHAT_ID = "CHAT_ID_BURAYA"

OUTPUT_FILE = "bulunan_ilanlar.json"

# Arama sitesi (app.py)
SITE_PORT = 5000
SITE_URL = f"http://localhost:{SITE_PORT}"
CACHE_DIR = "cache"      # indirilen ilan dosyaları ve metinleri
REFRESH_MINUTES = 30     # ilan listesinin yenilenme sıklığı