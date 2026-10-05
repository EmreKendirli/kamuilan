import hashlib
import io
import logging
import re
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from config import KEYWORDS, SITE_URL

# pypdf bozuk PDF nesneleri için satır satır uyarı basıyor
logging.getLogger("pypdf").setLevel(logging.ERROR)

BASE_URL = "https://kamuilan.sbb.gov.tr/"
SOURCE = "Kamu İlan (SBB)"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12
}

# Harf sayısı değişmediği için sadeleşmiş metindeki konumlar asıl metinle aynıdır
_TR_MAP = str.maketrans("İIıŞşĞğÜüÖöÇçÂâÎîÛû", "iiissgguuooccaaiiuu")

def fold(text):
    """Türkçe harfleri sadeleştirip küçültür; 'BİLİŞİM', 'bilişim' ve 'bilisim' aynı olur."""
    return text.translate(_TR_MAP).lower()

def now():
    """Türkiye saati (UTC+3); sunucu başka saat diliminde çalışsa da tarihler kaymasın."""
    return datetime.now(timezone(timedelta(hours=3)))

def parse_deadline(apply_dates, today=None):
    """'4 Ekim - 11 Ekim' aralığının son gününü tarihe çevirir (sitede yıl yazmıyor)."""
    found = re.findall(r"(\d{1,2})\s+([^\W\d]+)", apply_dates)
    if not found:
        return None
    day, month = int(found[-1][0]), MONTHS.get(fold(found[-1][1]))
    if not month:
        return None

    today = today or now().date()
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            pass
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - today).days))

def fetch_listings():
    """kamuilan.sbb.gov.tr ana sayfasındaki güncel ilanların tamamını döndürür."""
    response = requests.get(BASE_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.content.decode("utf-8-sig", "replace"), "html.parser")

    listings = []
    seen_ids = set()
    for group in soup.select("#nav2 li"):
        time_tag = group.find("time")
        published = time_tag.get_text(" ", strip=True) if time_tag else ""

        for link in group.select("a.xx[href]"):
            institution_tag = link.select_one(".alt_p1")
            title_tag = link.select_one(".alt_p2")
            if not institution_tag or not title_tag:
                continue

            apply_dates = ""
            dates_tag = title_tag.find("em")
            if dates_tag:
                apply_dates = " ".join(dates_tag.get_text().split()).strip("() ")
                dates_tag.extract()

            institution = " ".join(institution_tag.get_text().split())
            title = " ".join(title_tag.get_text().split())

            # Sitedeki "kod" her sayfa yüklemesinde değiştiği için kimliği içerikten üretiyoruz
            base_id = hashlib.sha1(f"{institution}|{title}|{apply_dates}".encode("utf-8")).hexdigest()[:12]
            listing_id, n = base_id, 1
            while listing_id in seen_ids:
                n += 1
                listing_id = f"{base_id}-{n}"
            seen_ids.add(listing_id)

            logo = link.find("img")
            deadline = parse_deadline(apply_dates)
            listings.append({
                "id": listing_id,
                "institution": institution,
                "title": title,
                "apply_dates": apply_dates,
                "published": published,
                "deadline": deadline.isoformat() if deadline else None,
                "logo": BASE_URL + logo["src"].lstrip("./").split("#")[0] if logo and logo.get("src") else None,
                "href": link["href"]
            })

    return listings

def download_document(listing):
    """İlanın dosyasını (çoğunlukla PDF) indirir; alınamazsa None döner."""
    try:
        # Site, Referer başlığı kendi adresi olmayan istekleri 404 sayfasına yolluyor
        response = requests.get(
            BASE_URL + listing["href"],
            headers={**HEADERS, "Referer": BASE_URL},
            timeout=60
        )
    except requests.RequestException as e:
        print(f"  [!] İlan dosyası indirilemedi ({listing['institution']}): {e}")
        return None

    data = response.content
    is_html = "html" in response.headers.get("Content-Type", "")
    if response.status_code != 200 or not data or (is_html and b"404" in data[:2000]):
        return None
    return data

def document_extension(data):
    """İndirilen dosyanın türünü ilk baytlarından tahmin eder."""
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"PK\x03\x04"):
        return ".docx"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return ".doc"
    return ".html"

def extract_text(data):
    """İlan dosyasının aranabilir metnini çıkarır (taranmış/resim PDF'lerde boş döner)."""
    try:
        if data.startswith(b"%PDF"):
            reader = PdfReader(io.BytesIO(data))
            text = " ".join(page.extract_text() or "" for page in reader.pages)
        elif document_extension(data) == ".html":
            text = BeautifulSoup(data, "html.parser").get_text(" ")
        else:
            text = ""
    except Exception as e:
        print(f"  [!] İlan metni okunamadı: {e}")
        text = ""
    return " ".join(text.split())

def fetch_all_jobs():
    print("[*] Resmi kaynaklar taranıyor...")

    try:
        listings = fetch_listings()
    except Exception as e:
        print(f"  [!] Kamu İlan hatası: {e}")
        return []
    print(f"  [>] Kamu İlan'da toplam {len(listings)} adet ilan inceleniyor...")

    keywords = [fold(kw) for kw in KEYWORDS]
    jobs = []
    for listing in listings:
        heading = f"{listing['institution']} - {listing['title']}"
        if any(kw in fold(heading) for kw in keywords):
            jobs.append({
                "title": f"{heading} ({listing['apply_dates']})",
                # Sitenin kendi ilan linkleri kalıcı değil; ilan, arama sitesi (app.py) üzerinden açılır
                "link": f"{SITE_URL}/ilan/{listing['id']}",
                "source": SOURCE
            })

    print(f"  [+] Kamu İlan'dan {len(jobs)} ilan eşleşti.")
    return jobs
