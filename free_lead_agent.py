import os
import re
import json
import subprocess
import time
import urllib.parse
import urllib.request
import html
from datetime import datetime

# ─────────────────────────────────────────────
# [1] УМНЫЕ ФИЛЬТРЫ НИШ
# ─────────────────────────────────────────────
WHITE_LIST_TAGS = [
    "dentist",
    "beauty",
    "hairdresser",
    "car_repair",
    "furniture_shop",
    "tattoo",
    "photographic_studio",
]

BLACK_LIST_KEYWORDS = [
    "буфет",
    "столовая",
    "государственный",
    "почта",
    "банк",
    "аптека",
    "павильон",
    "киоск",
    "школа",
    "больница",
    "универсам",
]

# ─────────────────────────────────────────────
# [3] ФРАЗЫ БОЛИ В ОТЗЫВАХ
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
]


# ─────────────────────────────────────────────
# МОДЕЛЬ ЛИДА
# ─────────────────────────────────────────────
class Lead:
    def __init__(self, name, tags, review_count, has_instagram, has_phone,
                 has_website, has_online_booking, reviews=None, address="", city="",
                 rating=0.0, phone_number="", instagram_url=""):
        self.name = name
        self.tags = tags                        # list[str] — OSM/2GIS категории
        self.review_count = review_count        # int
        self.has_instagram = has_instagram      # bool
        self.has_phone = has_phone              # bool
        self.has_website = has_website          # bool
        self.has_online_booking = has_online_booking  # bool (Yclients/Dikidi)
        self.reviews = reviews or []            # list[str] — тексты отзывов
        self.address = address
        self.city = city
        self.rating = rating                    # float, например 4.2
        self.phone_number = phone_number        # str, например "+7 (918) 123-45-67"
        self.instagram_url = instagram_url      # str, например "@beauty_lira"
        self.score = 0
        self.pain_evidence = []
        self.web_pain_snippets = []             # list[str] — цитаты из DuckDuckGo


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


# ─────────────────────────────────────────────
# [2] ПРОВЕРКА НА МАЛЫЙ БИЗНЕС
# ─────────────────────────────────────────────
REVIEW_MIN = 3
REVIEW_MAX = 40


def passes_review_gate(lead: Lead) -> bool:
    return REVIEW_MIN <= lead.review_count <= REVIEW_MAX


def score_lead(lead: Lead) -> Lead:
    score = 0

    # Белый список ниш
    if is_whitelisted(lead):
        score += 50

    # Диапазон отзывов — признак живого малого бизнеса
    if passes_review_gate(lead):
        score += 30

    # Есть Instagram + телефон, но НЕТ сайта и НЕТ онлайн-записи → приоритетный лид
    if lead.has_instagram and lead.has_phone and not lead.has_website and not lead.has_online_booking:
        score += 100

    # Отдельные бонусы
    if lead.has_phone:
        score += 10
    if lead.has_instagram:
        score += 10
    if not lead.has_website:
        score += 20

    lead.score = score
    return lead


# ─────────────────────────────────────────────
# [3] АНАЛИЗ БОЛИ В ОТЗЫВАХ (локальные отзывы)
# ─────────────────────────────────────────────
def analyze_reviews(lead: Lead) -> Lead:
    evidence = []
    for review_text in lead.reviews:
        review_lower = review_text.lower()
        for phrase in PAIN_PHRASES:
            if phrase.lower() in review_lower:
                evidence.append(review_text.strip())
                break  # одна фраза на отзыв достаточно
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
    """Ищет плохие отзывы в интернете и сохраняет цитаты боли."""
    query = f'{lead.name} {lead.city} отзывы не дозвониться не ответили'
    print(f"    [DDG] Поиск: {query[:70]}...")
    snippets = _ddg_search_snippets(query, max_results=8)
    time.sleep(1.2)  # вежливая пауза между запросами

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


