import json
import os
import schedule
import time
from scraper import fetch_all_jobs
from notifier import notify_jobs
from config import OUTPUT_FILE

def run_bot():
    print("\n--- Tarama Başlatıldı ---")
    jobs = fetch_all_jobs()
    
    seen_links = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            try:
                old_data = json.load(f)
                seen_links = {item["link"] for item in old_data}
            except Exception:
                pass
                
    new_jobs = [job for job in jobs if job["link"] not in seen_links]
    
    # Bulunan tüm ilanları her durumda JSON'a kaydet
    if jobs:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=4)
        print(f"[i] '{OUTPUT_FILE}' dosyası güncellendi/oluşturuldu.")
    
    if new_jobs:
        print(f"[+] {len(new_jobs)} yeni ilan tespit edildi.")
        notify_jobs(new_jobs)
    else:
        if jobs:
            print(f"[-] Toplam {len(jobs)} ilan bulundu ama hepsi zaten kayıtlıydı.")
        else:
            print("[-] Sitelerde aranan kelimelerle eşleşen hiç ilan bulunamadı.")

if __name__ == "__main__":
    run_bot()
    
    schedule.every().day.at("09:00").do(run_bot)
    schedule.every().day.at("15:00").do(run_bot)
    
    print("\n[i] Bot çalışıyor... (Kapatmak için Ctrl+C)")
    while True:
        schedule.run_pending()
        time.sleep(60)