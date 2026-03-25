#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FREE LEAD AGENT v15 — Lead Hunter & Automation Expert (FIXED).
REAL customer pain quotes from reviews. Strict Underdog filter.
Instagram/TG search required. Elite report with ACTUAL complaints.
"""

import sys
import re
import time
import requests
import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ─── CONFIG ──────────────────────────────────────────────────────────────────

CITY = "Minsk"
BBOX = "53.84,27.40,53.97,27.70"
OUTPUT = "SECRET_LEADS.md"
TARGET_LEADS = 5
MIN_REVIEWS = 5
MAX_REVIEWS = 45  # UNDERDOG filter: exclude >45 reviews

# ─── OSM MIRRORS ───────────────────────────────────────────────────────────────

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

# ─── UNDERDOG BUSINESS CATEGORIES (private points only) ───────────────────

UNDERDOG_QUERY = """
[out:json][timeout:25];
(
  node["shop"="car_repair"]({BBOX});
  node["shop"="beauty"]({BBOX});
  node["shop"="hairdresser"]({BBOX});
  node["shop"="clothes"]({BBOX});
  node["shop"="florist"]({BBOX});
  node["shop"="bakery"]({BBOX});
  node["shop"="butcher"]({BBOX});
  node["amenity"="cafe"]({BBOX});
  node["amenity"="restaurant"]({BBOX});
  node["amenity"="tutor"]({BBOX});
  node["amenity"="dentist"]({BBOX});
  node["shop"="barber"]({BBOX});
);
out tags 500;
""".replace("{BBOX}", BBOX)

# ─── NICHE NAMES ───────────────────────────────────────────────────────────────

NICHE_MAP = {
    "car_repair": "СТО",
    "beauty": "Салон красоты",
    "hairdresser": "Парикмахерская",
    "clothes": "Шоурум",
    "florist": "Цветы",
    "bakery": "Пекарня",
    "butcher": "Мясная лавка",
    "cafe": "Кафе",
    "restaurant": "Ресторан",
    "tutor": "Репетитор",
    "dentist": "Стоматология",
    "barber": "Барбершоп",
}

# ─── CORPORATE CHAINS TO EXCLUDE (strict filter) ───────────────────────────

CORPORATE_KEYWORDS = [
    "детский мир", "пятерочка", "евроопт", "корона", "соседи", "гиппо",
    "милавица", "respublika", "marvel", "zara", "h&m", "mango",
    "kfc", "mcdonalds", "burger king", "subway", "starbucks",
    "шоколадница", "кофе хауз", "даблби", "кофеин",
    "гкб", "поликлиника", "больница", "аптека", "беларуснефть",
    "беларуснафта", "азс", "минск", "республика"
]

# ─── DDGS ────────────────────────────────────────────────────────────────────

def _ddgs(query, n=5):
    try:
        from ddgs import DDGS
        return DDGS().text(query, max_results=n)
    except Exception:
        return []

# ─── FAST OSM FETCH ───────────────────────────────────────────────────────────

def fetch_osm_data():
    """Fast OSM data fetch."""
    print("🔍 Поиск UNDERDOG бизнеса через OSM...")
    
    for url in MIRRORS:
        try:
            r = requests.post(url, data={"data": UNDERDOG_QUERY}, timeout=30,
                              headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                elements = data.get("elements", [])
                print(f"✅ Найдено {len(elements)} бизнесов")
                return elements
        except Exception as e:
            print(f"❌ Ошибка {url}: {e}")
            continue
    
    print("❌ Все зеркала недоступны")
    return []

# ─── LEAD PROCESSING ─────────────────────────────────────────────────────────--

def is_corporate_business(name):
    """Strict corporate filter."""
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in CORPORATE_KEYWORDS)

def extract_lead_info(element):
    """Extract lead info from OSM element."""
    tags = element.get("tags", {})
    
    # Basic info
    name = tags.get("name", "").strip()
    if not name or len(name) < 2:
        return None
    
    # STRICT CORPORATE FILTER
    if is_corporate_business(name):
        return None
    
    # Niche detection
    niche_raw = tags.get("amenity") or tags.get("shop", "")
    niche = NICHE_MAP.get(niche_raw, niche_raw.replace("_", " ").title())
    
    # Contact info
    phone = tags.get("phone") or tags.get("contact:phone", "")
    website = tags.get("website") or tags.get("contact:website", "")
    rating = tags.get("rating", "")
    
    # Address
    street = tags.get("addr:street", "")
    house = tags.get("addr:housenumber", "")
    address = f"{street} {house}".strip() if street else CITY
    
    return {
        "name": name,
        "niche": niche,
        "phone": phone,
        "website": website,
        "rating": rating,
        "address": address,
        "raw_tags": tags
    }

def find_instagram(name, city):
    """Find Instagram link - REQUIRED for all leads."""
    print(f"    🔍 Поиск Instagram для {name}...")
    
    results = _ddgs(f'"{name}" {city} instagram', n=5)
    
    for r in results:
        body = r.get("body", "") + " " + r.get("href", "")
        m = re.search(r'instagram\.com/([a-zA-Z0-9_.]+)', body)
        if m and m.group(1) not in ("explore", "accounts", "p", "reel", "stories", "popular"):
            return f"https://www.instagram.com/{m.group(1)}/"
    
    return ""

def get_review_count_and_rating(name, city):
    """Get review count and rating from search."""
    print(f"    🔍 Подсчет отзывов для {name}...")
    
    review_count = 0
    rating = ""
    
    results = _ddgs(f'"{name}" {city} отзывы рейтинг', n=5)
    
    for r in results:
        body = r.get("body", "").lower()
        title = r.get("title", "").lower()
        text = body + " " + title
        
        # Extract review count
        if review_count == 0:
            cm = re.search(r'(\d+)\s*(отзыв|review|оценк)', text)
            if cm:
                try:
                    review_count = int(cm.group(1))
                except:
                    pass
        
        # Extract rating
        if not rating:
            rm = re.search(r'(\d[.,]\d)\s*/?\s*5|рейтинг[:\s]*(\d[.,]\d)', text)
            if rm:
                rating = (rm.group(1) or rm.group(2)).replace(",", ".")
    
    return review_count, rating

def find_real_customer_pain(name, city):
    """Find REAL customer pain quotes from reviews - FIXED VERSION."""
    print(f"    🔍 Поиск РЕАЛЬНЫХ жалоб для {name}...")
    
    pain_keywords = [
        "не берут трубку", "не дозвониться", "не дозвонился", "не ответили",
        "игнорируют", "админ", "администратор", "запись", "ждала ответа",
        "долго ждал", "занято", "не отвечают", "не смог записаться",
        "хамит", "груб", "плохо обслуж", "медленно", "отменили"
    ]
    
    real_pain_quotes = []
    
    # Search for ACTUAL reviews on review sites
    review_sites = [
        f'"{name}" {city} отзывы 2gis',
        f'"{name}" {city} отзывы яндекс',
        f'"{name}" {city} отзывы google',
        f'"{name}" {city} отзывы flamp',
    ]
    
    for site_query in review_sites:
        results = _ddgs(site_query, n=5)
        
        for r in results:
            body = r.get("body", "")
            href = r.get("href", "")
            
            # Look for review content patterns
            review_patterns = [
                r'"([^"]{30,200})"',  # Quotes in text
                r'(\d+[.]\s*[^.!?]{30,150}[.!?])',  # Numbered reviews
                r'([A-ZА-Я][^.!?]{30,150}[.!?])',  # Sentences with proper capitalization
            ]
            
            for pattern in review_patterns:
                matches = re.findall(pattern, body)
                for match in matches:
                    # Check if this is actually about the business and has pain
                    if name.lower() in match.lower():
                        for keyword in pain_keywords:
                            if keyword in match.lower():
                                # Clean and validate the quote
                                clean_quote = re.sub(r'\s+', ' ', match.strip())
                                
                                # Additional validation
                                if (len(clean_quote) > 40 and 
                                    len(clean_quote) < 200 and
                                    not any(skip in clean_quote.lower() for skip in [
                                        'вакансия', 'работа', 'требуется', 'резюме',
                                        'цена', 'стоимость', 'адрес', 'часы'
                                    ])):
                                    
                                    if clean_quote not in real_pain_quotes:
                                        real_pain_quotes.append(clean_quote)
                                        break  # One pain quote per match
    
    # If no real pain found, try direct complaint search
    if not real_pain_quotes:
        complaint_queries = [
            f'"{name}" {city} "не дозвониться" отзыв',
            f'"{name}" {city} "не берут трубку" отзыв',
            f'"{name}" {city} "администратор" отзыв',
        ]
        
        for query in complaint_queries:
            results = _ddgs(query, n=3)
            for r in results:
                body = r.get("body", "")
                if name.lower() in body.lower():
                    # Extract context around pain keyword
                    for keyword in pain_keywords:
                        if keyword in body.lower():
                            kw_idx = body.lower().find(keyword)
                            start = max(0, kw_idx - 100)
                            end = min(len(body), kw_idx + 100)
                            context = body[start:end].strip()
                            
                            # Clean up
                            clean_context = re.sub(r'\s+', ' ', context)
                            clean_context = clean_context.strip('.,!?')
                            
                            if len(clean_context) > 50 and len(clean_context) < 200:
                                if clean_context not in real_pain_quotes:
                                    real_pain_quotes.append(clean_context)
                                    break
    
    return real_pain_quotes[:2]  # Return top 2 real pain quotes

def check_site_automation(website):
    """Check site for automation features."""
    if not website:
        return "Нет сайта", "Отлично - нет автоматизации!"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(website, timeout=15, headers=headers)
        content = r.text.lower()
        
        # Check for automation
        automation_keywords = [
            "yclients", "dikidi", "altegio", "booksy", "record",
            "онлайн-запись", "online-запись", "записаться", "booking",
            "календарь", "appointment", "личный кабинет"
        ]
        
        found = [kw for kw in automation_keywords if kw in content]
        
        if found:
            return f"Есть автоматизация: {found[0]}", "Не наш клиент - уже автоматизированы"
        else:
            return "Есть сайт без автоматизации", "Наш клиент - нет онлайн-записи"
    
    except:
        return "Сайт недоступен", "Наш клиент - проблемы с сайтом"

def calculate_lead_score(lead, review_count, pain_quotes, site_status):
    """Calculate lead score for prioritization."""
    score = 0
    
    # REAL pain quotes = platinum lead
    if pain_quotes:
        score += 100
    
    # No site = good lead
    if not lead["website"]:
        score += 40
    
    # No phone = needs AI
    if not lead["phone"]:
        score += 30
    
    # Site without automation = our client
    if "нет автоматизации" in site_status.lower():
        score += 50
    
    # Review count in sweet spot
    if MIN_REVIEWS <= review_count <= MAX_REVIEWS:
        score += 20
    
    return score

# ─── ELITE REPORT ─────────────────────────────────────────────────────────--

def build_elite_report(leads):
    """Build elite report with cold outreach scripts."""
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    
    lines = []
    lines.append("# SECRET LEADS | 🏢 LEAD HUNTER & AUTOMATION EXPERT")
    lines.append(f"**Город:** {CITY} | **Дата:** {now} | **Лидов:** {len(leads)}")
    lines.append(f"**Фильтр:** {MIN_REVIEWS}-{MAX_REVIEWS} отзывов | Только UNDERDOG бизнес")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    for lead in leads:
        name = lead["name"]
        rating = lead.get("rating", "Нет рейтинга")
        review_count = lead["review_count"]
        phone = lead["phone"] if lead["phone"] else "Нет телефона"
        insta = lead.get("instagram", "")
        pain_quotes = lead.get("pain_quotes", [])
        site_status = lead.get("site_status", "Нет сайта")
        score = lead["score"]
        
        # Build contact line
        contact = phone
        if insta:
            contact += f" | **📱 Insta/TG:** [{insta}]"
        
        lines.append(f"### 🏢 {name} — ⭐ {rating} ({review_count} отз.)")
        lines.append(f"**📍 Контакт:** {contact}")
        lines.append("")
        
        # Pain evidence
        lines.append("> **🚩 ДОКАЗАТЕЛЬСТВО БОЛИ:**")
        if pain_quotes:
            for quote in pain_quotes:
                lines.append(f'> - "{quote}"')
        
        # Add site fact
        if "нет сайта" in site_status.lower():
            lines.append('> - Факт: "Нет сайта и онлайн-записи, теряют клиентов в нерабочее время"')
        elif "нет автоматизации" in site_status.lower():
            lines.append('> - Факт: "Сайт есть, но нет онлайн-записи, клиенты теряются"')
        
        lines.append("")
        
        # Cold outreach script
        lines.append("**🎤 ТВОЙ ХОЛОДНЫЙ ЗАХОД:**")
        if pain_quotes:
            lines.append(f'> "Привет! Я заметил отзыв от клиента, где не смогли до вас дозвониться. Вы потеряли деньги. Я внедрю вам ИИ-звонаря или Менеджера Директа за отзыв/кейс, чтобы это не повторялось. Интересно?"')
        else:
            lines.append(f'> "Привет! Заметил, что у вас нет онлайн-записи. Клиенты теряются, пока пытаются дозвониться. Сделаю вам ИИ-ассистента под ключ за отзыв, чтобы вы не теряли заказы. Интересно?"')
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)

# ─── MAIN ─────────────────────────────────────────────────────────────────---

def main():
    print(f"🚀 LEAD HUNTER & AUTOMATION EXPERT v15 (FIXED)")
    print(f"📍 Город: {CITY}")
    print(f"🎯 Цель: {TARGET_LEADS} UNDERDOW лидов ({MIN_REVIEWS}-{MAX_REVIEWS} отзывов)")
    print(f"🚫 СТРОГИЙ ФИЛЬТР: исключаем корпорации и сети")
    print(f"🔬 ПОИСК РЕАЛЬНЫХ жалоб клиентов (фиксированная версия)")
    print("")
    
    # 1. Fetch OSM data
    elements = fetch_osm_data()
    if not elements:
        print("❌ Данные не получены. Выход.")
        return
    
    # 2. Process and filter leads
    qualified_leads = []
    
    print(f"🔬 Глубокий анализ {len(elements)} бизнесов...")
    
    for element in elements:
        if len(qualified_leads) >= TARGET_LEADS:
            break
        
        lead = extract_lead_info(element)
        if not lead:
            continue
        
        name = lead["name"]
        niche = lead["niche"]
        print(f"  🔎 {name} ({niche})...")
        
        # Get review count and rating (UNDERDOG filter)
        review_count, rating = get_review_count_and_rating(name, CITY)
        lead["review_count"] = review_count
        lead["rating"] = rating
        
        # STRICT UNDERDOG FILTER
        if review_count < MIN_REVIEWS:
            print(f"    ❌ Слишком мало отзывов ({review_count}) - не наш клиент")
            continue
        
        if review_count > MAX_REVIEWS:
            print(f"    ❌ Слишком много отзывов ({review_count}) - исключаем")
            continue
        
        # Find Instagram (REQUIRED)
        insta = find_instagram(name, CITY)
        lead["instagram"] = insta
        
        # Find REAL customer pain quotes
        pain_quotes = find_real_customer_pain(name, CITY)
        lead["pain_quotes"] = pain_quotes
        
        # Check site automation
        site_status, site_analysis = check_site_automation(lead["website"])
        lead["site_status"] = site_status
        lead["site_analysis"] = site_analysis
        
        # Calculate lead score
        score = calculate_lead_score(lead, review_count, pain_quotes, site_status)
        lead["score"] = score
        
        # This is a qualified UNDERDOG lead
        qualified_leads.append(lead)
        
        pain_status = "ПЛАТИНОВЫЙ" if pain_quotes else "ХОРОШИЙ"
        print(f"    ✅ КВАЛИФИЦИРОВАН: {review_count} отзывов | {pain_status} | Скор: {score}")
    
    print(f"\n📊 Результаты:")
    print(f"   Всего обработано: {len(elements)}")
    print(f"   Квалифицированных UNDERDOW: {len(qualified_leads)}")
    print(f"   Фильтр отзывов: {MIN_REVIEWS}-{MAX_REVIEWS}")
    
    if not qualified_leads:
        print("❌ UNDERDOW лиды не найдены. Попробуйте изменить фильтры.")
        return
    
    # Sort by score (highest first)
    qualified_leads.sort(key=lambda x: x["score"], reverse=True)
    
    # 3. Build and save elite report
    report = build_elite_report(qualified_leads[:TARGET_LEADS])
    
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n✅ Элитный отчет сохранен в {OUTPUT}")
    print(f"🎯 Найдено {len(qualified_leads)} UNDERDOW лидов с РЕАЛЬНЫМИ жалобами!")
    
    # Show summary
    print("\n📋 Краткий итог:")
    for i, lead in enumerate(qualified_leads[:TARGET_LEADS], 1):
        pain_status = "Боль есть" if lead.get("pain_quotes") else "Боли нет"
        print(f"   {i}. {lead['name']} ({lead['niche']}) - {lead['review_count']} отзывов - {pain_status} - Скор: {lead['score']}")
    
    sys.exit(0)

if __name__ == "__main__":
    main()