# ─────────────────────────────────────────────
# ПАЙПЛАЙН ОБРАБОТКИ ЛИДОВ
# ─────────────────────────────────────────────
def process_leads(raw_leads: list) -> list:
    qualified = []
    for lead in raw_leads:
        # Шаг 1: чёрный список
        if is_blacklisted(lead):
            print(f"  [SKIP][BLACKLIST] {lead.name}")
            continue

        # Шаг 2: проверка диапазона отзывов
        if not passes_review_gate(lead):
            print(f"  [SKIP][REVIEWS={lead.review_count}] {lead.name}")
            continue

        # Шаг 3: скоринг
        lead = score_lead(lead)

        # Шаг 4: анализ боли (локальные отзывы)
        lead = analyze_reviews(lead)

        # Шаг 5: поиск боли в интернете через DuckDuckGo
        lead = fetch_web_pain(lead)

        qualified.append(lead)
        print(f"  [OK][score={lead.score}] {lead.name} | pain_local={len(lead.pain_evidence)} | pain_web={len(lead.web_pain_snippets)}")

    # Сортировка по убыванию score
    qualified.sort(key=lambda l: l.score, reverse=True)
    return qualified


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
# ГЕНЕРАЦИЯ SECRET_LEADS.md
# ─────────────────────────────────────────────
def generate_report(leads: list, path: str = "SECRET_LEADS.md"):
    lines = [
        "# 🎯 SECRET LEADS REPORT",
        f"> Обновлено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Качественных лидов: **{len(leads)}**",
        "",
        "---",
        "",
    ]

    for lead in leads:
        stars = f"⭐ {lead.rating:.1f}" if lead.rating else "⭐ —"
        contact_phone = lead.phone_number or ("есть" if lead.has_phone else "—")
        contact_insta = lead.instagram_url or ("есть" if lead.has_instagram else "—")
        web_str = "есть" if lead.has_website else "нет сайта"

        lines.append(f"### 🏢 {lead.name} — {stars} ({lead.review_count} отз.)")
        lines.append(f"**📍 Адрес:** {lead.address or '—'}, {lead.city or '—'}")
        lines.append(
            f"**📞 Контакт:** {contact_phone} | "
            f"**🌐 Сайт/Инста:** {contact_insta} ({web_str})"
        )
        lines.append("")

        # Собираем все цитаты боли
        all_pain = lead.pain_evidence + lead.web_pain_snippets
        if all_pain:
            lines.append("> **⚠️ НАЙДЕННАЯ БОЛЬ (ЦИТАТЫ):**")
            for ev in all_pain[:3]:
                lines.append(f'> - "{ev}"')
        else:
            # Структурная боль — нет сайта / нет онлайн-записи
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
        lines.append(f"**💰 НАШ ОФФЕР:**")
        lines.append(_build_offer(lead))
        lines.append("")
        lines.append("---")
        lines.append("")

    report_text = "\n".join(lines)

    project_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(project_dir, path)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n[REPORT] Сохранён: {full_path}")
    return full_path


