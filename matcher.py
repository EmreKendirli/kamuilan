import re

from scraper import fold

DAYS_PER_YEAR = 360     # SGK hesabında 1 yıl = 360 prim günü

NUMBER_WORDS = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}

# Kalıplar fold() ile sadeleştirilmiş metinde aranır
# "en az 3 (üç) yıl tecrübe", "en az 5 yıllık mesleki tecrübeye"
EXPERIENCE = re.compile(
    r"en az (\d{1,2}|" + "|".join(NUMBER_WORDS) + r")\s*(?:\([^)]{1,12}\)\s*)?yil\w*"
    r"(?=.{0,90}?(?:tecrube|deneyim|calismis|calisma|hizmet))"
)
# "KPSS (P3) puan türünden en az 60 puan", "en az 80 (seksen) puan"
MIN_SCORE = re.compile(r"en az (\d{2,3})(?:[.,]\d+)?\s*(?:\([^)]{1,20}\)\s*)?(?:ve uzeri\s*)?puan")
KPSS = re.compile(r"kpss|kamu personel\w* secme|\bp\d{1,3}\b|puan tur")
LANGUAGE = re.compile(r"yds|yabanci dil|yokdil")
ALES = re.compile(r"\bales\b")
EXAMS = {"kpss": KPSS, "language": LANGUAGE, "ales": ALES}
ACADEMIC_TITLES = re.compile(r"arastirma gorevlisi|ogretim gorevlisi|docent")
# Bilişim personeli alımlarındaki sıralama: KPSS'nin %70'i + yabancı dilin %30'u
WEIGHTED_RANKING = re.compile(r"(%\s*70|yuzde yetmis).{0,200}?yabanci dil")

def experience_label(days):
    """840 -> '2 yıl 4 ay'"""
    years, months = days // DAYS_PER_YEAR, (days % DAYS_PER_YEAR) // 30
    parts = ([f"{years} yıl"] if years else []) + ([f"{months} ay"] if months else [])
    return " ".join(parts) or "1 aydan az"

def _stem(name):
    """'Yazılım Mühendisliği' / 'Yazılım Mühendisi' -> 'yazilim muhendis' (ekli halleri de eşleşsin)"""
    stem = " ".join(fold(name).split())
    for suffix in ("ligi", "lugu", "i", "u"):
        if stem.endswith(suffix) and len(stem) - len(suffix) >= 4:
            return stem.removesuffix(suffix)
    return stem

def _spans(folded, stems):
    """Bölüm adının geçtiği yerlerin çevresi; o pozisyonun şartları çoğunlukla burada yazar."""
    spans = []
    for stem in stems:
        for match in re.finditer(re.escape(stem), folded):
            spans.append((match.start() - 100, match.end() + 500))
    return spans

def _near(found, spans):
    return [value for position, value in found if any(start <= position <= end for start, end in spans)]

def _minimum_scores(folded):
    """'en az NN puan' ifadelerini, hemen öncesinde adı geçen sınava (KPSS, yabancı dil) göre ayırır."""
    found = {"kpss": [], "language": []}
    for match in MIN_SCORE.finditer(folded):
        score = int(match.group(1))
        if not 40 <= score <= 100:
            continue

        before = folded[max(0, match.start() - 160):match.start()]
        last_mention = {
            exam: max((m.end() for m in pattern.finditer(before)), default=-1)
            for exam, pattern in EXAMS.items()
        }
        exam = max(last_mention, key=last_mention.get)
        if last_mention[exam] < 0:
            # Sınavın adı puandan sonra da yazılabiliyor: "en az 70 puan (KPSS P3)"
            exam = "kpss" if KPSS.search(folded[match.end():match.end() + 80]) else None
        if exam in found:
            found[exam].append((match.start(), score))
    return found

def _experience_years(folded):
    found = []
    for match in EXPERIENCE.finditer(folded):
        number = match.group(1)
        found.append((match.start(), NUMBER_WORDS.get(number) or int(number)))
    return found

def _compare(required_values, mine_value, required, mine):
    """İlanda bulunan şart(lar)ı kişinin değeriyle karşılaştırıp tek satırlık sonuç üretir."""
    low, high = min(required_values), max(required_values)
    if mine_value is None:      # kişi bu bilgiyi girmemiş: şartı yalnızca bildir
        return {"state": "info", "text": required(low, high)}
    # Birden çok pozisyonun şartı karışmış olabilir: en düşüğünü bile tutmuyorsa olumsuz, hepsini tutuyorsa olumlu
    state = "fail" if mine_value < low else "ok" if mine_value >= high else "warn"
    return {"state": state, "text": f"{required(low, high)}; {mine(mine_value)}"}

