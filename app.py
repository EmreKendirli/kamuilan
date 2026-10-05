import logging
import re
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for

import matcher
import scraper
from config import CACHE_DIR, KEYWORDS, PROFILE, REFRESH_MINUTES, SITE_PORT, SITE_URL

app = Flask(__name__)
app.json.ensure_ascii = False

CACHE = Path(__file__).parent / CACHE_DIR
CACHE_FILE = re.compile(r"[0-9a-f]{12}(-\d+)?")     # scraper'ın ürettiği ilan kimliği

lock = threading.Lock()
state = {
    "listings": [],     # sitedeki güncel ilanlar
    "texts": {},        # ilan id -> (metin, sadeleştirilmiş metin)
    "updated": None,
    "indexing": True,   # liste alınıyor / ilan metinleri taranıyor
    "error": None
}

def cached_document(listing_id):
    """İlanın daha önce indirilmiş dosyasını döndürür (yoksa None)."""
    for path in CACHE.glob(f"{listing_id}.*"):
        if path.suffix != ".txt":
            return path
    return None

def ensure_document(listing):
    """İlan dosyası diskte yoksa indirir, metnini de yanına kaydeder."""
    path = cached_document(listing["id"])
    if path:
        return path

    data = scraper.download_document(listing)
    if data is None:
        return None

    path = CACHE / (listing["id"] + scraper.document_extension(data))
    path.write_bytes(data)
    (CACHE / f"{listing['id']}.txt").write_text(scraper.extract_text(data), encoding="utf-8")
    return path

def load_text(listing):
    """İlanın aranabilir metnini döndürür; dosya alınamazsa None."""
    text_path = CACHE / f"{listing['id']}.txt"
    if not text_path.exists() and not ensure_document(listing):
        return None
    return text_path.read_text(encoding="utf-8")

def refresh():
    listings = scraper.fetch_listings()
    if not listings:
        raise RuntimeError("Kaynak sitede ilan bulunamadı (sayfa yapısı değişmiş olabilir).")

    ids = {listing["id"] for listing in listings}
    with lock:
        state["listings"] = listings
        state["texts"] = {k: v for k, v in state["texts"].items() if k in ids}
        state["updated"] = scraper.now()
        state["error"] = None

    # Yayından kalkan ilanların dosyalarını temizle (yalnızca bizim ürettiğimiz adlar)
    for path in CACHE.iterdir():
        if CACHE_FILE.fullmatch(path.stem) and path.stem not in ids:
            path.unlink()

    missing = [listing for listing in listings if listing["id"] not in state["texts"]]
    if missing:
        print(f"[*] {len(missing)} ilanın metni taranıyor...")
    for listing in missing:
        was_cached = (CACHE / f"{listing['id']}.txt").exists()
        text = load_text(listing)
        if text is not None:
            with lock:
                state["texts"][listing["id"]] = (text, scraper.fold(text))
        if not was_cached:
            time.sleep(0.3)     # kaynak siteyi yormamak için
    if missing:
        print(f"[+] Metin taraması bitti: {len(state['texts'])}/{len(listings)} ilan aranabilir.")

def refresh_loop():
    while True:
        state["indexing"] = True
        try:
            refresh()
        except Exception as e:
            print(f"[!] İlanlar güncellenemedi: {e}")
            with lock:
                state["error"] = str(e)
        state["indexing"] = False
        time.sleep(REFRESH_MINUTES * 60)

def make_snippet(text, folded, terms):
    """Metinde ilk eşleşen kelimenin çevresinden kısa bir alıntı döndürür."""
    positions = [folded.find(term) for term in terms if term in folded]
    if not positions:
        return None
    start = max(0, min(positions) - 90)
    end = min(len(text), min(positions) + 160)
    # Alıntıyı kelime ortasından başlatıp bitirme
    if start > 0:
        start = text.find(" ", start, min(positions)) + 1 or start
    if end < len(text):
        end = text.rfind(" ", min(positions), end) if " " in text[min(positions):end] else end
    return ("… " if start > 0 else "") + text[start:end].strip() + (" …" if end < len(text) else "")

def deadline_info(listing):
    """Son başvuru gününe kalan gün sayısını ve ekranda gösterilecek halini döndürür."""
    if not listing["deadline"]:
        return None, None
    days = (date.fromisoformat(listing["deadline"]) - scraper.now().date()).days
    if days < 0:
        return days, "Süresi doldu"
    if days == 0:
        return days, "Bugün son gün"
    if days == 1:
        return days, "Yarın son gün"
    return days, f"{days} gün kaldı"

def find_listing(listing_id):
    with lock:
        listing = next((l for l in state["listings"] if l["id"] == listing_id), None)
    if not listing:
        abort(404, "Bu ilan artık yayında değil.")
    return listing

@app.after_request
def no_stale_pages(response):
    # Geri tuşuyla dönüldüğünde tarayıcı sayfanın eski kopyasını göstermesin
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-cache"
    return response

@app.get("/")
def index():
    return render_template("index.html", keywords=KEYWORDS)

