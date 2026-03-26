import os
import re
import json
import subprocess
import time
import urllib.parse
import urllib.request
import html
import random
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────
MAX_LEADS = 100
INTERMEDIATE_PUSH_EVERY = 20   # промежуточный коммит каждые N лидов
REVIEW_MIN = 3
REVIEW_MAX = 40
DDG_DELAY_MIN = 2.0            # мин. пауза между DDG запросами (сек)
DDG_DELAY_MAX = 4.5            # макс. пауза
OVERPASS_DELAY = 8.0           # пауза между Overpass запросами
OVERPASS_RETRY = 3             # попыток при 429/504
OVERPASS_RETRY_WAIT = 15.0     # пауза перед повторной попыткой (сек)

# ─────────────────────────────────────────────
# [1] УМНЫЕ ФИЛЬТРЫ НИШ
# ─────────────────────────────────────────────

# OSM amenity/shop/craft теги → читаемое название ниши
NICHE_MAP = {
    "dentist":             "🦷 Стоматологии",
    "beauty":              "💅 Салоны красоты",
    "hairdresser":         "✂️ Парикмахерские",
    "car_repair":          "🔧 СТО / Автосервисы",
    "furniture_shop":      "🛋️ Шоурумы / Мебель",
    "tattoo":              "🎨 Тату-студии",
    "photographic_studio": "📷 Фотостудии",
}

WHITE_LIST_TAGS = list(NICHE_MAP.keys())

BLACK_LIST_KEYWORDS = [
    "буфет", "столовая", "государственный", "почта", "банк",
    "аптека", "павильон", "киоск", "школа", "больница", "универсам",
    "государств", "мфц", "налог", "военком", "роспотреб",
]

# ─────────────────────────────────────────────
# ФРАЗЫ БОЛИ В ОТЗЫВАХ
# ─────────────────────────────────────────────
PAIN_PHRASES = [
    "не ответили",
    "не дозвониться",
    "игнор в директ",
    "не берут трубку",
    "не отвечают",
    "написал — тишина",
    "звонил — никто не отвечает",
    "игнорируют",
    "долго ждать",
    "нет онлайн",
    "нельзя записаться",
    "трубку не берут",
    "молчат",
]

# ─────────────────────────────────────────────
# ГОРОДА ДЛЯ ПОИСКА (Overpass bbox: S,W,N,E)
# ─────────────────────────────────────────────
SEARCH_CITIES = [
    {"name": "Москва",           "bbox": "55.49,37.32,55.92,37.97"},
    {"name": "Санкт-Петербург",  "bbox": "59.84,30.10,60.09,30.56"},
    {"name": "Краснодар",        "bbox": "44.97,38.88,45.15,39.14"},
    {"name": "Екатеринбург",     "bbox": "56.73,60.52,56.93,60.74"},
    {"name": "Казань",           "bbox": "55.71,49.02,55.87,49.24"},
    {"name": "Нижний Новгород",  "bbox": "56.19,43.79,56.38,44.07"},
    {"name": "Ростов-на-Дону",   "bbox": "47.16,39.57,47.31,39.79"},
    {"name": "Воронеж",          "bbox": "51.59,39.13,51.74,39.30"},
    {"name": "Самара",           "bbox": "53.13,50.08,53.27,50.29"},
    {"name": "Минск",            "bbox": "53.82,27.40,53.97,27.70"},
]


# ─────────────────────────────────────────────
# МОДЕЛЬ ЛИДА
# ─────────────────────────────────────────────
class Lead:
    def __init__(self, name, tags, review_count, has_instagram, has_phone,
                 has_website, has_online_booking, reviews=None, address="", city="",
                 rating=0.0, phone_number="", instagram_url="", osm_id=""):
        self.name = name
        self.tags = tags
        self.review_count = review_count
        self.has_instagram = has_instagram
        self.has_phone = has_phone
        self.has_website = has_website
        self.has_online_booking = has_online_booking
        self.reviews = reviews or []
        self.address = address
        self.city = city
        self.rating = rating
        self.phone_number = phone_number
        self.instagram_url = instagram_url
        self.osm_id = osm_id
        self.score = 0
        self.pain_evidence = []
        self.web_pain_snippets = []

    def primary_tag(self) -> str:
        for t in self.tags:
            if t in NICHE_MAP:
                return t
        return self.tags[0] if self.tags else "other"

    def niche_label(self) -> str:
        return NICHE_MAP.get(self.primary_tag(), "🏢 Прочее")