def evaluate(listing, folded, profile):
    """İlanı profile göre değerlendirir; ilan profildeki bölümlerle ilgili değilse None döner.

    Dönen "group": suitable (uygun görünüyor), check (bir şart belirsiz), unlikely (bir şartı tutmuyor),
    academic (öğretim elemanı), faculty (öğretim üyesi), cancelled (iptal ilanı).
    """
    own = [d for d in profile["departments"] if _stem(d) in folded]
    related = [d for d in profile["related_departments"] if _stem(d) in folded]
    if not own and not related:
        return None

    stems = [_stem(d) for d in own + related]
    title = fold(listing["title"])
    result = {"own": bool(own), "terms": stems, "checks": []}

    if "iptal" in title:
        return {**result, "group": "cancelled"}
    if "ogretim uyesi" in title:
        return {**result, "group": "faculty"}

    checks = result["checks"]
    if own:
        checks.append({"state": "ok", "text": f"{', '.join(own)} ilanda geçiyor"})
    else:
        checks.append({"state": "warn", "text": f"İlanda {', '.join(related)} geçiyor; {', '.join(profile['departments'])} ayrıca yazmıyor"})

    # Başlık bir şey söylemiyorsa: akademik unvanlar sayıp KPSS'den hiç söz etmeyen ilan akademik kadrodur
    if re.search(r"ogretim|arastirma gorevlisi|akademik", title) or (ACADEMIC_TITLES.search(folded) and "kpss" not in folded):
        checks.append({"state": "info", "text": "Akademik kadro: KPSS geçmez; ALES ve çoğu kadroda yüksek lisans istenir"})
        return {**result, "group": "academic"}

    spans = _spans(folded, stems)
    minimums = _minimum_scores(folded)

    kpss = _near(minimums["kpss"], spans) or [score for _, score in minimums["kpss"]]
    if kpss:
        checks.append(_compare(
            kpss, profile["kpss"],
            required=lambda low, high: f"KPSS en az {low} isteniyor" if low == high else f"KPSS tabanı pozisyona göre {low}–{high}",
            mine=lambda score: f"sizde {score}"
        ))
    elif "kpss sarti aranma" in folded:
        checks.append({"state": "info", "text": "KPSS şartı aranmıyor"})

    weighted = WEIGHTED_RANKING.search(folded)
    language = _near(minimums["language"], spans)
    if language:
        checks.append(_compare(
            language, profile["yds"],
            required=lambda low, high: f"YDS en az {low} isteniyor" if low == high else f"YDS tabanı pozisyona göre {low}–{high}",
            mine=lambda score: f"sizde {score}"
        ))
    elif minimums["language"]:
        # Şart bölüm adından uzakta yazıyor: herkes için mi, yalnızca bazı pozisyonlar için mi belli değil
        lowest = min(score for _, score in minimums["language"])
        if profile["yds"] is None:
            checks.append({"state": "info", "text": f"İlanda YDS en az {lowest} şartı geçiyor"})
        elif profile["yds"] >= max(score for _, score in minimums["language"]):
            checks.append({"state": "ok", "text": f"İlanda YDS en az {lowest} şartı geçiyor; sizde {profile['yds']}"})
        else:
            checks.append({"state": "warn", "text": f"İlanda YDS en az {lowest} şartı geçiyor; sizde {profile['yds']}. Sizin pozisyonunuz için istenip istenmediğine bakın"})
    elif LANGUAGE.search(folded) and not weighted:
        checks.append({"state": "info", "text": "İlanda yabancı dil puanından söz ediliyor; şart olup olmadığına bakın"})

    if weighted and profile["kpss"] is not None:
        ranking = f"{profile['kpss'] * 0.7 + (profile['yds'] or 0) * 0.3:.1f}".replace(".", ",")
        checks.append({"state": "info", "text": f"Sıralama KPSS'nin %70'i + YDS'nin %30'u ile yapılıyor; sizin puanınız {ranking}"})
    elif weighted:
        checks.append({"state": "info", "text": "Sıralama KPSS'nin %70'i + YDS'nin %30'u ile yapılıyor"})
    if ALES.search(folded):
        checks.append({"state": "info", "text": "İlanda ALES puanı şartı geçiyor"})

    # Bilişim personeli ilanlarında bütün pozisyonlar alanla ilgili; deneyim şartı pozisyon tablosunda yazar
    experience = _experience_years(folded)
    years = [y for _, y in experience] if "bilisim personel" in title else _near(experience, spans)
    if years:
        checks.append(_compare(
            [y * DAYS_PER_YEAR for y in years], profile["premium_days"],
            required=lambda low, high: (
                f"En az {low // DAYS_PER_YEAR} yıl ({low} prim günü) deneyim isteniyor" if low == high
                else f"Deneyim şartı pozisyona göre {low // DAYS_PER_YEAR}–{high // DAYS_PER_YEAR} yıl ({low}–{high} prim günü)"
            ),
            mine=lambda days: f"sizde {days} gün ({experience_label(days)})"
        ))

    states = {check["state"] for check in checks}
    group = "unlikely" if "fail" in states else "check" if "warn" in states else "suitable"
    return {**result, "group": group}