def snapshot():
    """İsteğin üzerinde çalışacağı ilan/metin kopyası ve her yanıta eklenen durum bilgisi."""
    with lock:
        listings = list(state["listings"])
        texts = dict(state["texts"])
        updated, indexing, error = state["updated"], state["indexing"], state["error"]

    status = {
        "ready": updated is not None,
        "total": len(listings),
        "indexed": sum(1 for listing in listings if listing["id"] in texts),
        "indexing": indexing,
        "updated": updated.strftime("%H:%M") if updated else None,
        "error": error
    }
    return listings, texts, status

def public(listing):
    """İlanın sayfaya gönderilen hali."""
    result = {k: v for k, v in listing.items() if k != "href"}
    result["days_left"], result["days_left_label"] = deadline_info(listing)
    return result

@app.get("/api/search")
def search():
    terms = scraper.fold(request.args.get("q", "")).split()
    listings, texts, status = snapshot()

    results = []
    for listing in listings:
        heading = scraper.fold(f"{listing['institution']} {listing['title']}")
        text, folded = texts.get(listing["id"], ("", ""))
        if not all(term in heading or term in folded for term in terms):
            continue

        result = public(listing)
        result["in_title"] = all(term in heading for term in terms)
        result["hits"] = sum(folded.count(term) for term in terms)
        result["snippet"] = make_snippet(text, folded, terms)
        results.append(result)

    # Başlıkta geçenler üstte; kendi içlerinde sitedeki sıra (yeniden eskiye) korunur
    if terms:
        results.sort(key=lambda r: not r["in_title"])

    return jsonify({**status, "results": results})

def request_profile():
    """Sayfadaki formdan gelen bilgiler; form gönderilmemişse profil.json / config.py'deki profil."""
    args = request.args
    if "bolum" not in args:
        return PROFILE

    def names(key):
        # Çok kısa adlar ("it" gibi) her ilanla eşleşir
        return [name.strip() for name in args.get(key, "").split(",") if len(name.strip()) >= 3]

    def number(key, highest):
        """Boş bırakılan alan None döner: o şart karşılaştırılmaz, yalnızca bildirilir."""
        try:
            value = float(args.get(key, "").replace(",", "."))
        except ValueError:
            return None
        if value != value:      # "nan"
            return None
        value = min(max(value, 0), highest)
        return int(value) if value.is_integer() else value

    departments = names("bolum")
    days = number("gun", 20000)
    return {
        "title": ", ".join(departments),
        "departments": departments,
        "related_departments": names("yakin"),
        "kpss": number("kpss", 100),
        "yds": number("yds", 100),
        "premium_days": None if days is None else int(days)
    }

@app.get("/api/match")
def match():
    listings, texts, status = snapshot()
    profile = request_profile()

    groups = {"suitable": [], "check": [], "unlikely": [], "academic": []}
    hidden = {"faculty": 0, "cancelled": 0}
    for listing in listings:
        text, folded = texts.get(listing["id"], ("", ""))
        verdict = matcher.evaluate(listing, folded, profile)
        if not verdict:
            continue
        if verdict["group"] in hidden:
            hidden[verdict["group"]] += 1
            continue

        result = public(listing)
        result["own"] = verdict["own"]
        result["checks"] = verdict["checks"]
        result["terms"] = verdict["terms"]
        result["snippet"] = make_snippet(text, folded, verdict["terms"][:1])
        groups[verdict["group"]].append(result)

    # Kendi bölümünün adı geçen ilanlar, yalnızca yakın bölümün geçtiği ilanlardan önce
    for results in groups.values():
        results.sort(key=lambda r: not r["own"])

    return jsonify({**status, "profile": profile, "groups": groups, "hidden": hidden})

@app.get("/ilan/<listing_id>")
def detail(listing_id):
    listing = find_listing(listing_id)
    days_left, days_left_label = deadline_info(listing)
    path = cached_document(listing_id)
    return render_template(
        "detail.html",
        listing=listing,
        days_left=days_left,
        days_left_label=days_left_label,
        document_url=url_for("open_document", listing_id=listing_id),
        # İlanların neredeyse tamamı PDF; Word dosyaları tarayıcıda gösterilemez
        embed=path is None or path.suffix == ".pdf"
    )

@app.get("/ilan/<listing_id>/dosya")
def open_document(listing_id):
    listing = find_listing(listing_id)

    path = ensure_document(listing)
    if not path:
        # Listedeki link eskimiş olabilir; listeyi tazeleyip bir kez daha dene
        fresh = next((l for l in scraper.fetch_listings() if l["id"] == listing_id), None)
        path = ensure_document(fresh) if fresh else None
    if not path:
        abort(502, "İlan dosyası kaynak siteden alınamadı.")

    return send_file(path, download_name=f"ilan-{listing_id}{path.suffix}")

# İlan taraması hem "python app.py" ile hem de sunucuda (gunicorn app:app) başlasın.
# Durum bellekte tutulduğu için sunucuda tek işlemle (--workers 1) çalıştırılmalıdır.
CACHE.mkdir(exist_ok=True)
threading.Thread(target=refresh_loop, daemon=True).start()

if __name__ == "__main__":
    threading.Timer(1.0, webbrowser.open, args=[SITE_URL]).start()

    # Sayfa arama isteklerini sık yenilediği için her isteğin konsola yazılmasını kapat
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"[i] Site çalışıyor: {SITE_URL} (Kapatmak için Ctrl+C)")
    app.run(host="127.0.0.1", port=SITE_PORT)
