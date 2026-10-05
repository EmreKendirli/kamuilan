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

# "Bana uygun" sekmesinde ilanların karşılaştırılacağı bilgiler.
# Buradakiler örnek değerlerdir; kendi bilgilerinizi profil.json dosyasına yazın (git'e eklenmez).
PROFILE = {
    "title": "Yazılım Mühendisi",
    "departments": ["Yazılım Mühendisliği"],            # mezun olunan bölüm
    "related_departments": ["Bilgisayar Mühendisliği"], # yakın bölüm: başvuru hakkı ilana göre değişir
    "kpss": 70,
    "yds": 0,                                           # yabancı dil puanı (yoksa 0)
    "premium_days": 0                                   # SGK prim günü (360 gün = 1 yıl deneyim)
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