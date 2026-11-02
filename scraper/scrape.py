#!/usr/bin/env python3
"""KPSS ilanlarını toplar, PDF ilan metinlerini okuyup ön lisans (P93) uygunluğunu işaretler."""
import datetime as dt, io, json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

SOURCES = [
    {"name": "OMÜ KPSS-B İlanları", "url": "https://mezun.omu.edu.tr/tr/is-hayati/is-staj/kpss-b-ilanlari"},
    {"name": "OMÜ Sözleşmeli Personel İlanları", "url": "https://mezun.omu.edu.tr/tr/is-hayati/is-staj/4-b-soezlesmeli-personel-alim-ilanlari"},
]
OUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (kpss-takip; kisisel ilan takibi)"}
MONTHS = {"ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
          "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12}
_MAP = str.maketrans("İIıÇçĞğÖöŞşÜü", "iiiccggoossuu")
WORD = r"[A-Za-zÇĞİÖŞÜçğıöşü]"
DATE_RE = re.compile(rf"\((\d{{1,2}})\s*({WORD}*)\s*-\s*(\d{{1,2}})\s+({WORD}+)\s+(\d{{4}})\)")


def fold(s):  # uzunluğu korur: Türkçe harfleri ASCII'ye çevirip küçültür
    return s.translate(_MAP).lower()


ILLER = ["Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara", "Antalya", "Ardahan",
         "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman", "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu",
         "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne", "Elazığ",
         "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır",
         "Isparta", "İstanbul", "İzmir", "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri",
         "Kilis", "Kırıkkale", "Kırklareli", "Kırşehir", "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
         "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir", "Niğde", "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun",
         "Siirt", "Sinop", "Sivas", "Şanlıurfa", "Şırnak", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak", "Van",
         "Yalova", "Yozgat", "Zonguldak"]
assert len(ILLER) == 81
IL_PATTERNS = [(il, re.compile(r"(?<![a-z])" + fold(il) + r"(?![a-z])")) for il in ILLER]
IL_PATTERNS += [("Afyonkarahisar", re.compile(r"(?<![a-z])afyon(?![a-z])")),
                ("Kahramanmaraş", re.compile(r"(?<![a-z])maras(?![a-z])")),
                ("Şanlıurfa", re.compile(r"(?<![a-z])urfa(?![a-z])")),
                ("Gaziantep", re.compile(r"(?<![a-z])antep(?![a-z])"))]


def detect_iller(text):
    """Metinde geçen illeri, geçiş sırasına göre döndürür."""
    f = fold(text)
    pos = {}
    for il, rx in IL_PATTERNS:
        m = rx.search(f)
        if m and (il not in pos or m.start() < pos[il]):
            pos[il] = m.start()
    return sorted(pos, key=pos.get)


def parse_dates(title):
    m = DATE_RE.search(title)
    if not m:
        return None, None
    d1, m1, d2, m2, y = m.groups()
    m2n = MONTHS.get(fold(m2))
    m1n = MONTHS.get(fold(m1)) if m1 else m2n
    if not m2n or not m1n:
        return None, None
    y = int(y)
    try:
        end = dt.date(y, m2n, int(d2))
        start = dt.date(y if m1n <= m2n else y - 1, m1n, int(d1))
    except ValueError:
        return None, None
    return start.isoformat(), end.isoformat()


def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(3)


def list_postings(src):
    soup = BeautifulSoup(get(src["url"]).text, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text().split())
        if "ilan" not in fold(title) or not DATE_RE.search(title):
            continue
        url = urljoin(src["url"], a["href"])
        if url in seen:
            continue
        seen.add(url)
        start, end = parse_dates(title)
        out.append({"source": src["name"], "title": title, "url": url, "start": start, "end": end})
    return out


def classify(text):
    f = fold(text)
    if len(f.strip()) < 200:
        return {"status": "okunamadi", "reason": "PDF metni okunamadı (taranmış görüntü olabilir); ilanı elle açıp kontrol edin.", "mins": [], "snippet": ""}
    p93 = re.search(r"p\s?93", f)
    onl = re.search(r"on\s?lisans", f)
    bp = re.search(r"bilgisayar\s+programciligi", f)
    mins = sorted({int(x) for x in re.findall(r"en az\s*(\d{2,3})\s*puan", f) if 40 <= int(x) <= 100})
    if p93 and bp:
        status, reason = "uygun", "İlanda P93 ve Bilgisayar Programcılığı geçiyor."
    elif p93:
        status, reason = "kontrol", "P93 geçiyor ama Bilgisayar Programcılığı geçmiyor; kadronun bölüm şartını okuyun."
    elif onl:
        status, reason = "kontrol", "Ön lisans geçiyor ama P93 görünmüyor; ilanı okuyun."
    else:
        status, reason = "uygun_degil", "P93 / ön lisans geçmiyor (lisans veya lise ilanı olabilir)."
    m = bp or p93 or onl
    snippet = ""
    if m:
        s = max(0, m.start() - 160)
        snippet = " ".join(text[s:m.end() + 160].split())
    return {"status": status, "reason": reason, "mins": mins, "snippet": snippet}


def analyze(url):
    r = get(url)
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" not in ctype and not url.lower().endswith(".pdf"):
        return {"status": "manuel", "reason": "Bu ilan PDF değil, kurumun kendi sitesinde; elle kontrol edin.", "mins": [], "snippet": ""}
    reader = PdfReader(io.BytesIO(r.content))
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:40])
    res = classify(text)
    res["_head"] = text[:2500]
    return res


def main():
    old = {}
    if OUT.exists():
        try:
            old = {p["url"]: p for p in json.loads(OUT.read_text("utf-8")).get("postings", [])}
        except Exception:
            pass
    today, errors, found = dt.date.today(), [], []
    for src in SOURCES:
        try:
            found += list_postings(src)
        except Exception as e:
            errors.append(f"{src['name']}: {e}")
    if not found:
        print("Hiç ilan bulunamadı:", errors, file=sys.stderr)
        sys.exit(1)
    result = []
    for p in found:
        if p["end"] and dt.date.fromisoformat(p["end"]) < today - dt.timedelta(days=14):
            continue
        prev = old.get(p["url"])
        if prev and prev.get("status") not in (None, "okunamadi") and "iller" in prev:
            p.update({k: prev[k] for k in ("status", "reason", "mins", "snippet", "iller")})
        else:
            head = ""
            try:
                p.update(analyze(p["url"]))
                head = p.pop("_head", "")
            except Exception as e:
                p.update({"status": "okunamadi", "reason": f"İndirilemedi: {e}", "mins": [], "snippet": ""})
                errors.append(f"{p['title']}: {e}")
            p["iller"] = detect_iller(p["title"]) or detect_iller(head)
        result.append(p)
    result.sort(key=lambda x: x["end"] or "9999")
    OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                               "postings": result, "errors": errors}, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(result)} ilan yazıldı, {len(errors)} hata.")


if __name__ == "__main__":
    main()