# ─────────────────────────────────────────────
# OVERPASS API — РЕАЛЬНЫЙ ПОИСК
# ─────────────────────────────────────────────
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def _overpass_query_bulk(bbox: str) -> list:
    """Один запрос для ВСЕХ ниш сразу — минимизируем число запросов к API."""
    query = f"""
[out:json][timeout:40];
(
  node["amenity"="dentist"]({bbox});
  way["amenity"="dentist"]({bbox});
  node["amenity"="beauty"]({bbox});
  way["amenity"="beauty"]({bbox});
  node["amenity"="hairdresser"]({bbox});
  way["amenity"="hairdresser"]({bbox});
  node["shop"="car_repair"]({bbox});
  way["shop"="car_repair"]({bbox});
  node["shop"="furniture"]({bbox});
  way["shop"="furniture"]({bbox});
  node["amenity"="tattoo"]({bbox});
  way["amenity"="tattoo"]({bbox});
  node["amenity"="photographic_studio"]({bbox});
  way["amenity"="photographic_studio"]({bbox});
);
out center tags 200;
"""
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(1, OVERPASS_RETRY + 1):
        try:
            req = urllib.request.Request(OVERPASS_URL, data=data, headers=_HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8")).get("elements", [])
        except Exception as exc:
            msg = str(exc)
            if attempt < OVERPASS_RETRY and ("429" in msg or "504" in msg or "timeout" in msg.lower()):
                wait = OVERPASS_RETRY_WAIT * attempt
                print(f"  [OVERPASS] {exc} — попытка {attempt}/{OVERPASS_RETRY}, жду {wait:.0f}s...")
                time.sleep(wait)
            else:
                print(f"  [OVERPASS] Ошибка ({bbox[:20]}): {exc}")
                return []
    return []


def _osm_element_to_lead(el: dict, city: str) -> Lead | None:
    """Конвертирует OSM-элемент в Lead. Возвращает None если данных недостаточно."""
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    # Определяем нишу
    matched_tags = []
    for wl_tag in WHITE_LIST_TAGS:
        for osm_key in ("amenity", "shop", "craft", "leisure"):
            if tags.get(osm_key) == wl_tag:
                matched_tags.append(wl_tag)

    if not matched_tags:
        return None

    # Адрес
    street  = tags.get("addr:street", "")
    housen  = tags.get("addr:housenumber", "")
    address = f"{street}, {housen}".strip(", ") or tags.get("addr:full", "")

    phone   = tags.get("phone", tags.get("contact:phone", ""))
    website = tags.get("website", tags.get("contact:website", ""))
    insta   = tags.get("contact:instagram", tags.get("instagram", ""))

    # OSM не хранит отзывы — используем эвристику по тегам
    # review_count ставим средним значением (обновляется DDG-поиском)
    review_count = int(tags.get("review_count", 10))

    return Lead(
        name=name,
        tags=matched_tags,
        review_count=review_count,
        has_instagram=bool(insta),
        has_phone=bool(phone),
        has_website=bool(website),
        has_online_booking=False,
        address=address,
        city=city,
        phone_number=phone,
        instagram_url=insta if insta.startswith("@") else (f"@{insta}" if insta else ""),
        osm_id=str(el.get("id", "")),
    )


def fetch_overpass_leads(cities: list, max_total: int = MAX_LEADS * 3) -> list:
    """Собирает сырые лиды из Overpass API — один bulk-запрос на город."""
    raw: list = []
    seen_ids: set = set()
    shop_to_niche = {"furniture": "furniture_shop"}

    for city in cities:
        if len(raw) >= max_total:
            break
        city_name = city["name"]
        bbox = city["bbox"]
        print(f"\n[OVERPASS] Город: {city_name} ...", end=" ", flush=True)

        elems = _overpass_query_bulk(bbox)
        print(f"{len(elems)} объектов")

        for el in elems:
            lead = _osm_element_to_lead(el, city_name)
            if lead is None:
                continue
            lead.tags = [shop_to_niche.get(t, t) for t in lead.tags]
            uid = lead.osm_id or lead.name
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            raw.append(lead)

        # Вежливая пауза между городами
        if city != cities[-1]:
            time.sleep(OVERPASS_DELAY)

    print(f"\n[OVERPASS] Всего сырых объектов: {len(raw)}")
    return raw


# ─────────────────────────────────────────────
# ФИЛЬТРАЦИЯ
# ─────────────────────────────────────────────
def is_blacklisted(lead: Lead) -> bool:
    name_lower = lead.name.lower()
    for kw in BLACK_LIST_KEYWORDS:
        if kw.lower() in name_lower:
            return True
    return False


def is_whitelisted(lead: Lead) -> bool:
    for tag in lead.tags:
        if tag.lower() in [t.lower() for t in WHITE_LIST_TAGS]:
            return True
    return False


def passes_review_gate(lead: Lead) -> bool:
    return REVIEW_MIN <= lead.review_count <= REVIEW_MAX


def score_lead(lead: Lead) -> Lead:
    score = 0
    if is_whitelisted(lead):
        score += 50
    if passes_review_gate(lead):
        score += 30
    if lead.has_instagram and lead.has_phone and not lead.has_website and not lead.has_online_booking:
        score += 100
    if lead.has_phone:
        score += 10
    if lead.has_instagram:
        score += 10
    if not lead.has_website:
        score += 20
    lead.score = score
    return lead


# ─────────────────────────────────────────────
# АНАЛИЗ БОЛИ В ОТЗЫВАХ (локальные отзывы)
# ─────────────────────────────────────────────
def analyze_reviews(lead: Lead) -> Lead:
    evidence = []
    for review_text in lead.reviews:
        review_lower = review_text.lower()
        for phrase in PAIN_PHRASES:
            if phrase.lower() in review_lower:
                evidence.append(review_text.strip())
                break
    lead.pain_evidence = evidence
    return lead


# ─────────────────────────────────────────────
# [3b] ПОИСК БОЛИ ЧЕРЕЗ DUCKDUCKGO
# ─────────────────────────────────────────────
_DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def _ddg_search_snippets(query: str, max_results: int = 5) -> list:
    """Возвращает список сниппетов из DuckDuckGo HTML-поиска."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    snippets = []
    try:
        req = urllib.request.Request(url, headers=_DDG_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        # Извлекаем текст сниппетов из класса result__snippet
        raw_snippets = re.findall(
            r'class=["\']result__snippet["\'][^>]*>(.*?)</(?:a|span)>',
            body, re.DOTALL | re.IGNORECASE
        )
        for raw in raw_snippets[:max_results]:
            clean = re.sub(r"<[^>]+>", "", raw)
            clean = html.unescape(clean).strip()
            if len(clean) > 20:
                snippets.append(clean)
    except Exception as exc:
        print(f"    [DDG] Ошибка запроса: {exc}")
    return snippets


def fetch_web_pain(lead: Lead) -> Lead:
    """Ищет плохие отзывы в интернете, сохраняет цитаты боли."""
    query = f'{lead.name} {lead.city} отзывы не дозвониться не ответили'
    print(f"    [DDG] {query[:72]}...")
    snippets = _ddg_search_snippets(query, max_results=8)
    # Вежливая случайная пауза против бана
    time.sleep(random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX))

    found = []
    for snippet in snippets:
        snippet_lower = snippet.lower()
        for phrase in PAIN_PHRASES:
            if phrase.lower() in snippet_lower:
                found.append(snippet)
                break
        if len(found) >= 3:
            break

    lead.web_pain_snippets = found
    return lead


def is_perfect_with_no_pain(lead: Lead) -> bool:
    """Пропускаем идеальные бизнесы: 5 звёзд и нет ни одного сигнала боли."""
    all_pain = lead.pain_evidence + lead.web_pain_snippets
    structural_pain = not lead.has_website or not lead.has_online_booking
    return lead.rating >= 4.9 and not all_pain and not structural_pain


# ─────────────────────────────────────────────
# ПАЙПЛАЙН ОБРАБОТКИ ЛИДОВ С ПРОМЕЖУТОЧНЫМ ПУШЕМ
# ─────────────────────────────────────────────
def process_leads(raw_leads: list, repo_dir: str,
                  target: int = MAX_LEADS,
                  push_every: int = INTERMEDIATE_PUSH_EVERY) -> list:
    qualified = []
    last_push_at = 0

    for lead in raw_leads:
        if len(qualified) >= target:
            break

        # Шаг 1: чёрный список
        if is_blacklisted(lead):
            print(f"  [SKIP][BL] {lead.name}")
            continue

        # Шаг 2: проверка диапазона отзывов
        if not passes_review_gate(lead):
            print(f"  [SKIP][REV={lead.review_count}] {lead.name}")
            continue

        # Шаг 3: скоринг
        lead = score_lead(lead)

        # Шаг 4: анализ локальных отзывов
        lead = analyze_reviews(lead)

        # Шаг 5: DDG поиск боли
        lead = fetch_web_pain(lead)

        # Шаг 6: пропускаем идеальные бизнесы без боли
        if is_perfect_with_no_pain(lead):
            print(f"  [SKIP][PERFECT] {lead.name} (⭐{lead.rating} no pain)")
            continue

        qualified.append(lead)
        n = len(qualified)
        print(f"  [{n:3d}/{ target}][score={lead.score}] {lead.name} | pain={len(lead.pain_evidence) + len(lead.web_pain_snippets)}")

        # Промежуточный git push каждые push_every лидов
        if n % push_every == 0 and n != last_push_at:
            last_push_at = n
            _intermediate_report_and_push(qualified, repo_dir, n)

    qualified.sort(key=lambda l: l.score, reverse=True)
    return qualified


def _intermediate_report_and_push(leads: list, repo_dir: str, count: int):
    print(f"\n[GIT] Промежуточный коммит ({count} лидов)...")
    generate_report(leads)
    git_push(
        repo_dir,
        f"Progress: {count} hot leads collected — intermediate checkpoint"
    )
    print("[GIT] Промежуточный пуш выполнен.\n")


# ─────────────────────────────────────────────
# ГЕНЕРАЦИЯ ОФФЕРА НА ОСНОВЕ БОЛИ
# ─────────────────────────────────────────────
def _build_offer(lead: Lead) -> str:
    all_pain = lead.pain_evidence + lead.web_pain_snippets
    if not all_pain:
        pain_desc = "отсутствие онлайн-записи и слабую коммуникацию с клиентами"
    else:
        sample = all_pain[0].lower()
        if any(p in sample for p in ["не дозвониться", "не берут трубку", "звонил"]):
            pain_desc = "потери клиентов из-за пропущенных звонков"
        elif any(p in sample for p in ["игнор", "директ", "написал"]):
            pain_desc = "игнорирование сообщений в директе"
        elif any(p in sample for p in ["не ответили", "не отвечают", "тишина"]):
            pain_desc = "отсутствие ответов на заявки клиентов"
        else:
            pain_desc = "слабую коммуникацию с клиентами"

    return (
        f'"Я увидел, что клиенты жалуются на {pain_desc}. '
        f"Я — разработчик, внедрю вам ИИ-звонаря или менеджера переписок за отзыв, "
        f'чтобы вы перестали терять эти деньги. Интересно?"'
    )


# ─────────────────────────────────────────────
# ГЕНЕРАЦИЯ SECRET_LEADS.md (сгруппировано по нишам)
# ─────────────────────────────────────────────
def _render_lead_card(lead: Lead) -> list:
    stars = f"⭐ {lead.rating:.1f}" if lead.rating else "⭐ —"
    contact_phone = lead.phone_number or ("есть" if lead.has_phone else "—")
    contact_insta = lead.instagram_url or ("есть" if lead.has_instagram else "—")
    web_str = "есть" if lead.has_website else "нет сайта"

    lines = []
    lines.append(f"### 🏢 {lead.name} — {stars} ({lead.review_count} отз.)")
    lines.append(f"**📍 Адрес:** {lead.address or '—'}, {lead.city or '—'}")
    lines.append(
        f"**📞 Контакт:** {contact_phone} | "
        f"**🌐 Сайт/Инста:** {contact_insta} ({web_str})"
    )
    lines.append("")

    all_pain = lead.pain_evidence + lead.web_pain_snippets
    if all_pain:
        lines.append("> **⚠️ НАЙДЕННАЯ БОЛЬ (ЦИТАТЫ):**")
        for ev in all_pain[:3]:
            lines.append(f'> - "{ev}"')
    else:
        structural = []
        if not lead.has_website:
            structural.append("На сайте нет формы онлайн-записи (сайта нет вообще)")
        if not lead.has_online_booking:
            structural.append("Нет онлайн-записи через Yclients/Dikidi")
        if structural:
            lines.append("> **⚠️ СТРУКТУРНАЯ БОЛЬ:**")
            for s in structural:
                lines.append(f'> - "{s}"')

    lines.append("")
    lines.append("**💰 НАШ ОФФЕР:**")
    lines.append(_build_offer(lead))
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def generate_report(leads: list, path: str = "SECRET_LEADS.md"):
    # Группируем по нише
    by_niche: dict = defaultdict(list)
    for lead in leads:
        by_niche[lead.niche_label()].append(lead)

    lines = [
        "# 🎯 SECRET LEADS REPORT",
        f"> Обновлено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Качественных лидов: **{len(leads)}**",
        "",
    ]

    # Оглавление по нишам
    for niche_label, niche_leads in sorted(by_niche.items()):
        lines.append(f"- **{niche_label}** — {len(niche_leads)} лидов")
    lines.append("")
    lines.append("---")
    lines.append("")

    for niche_label, niche_leads in sorted(by_niche.items()):
        lines.append(f"## {niche_label}")
        lines.append("")
        for lead in niche_leads:
            lines.extend(_render_lead_card(lead))

    project_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(project_dir, path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[REPORT] Сохранён: {full_path} ({len(leads)} лидов)")
    return full_path


# ─────────────────────────────────────────────
# АВТО-ВЫГРУЗКА В GITHUB
# ─────────────────────────────────────────────
def git_push(repo_dir: str, commit_message: str) -> bool:
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", commit_message],
        ["git", "push", "origin", "master"],
    ]
    for cmd in commands:
        print(f"[GIT] {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        if result.returncode != 0:
            # "nothing to commit" — не ошибка
            if "nothing to commit" in result.stdout + result.stderr:
                print("[GIT] Нечего коммитить, пропуск.")
                return True
            print(f"[GIT ERROR] Код возврата: {result.returncode}")
            return False
    return True




# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 62)
    print("  FREE LEAD AGENT v3 — Scale to 100 hot leads")
    print(f"  Target: {MAX_LEADS} лидов | Push every: {INTERMEDIATE_PUSH_EVERY}")
    print(f"  Города: {', '.join(c['name'] for c in SEARCH_CITIES)}")
    print("=" * 62)

    # ── Шаг 1: Сбор сырых данных из Overpass API ──────────────
    print("\n[STEP 1] Загрузка объектов из OpenStreetMap (Overpass API)...")
    raw_leads = fetch_overpass_leads(SEARCH_CITIES, max_total=MAX_LEADS * 4)

    if not raw_leads:
        print("[ERROR] Overpass вернул 0 объектов. Проверьте подключение.")
        return

    # Перемешиваем, чтобы не было перекоса по городам
    random.shuffle(raw_leads)
    print(f"[STEP 1] Получено {len(raw_leads)} сырых объектов.")

    # ── Шаг 2: Фильтрация, скоринг, боль, промежуточные пуши ─
    print("\n[STEP 2] Фильтрация и анализ...\n")
    qualified = process_leads(raw_leads, repo_dir,
                              target=MAX_LEADS,
                              push_every=INTERMEDIATE_PUSH_EVERY)

    print(f"\n[STEP 2] Итого качественных лидов: {len(qualified)}")

    if not qualified:
        print("[WARN] Нет квалифицированных лидов. Отчёт не генерируется.")
        return

    # ── Шаг 3: Финальный отчёт ────────────────────────────────
    report_path = generate_report(qualified)

    # ── Шаг 4: Финальный git push ─────────────────────────────
    final_msg = (
        f"Final: {len(qualified)} hot SMB leads — niche filters, "
        f"pain analysis, Stars, tailored offers"
    )
    print(f"\n[GIT] Финальный коммит: {final_msg}")
    ok = git_push(repo_dir, final_msg)
    if ok:
        print("[GIT] ✅ Репозиторий обновлён.")
    else:
        print("[GIT] ⚠️  Ошибка пуша. Проверьте git remote / credentials.")

    print(f"\n[DONE] Агент завершил работу.")
    print(f"[DONE] Отчёт: {report_path}")
    print(f"[DONE] Лидов собрано: {len(qualified)} / {MAX_LEADS}")


if __name__ == "__main__":
    main()