# ─────────────────────────────────────────────
# [4] АВТО-ВЫГРУЗКА В GITHUB
# ─────────────────────────────────────────────
def git_push(repo_dir: str, commit_message: str):
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", commit_message],
        ["git", "push", "origin", "master"],
    ]
    for cmd in commands:
        print(f"\n[GIT] {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        if result.returncode != 0:
            print(f"[GIT ERROR] Код возврата: {result.returncode}")
            return False
    return True


# ─────────────────────────────────────────────
# ДЕМО-ДАННЫЕ ДЛЯ ТЕСТА
# ─────────────────────────────────────────────
DEMO_LEADS = [
    # Должен пройти — приоритетный (нет сайта, есть insta+phone)
    Lead(
        name="Студия красоты «Лира»",
        tags=["beauty", "hairdresser"],
        review_count=12,
        has_instagram=True,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=[
            "Отличный мастер, жаль не дозвониться никогда",
            "Пришла без записи, всё ок",
        ],
        address="ул. Ленина, 14",
        city="Краснодар",
        rating=4.3,
        phone_number="+7 (861) 200-11-22",
        instagram_url="@lira_beauty_krd",
    ),
    # Должен пройти — стоматология с болью
    Lead(
        name="Дентал Плюс",
        tags=["dentist"],
        review_count=27,
        has_instagram=True,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=[
            "Написал в директ — игнор в директ, никто не ответил",
            "Запись через администратора, удобно",
        ],
        address="пр. Мира, 8",
        city="Ростов-на-Дону",
        rating=4.1,
        phone_number="+7 (863) 300-44-55",
        instagram_url="@dental_plus_rostov",
    ),
    # Должен пройти — автосервис
    Lead(
        name="Авто Мастер",
        tags=["car_repair"],
        review_count=18,
        has_instagram=False,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=["Хорошо сделали, цена норм"],
        address="ул. Гагарина, 22",
        city="Воронеж",
        rating=4.0,
        phone_number="+7 (473) 111-22-33",
    ),
    # ДОЛЖЕН БЫТЬ ОТФИЛЬТРОВАН — чёрный список
    Lead(
        name="Столовая №7",
        tags=["cafe"],
        review_count=15,
        has_instagram=False,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=[],
        address="ул. Советская, 1",
        city="Москва",
    ),
    # ДОЛЖЕН БЫТЬ ОТФИЛЬТРОВАН — слишком мало отзывов
    Lead(
        name="Тату-студия «Игла»",
        tags=["tattoo"],
        review_count=1,
        has_instagram=True,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=[],
        address="пер. Садовый, 3",
        city="Самара",
    ),
    # ДОЛЖЕН БЫТЬ ОТФИЛЬТРОВАН — слишком много отзывов (сеть)
    Lead(
        name="Сеть парикмахерских «Шарм»",
        tags=["hairdresser"],
        review_count=250,
        has_instagram=True,
        has_phone=True,
        has_website=True,
        has_online_booking=True,
        reviews=[],
        address="ул. Пушкина, 10",
        city="Екатеринбург",
    ),
    # Должен пройти — фотостудия
    Lead(
        name="Фотостудия «Свет»",
        tags=["photographic_studio"],
        review_count=9,
        has_instagram=True,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=["Не ответили на заявку уже 3 дня"],
        address="бул. Цветной, 5",
        city="Казань",
        rating=4.6,
        phone_number="+7 (843) 500-66-77",
        instagram_url="@svet_photo_kzn",
    ),
    # Должен пройти — мебельный
    Lead(
        name="Мебель «Уют»",
        tags=["furniture_shop"],
        review_count=14,
        has_instagram=True,
        has_phone=True,
        has_website=False,
        has_online_booking=False,
        reviews=["Не берут трубку, пришлось ехать лично"],
        address="ул. Строителей, 33",
        city="Нижний Новгород",
        rating=3.9,
        phone_number="+7 (831) 400-88-99",
        instagram_url="@uyut_mebel_nn",
    ),
    # ДОЛЖЕН БЫТЬ ОТФИЛЬТРОВАН — государственный
    Lead(
        name="Государственный центр занятости",
        tags=["government"],
        review_count=10,
        has_instagram=False,
        has_phone=True,
        has_website=True,
        has_online_booking=False,
        reviews=[],
        address="ул. Октябрьская, 2",
        city="Волгоград",
    ),
]


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  FREE LEAD AGENT — Hybrid Parser")
    print("  Фильтры: ниша + малый бизнес + боль в отзывах")
    print("=" * 60)
    print(f"\n[INFO] Входящих лидов: {len(DEMO_LEADS)}")
    print("[INFO] Обработка...\n")

    qualified_leads = process_leads(DEMO_LEADS)

    print(f"\n[INFO] Прошло фильтры: {len(qualified_leads)} лидов")

    if not qualified_leads:
        print("[WARN] Нет квалифицированных лидов. Отчёт не генерируется.")
        return

    report_path = generate_report(qualified_leads)

    QUALITY_THRESHOLD = 5
    if len(qualified_leads) >= QUALITY_THRESHOLD:
        print(f"\n[INFO] Найдено {len(qualified_leads)} лидов (≥{QUALITY_THRESHOLD}) — запускаю git push...")
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        commit_msg = (
            "Update: Added stars, review snippets and tailored offers"
        )
        success = git_push(repo_dir, commit_msg)
        if success:
            print("\n[GIT] Успешно выгружено в репозиторий.")
        else:
            print("\n[GIT] Ошибка при выгрузке. Проверьте git remote и права доступа.")
    else:
        print(f"\n[INFO] Лидов {len(qualified_leads)} < {QUALITY_THRESHOLD}. Git push не выполняется.")

    print("\n[DONE] Агент завершил работу.")
    print(f"[DONE] Отчёт: {report_path}")


if __name__ == "__main__":
    main()
