# -*- coding: utf-8 -*-
"""
BrainStorm — ai_client.py v8
Улучшенная генерация вопросов через GigaChat:
  • Строгая валидация correct-индекса (0-based, проверка фактической позиции)
  • Дедупликация по MD5-хешу текста вопроса
  • Для Своей игры — батч-генерация всех вопросов категории за 1 запрос
  • Fallback-банк с 40+ вопросами
"""

import os, re, json, random, hashlib, logging
from typing import Optional, List

logger = logging.getLogger(__name__)

DIFFICULTY_LABELS = {
    "easy":   "ЛЁГКИЙ — простые факты, известные любому школьнику",
    "medium": "СРЕДНИЙ — требует кругозора эрудированного взрослого",
    "hard":   "СЛОЖНЫЙ — экспертные знания, узкоспециальные детали",
}

SYSTEM_PROMPT = """\
Ты — профессиональный составитель вопросов для викторины. Все вопросы ТОЛЬКО на русском языке.

АБСОЛЮТНЫЕ ПРАВИЛА (нарушение делает ответ некорректным):
1. Отвечай ТОЛЬКО валидным JSON-объектом. Никакого markdown, никаких ```, никаких пояснений.
2. "correct" — ЦЕЛОЕ ЧИСЛО (0, 1, 2 или 3), это ИНДЕКС правильного ответа в массиве "options" считая с нуля.
   Например: если правильный ответ стоит ВТОРЫМ в списке, то correct = 1 (не 2!).
3. Перед выводом ПРОВЕРЬ СЕБЯ: options[correct] — это действительно правильный ответ?
4. Все варианты в "options" РАЗЛИЧНЫ между собой.
5. Правильный ответ фактически верен — не выдумывай факты.
6. Неправильные варианты правдоподобны, но точно неверны.
7. Вопросы в одном ответе УНИКАЛЬНЫ — не повторяй ни один факт.
"""


def _q_hash(q: dict) -> str:
    """MD5 первых 60 символов вопроса для дедупликации."""
    key = (q.get("question") or "").strip().lower()[:60]
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]


def build_prompt(topic: str, count: int, difficulty: str, num_options: int,
                 used_hashes: Optional[List[str]] = None) -> str:
    diff_label = DIFFICULTY_LABELS.get(difficulty, DIFFICULTY_LABELS["medium"])
    max_idx    = num_options - 1

    # Пример для модели — всегда верный (correct=1 → второй элемент)
    example_opts = ["Ag", "Au", "Fe", "Cu"][:num_options]
    example = {
        "question":    "Какой химический символ у золота?",
        "options":     example_opts,
        "correct":     1,          # Au — второй в списке, индекс 1
        "explanation": "Au — от латинского Aurum. Золото известно людям более 5000 лет.",
        "hint":        "Этот благородный металл жёлтого цвета — символ богатства.",
    }
    example_json = json.dumps({"questions": [example]}, ensure_ascii=False, indent=2)

    used_block = ""
    if used_hashes:
        used_block = (
            "\n⛔ ЗАПРЕЩЕНО повторять вопросы, похожие на уже использованные. "
            f"Идентификаторы использованных вопросов (игнорируй их содержание, "
            f"просто не повторяй факты, которые в них могли быть): {', '.join(used_hashes[-15:])}\n"
        )

    return (
        f'Создай РОВНО {count} уникальных вопросов по теме: "{topic}".\n'
        f'Сложность: {diff_label}.\n'
        f'Каждый вопрос: РОВНО {num_options} вариантов ответа.\n'
        f'{used_block}\n'
        f'ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ:\n'
        f'• "correct" = целое число от 0 до {max_idx} — это ПОЗИЦИЯ правильного ответа в массиве "options" (считая с нуля).\n'
        f'• options["correct"] — ТОТ САМЫЙ правильный ответ. Проверь это перед выводом.\n'
        f'• {num_options} вариантов в "options" — все разные строки.\n'
        f'• Вопросы уникальны: не повторяй факты между вопросами в этом же ответе.\n'
        f'• "explanation" — 1-2 интересных факта (не пересказывай вопрос).\n'
        f'• "hint" — 1 предложение, наводящее на ответ, НЕ называющее его прямо.\n\n'
        f'Эталонный пример формата:\n{example_json}\n\n'
        f'Создай {count} вопросов по теме "{topic}". Только JSON, без лишнего текста:'
    )


def build_hint_prompt(question_text: str) -> str:
    return (
        f"Дай одну подсказку (1-2 предложения) к вопросу викторины. "
        f"НЕ называй правильный ответ — только наведи на мысль.\n"
        f"Вопрос: {question_text}\nПодсказка:"
    )


# ── GigaChat ──────────────────────────────────────────────────────────────────

def _call_gigachat(user_prompt: str, system: str = SYSTEM_PROMPT) -> str:
    creds = os.getenv("GIGACHAT_CREDENTIALS", "")
    scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    if not creds:
        raise RuntimeError("GIGACHAT_CREDENTIALS не задан")
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole
    msgs = [
        Messages(role=MessagesRole.SYSTEM, content=system),
        Messages(role=MessagesRole.USER,   content=user_prompt),
    ]
    with GigaChat(credentials=creds, scope=scope, verify_ssl_certs=False) as gc:
        resp = gc.chat(Chat(messages=msgs))
    return resp.choices[0].message.content


# ── Парсинг ───────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> str:
    text = raw.strip().lstrip('\ufeff')
    cb = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if cb:
        text = cb.group(1).strip()
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e > s:
        text = text[s:e+1]
    # Убираем trailing commas
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def _parse_response(raw: str, num_options: int) -> list:
    text = _extract_json(raw)
    try:
        data = json.loads(text)
        # Ищем список вопросов
        for key in ("questions", "вопросы", "items"):
            v = data.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        # Одиночный вопрос
        if "question" in data and "options" in data:
            return [data]
        # Любой список словарей с вопросом
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "question" in v[0]:
                return v
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error: %s | raw[:200]: %s", exc, text[:200])

    # Regex fallback
    qs = []
    for m in re.finditer(r'\{[^{}]*?"question"[^{}]*?\}', raw, re.DOTALL):
        chunk = re.sub(r',\s*([}\]])', r'\1', m.group(0))
        try:
            obj = json.loads(chunk)
            if "question" in obj and "options" in obj:
                qs.append(obj)
        except Exception:
            pass
    if qs:
        logger.info("Regex fallback: %d questions", len(qs))
    return qs


# ── Валидация ─────────────────────────────────────────────────────────────────

def _smart_fix_correct(q: dict, num_options: int) -> int:
    c = q.get("correct", 0)
    opts = q.get("options", [])

    # Уже число в диапазоне
    if isinstance(c, int) and 0 <= c < num_options:
        return c

    # Строка-число
    if isinstance(c, str) and c.strip().isdigit():
        idx = int(c.strip())
        if 0 <= idx < num_options:
            return idx
        if 1 <= idx <= num_options:  # 1-based
            return idx - 1

    # Строка совпадает с вариантом ответа
    if isinstance(c, str):
        c_clean = c.strip().lower()
        for i, opt in enumerate(opts):
            if str(opt).strip().lower() == c_clean:
                return i

    # Буква A/B/C/D
    if isinstance(c, str) and len(c.strip()) == 1 and c.strip().upper().isalpha():
        idx = ord(c.strip().upper()) - ord('A')
        if 0 <= idx < num_options:
            return idx

    logger.warning("Не удалось определить correct=%r, ставим 0", c)
    return 0


def _fix_indexing_batch(questions: list, num_options: int) -> list:
    """Если ВСЕ вопросы имеют 1-based индексы — конвертируем пакетно."""
    corrects = [q.get("correct", 0) for q in questions if isinstance(q.get("correct"), int)]
    if corrects and min(corrects) >= 1 and max(corrects) == num_options:
        logger.info("Batch 1→0 index conversion")
        for q in questions:
            if isinstance(q.get("correct"), int) and q["correct"] > 0:
                q["correct"] -= 1
    return questions


def _validate_question(q: dict, num_options: int) -> Optional[dict]:
    """Валидирует и исправляет один вопрос. Возвращает None если не исправить."""
    if not isinstance(q, dict):
        return None

    question = str(q.get("question") or "").strip()
    if len(question) < 10:
        return None

    opts = q.get("options") or []
    if not isinstance(opts, list):
        return None

    opts = [str(o).strip() for o in opts if str(o).strip()]

    # Дополняем / обрезаем
    while len(opts) < num_options:
        opts.append(f"Вариант {chr(65 + len(opts))}")
    opts = opts[:num_options]

    # Убираем дубли среди вариантов
    seen, clean_opts = set(), []
    for o in opts:
        ol = o.lower()
        if ol not in seen:
            seen.add(ol)
            clean_opts.append(o)
        else:
            clean_opts.append(f"Другой вариант {chr(65 + len(clean_opts))}")

    q = q.copy()
    q["options"]  = clean_opts
    q["question"] = question
    q["correct"]  = _smart_fix_correct(q, num_options)

    # Убедимся что correct в диапазоне
    if not (0 <= q["correct"] < len(clean_opts)):
        q["correct"] = 0

    q["explanation"] = str(q.get("explanation") or "").strip()
    q["hint"]        = str(q.get("hint") or "").strip()

    return q


def _deduplicate(questions: list, seen: set) -> list:
    result = []
    for q in questions:
        h = _q_hash(q)
        if h not in seen:
            seen.add(h)
            result.append(q)
        else:
            logger.debug("Дубль пропущен: %s", q.get("question","")[:50])
    return result


def _mark_bonus(questions: list, chance: float = 0.15) -> list:
    return [{**q, "bonus": random.random() < chance} for q in questions]


# ── Публичные функции ─────────────────────────────────────────────────────────

# Глобальный кеш хешей в рамках сессии сервера
_session_hashes: set = set()


def generate_questions(topic: str, count: int, difficulty: str, num_options: int,
                       used_questions: Optional[list] = None) -> list:
    """
    Генерирует вопросы через GigaChat или возвращает fallback.
    Для Своей игры вызывается с count=n_rows, что гарантирует уникальность в категории.
    """
    global _session_hashes

    used_hashes = [_q_hash(q) for q in (used_questions or [])]

    if os.getenv("GIGACHAT_CREDENTIALS"):
        try:
            prompt = build_prompt(topic, count, difficulty, num_options, used_hashes)
            logger.info("📤 GigaChat | тема=%s | кол=%d | diff=%s | opts=%d",
                        topic, count, difficulty, num_options)
            raw    = _call_gigachat(prompt)
            logger.info("📥 Ответ: %d символов", len(raw))

            raw_qs = _parse_response(raw, num_options)
            raw_qs = _fix_indexing_batch(raw_qs, num_options)

            validated = []
            for q in raw_qs:
                fixed = _validate_question(q, num_options)
                if fixed:
                    validated.append(fixed)

            # Глобальная дедупликация
            validated = _deduplicate(validated, _session_hashes)

            if validated:
                logger.info("✅ GigaChat: %d/%d вопросов прошли валидацию",
                            len(validated), len(raw_qs))
                return _mark_bonus(validated)

            logger.warning("⚠️ Все вопросы GigaChat отфильтрованы → fallback")
        except Exception as exc:
            logger.warning("⚠️ GigaChat ошибка: %s → fallback", exc)

    logger.warning("⚠️ Fallback-банк вопросов")
    return _get_fallback_questions(count, num_options)


def _get_fallback_questions(count: int, num_options: int) -> list:
    global _session_hashes
    pool = [q.copy() for q in _FALLBACK]
    random.shuffle(pool)
    result = []
    for q in pool:
        if len(result) >= count:
            break
        opts = (q["options"] * 2)[:num_options]
        while len(opts) < num_options:
            opts.append(f"Вариант {len(opts)+1}")
        q = q.copy()
        q["options"] = opts
        q["correct"] = min(q.get("correct", 0), num_options - 1)
        fixed = _validate_question(q, num_options)
        if not fixed:
            continue
        h = _q_hash(fixed)
        if h in _session_hashes:
            continue
        _session_hashes.add(h)
        result.append(fixed)
    return _mark_bonus(result)


def reset_session_hashes():
    """Вызывать при старте каждой новой игры."""
    global _session_hashes
    _session_hashes = set()
    logger.info("🔄 Session question hashes reset")


def generate_hint(question_text: str) -> str:
    if os.getenv("GIGACHAT_CREDENTIALS"):
        try:
            hint = _call_gigachat(build_hint_prompt(question_text)).strip()
            hint = re.sub(r'^(Подсказка\s*:?\s*)', '', hint, flags=re.IGNORECASE).strip()
            if hint:
                return hint
        except Exception as exc:
            logger.warning("⚠️ Ошибка подсказки: %s", exc)
    return "Подумайте внимательно — ответ связан с контекстом вопроса."


def active_backend() -> str:
    if os.getenv("GIGACHAT_CREDENTIALS"):
        return f"GigaChat ✅ ({os.getenv('GIGACHAT_SCOPE','GIGACHAT_API_PERS')})"
    return "Fallback (встроенный банк вопросов)"


def parse_questions_json(raw: str) -> list:
    """Публичный алиас для learn_mode."""
    qs = _parse_response(raw, 4)
    qs = _fix_indexing_batch(qs, 4)
    return [_validate_question(q, 4) for q in qs if _validate_question(q, 4)]


# ── Fallback-банк (40 уникальных вопросов) ───────────────────────────────────

_FALLBACK = [
    {"question": "Сколько планет в Солнечной системе?",
     "options": ["6","7","8","9"], "correct": 2,
     "explanation": "Плутон исключён МАС в 2006 году. Восемь планет: от Меркурия до Нептуна."},
    {"question": "Химический символ золота?",
     "options": ["Ag","Fe","Au","Cu"], "correct": 2,
     "explanation": "Au — от латинского Aurum. Золото люди знают более 5000 лет."},
    {"question": "В каком году произошла Октябрьская революция?",
     "options": ["1905","1914","1917","1922"], "correct": 2,
     "explanation": "7 ноября 1917 г. большевики взяли власть. По старому стилю — 25 октября."},
    {"question": "Столица Австралии?",
     "options": ["Сидней","Мельбурн","Канберра","Брисбен"], "correct": 2,
     "explanation": "Канберра построена как компромисс между Сиднеем и Мельбурном."},
    {"question": "Кто написал роман «Война и мир»?",
     "options": ["Достоевский","Чехов","Толстой","Тургенев"], "correct": 2,
     "explanation": "Лев Толстой писал роман с 1863 по 1869 год."},
    {"question": "Основной газ атмосферы Земли?",
     "options": ["Кислород","Углекислый газ","Аргон","Азот"], "correct": 3,
     "explanation": "Азот составляет ~78% атмосферы. Кислород — около 21%."},
    {"question": "Самый лёгкий металл в периодической таблице?",
     "options": ["Алюминий","Магний","Литий","Натрий"], "correct": 2,
     "explanation": "Литий: плотность 0.53 г/см³ — легче воды."},
    {"question": "В каком году человек впервые полетел в космос?",
     "options": ["1957","1959","1961","1965"], "correct": 2,
     "explanation": "12 апреля 1961 г. Гагарин облетел Землю за 108 минут."},
    {"question": "Самая длинная река в мире?",
     "options": ["Амазонка","Нил","Янцзы","Миссисипи"], "correct": 1,
     "explanation": "Нил (~6670 км) традиционно считается длиннейшей рекой мира."},
    {"question": "Сколько костей у взрослого человека?",
     "options": ["186","206","226","246"], "correct": 1,
     "explanation": "У новорождённых ~270 костей, но к взрослости они срастаются до 206."},
    {"question": "Столица Японии?",
     "options": ["Осака","Киото","Токио","Иокогама"], "correct": 2,
     "explanation": "Токио стал столицей в 1869 году, сменив Киото."},
    {"question": "Кто написал роман «Мастер и Маргарита»?",
     "options": ["Пастернак","Булгаков","Есенин","Ахматова"], "correct": 1,
     "explanation": "Булгаков писал роман с 1928 по 1940 г., опубликован посмертно в 1966 г."},
    {"question": "Скорость света в вакууме (приближённо, тыс. км/с)?",
     "options": ["100","200","300","400"], "correct": 2,
     "explanation": "Точно 299 792 км/с. Фундаментальная константа физики."},
    {"question": "Какой орган вырабатывает инсулин?",
     "options": ["Печень","Почки","Поджелудочная железа","Надпочечники"], "correct": 2,
     "explanation": "β-клетки островков Лангерганса в поджелудочной железе."},
    {"question": "Ближайшая к Солнцу планета?",
     "options": ["Венера","Земля","Меркурий","Марс"], "correct": 2,
     "explanation": "Меркурий ближайший, но не самый горячий — Венера горячее из-за парникового эффекта."},
    {"question": "Кто написал 9-ю симфонию («Ода к радости»)?",
     "options": ["Моцарт","Шуберт","Бах","Бетховен"], "correct": 3,
     "explanation": "Бетховен написал её в 1824 г., будучи абсолютно глухим."},
    {"question": "Чему равна сумма углов треугольника?",
     "options": ["90°","180°","270°","360°"], "correct": 1,
     "explanation": "В евклидовой геометрии сумма углов треугольника всегда 180°."},
    {"question": "Сколько хромосом у здорового человека?",
     "options": ["23","44","46","48"], "correct": 2,
     "explanation": "46 хромосом (23 пары). Лишняя 21-я хромосома — синдром Дауна."},
    {"question": "Животное-символ WWF?",
     "options": ["Белый медведь","Большая панда","Тигр","Снежный барс"], "correct": 1,
     "explanation": "Большая панда — символ WWF с момента основания организации в 1961 году."},
    {"question": "Наибольшая по площади страна мира?",
     "options": ["Канада","Китай","США","Россия"], "correct": 3,
     "explanation": "Россия — 17.1 млн км², в 1.8 раза больше второй по размеру Канады."},
    {"question": "Сколько сторон у правильного шестиугольника?",
     "options": ["4","5","6","7"], "correct": 2,
     "explanation": "Шестиугольник — наиболее эффективная фигура для заполнения плоскости (пчелиные соты)."},
    {"question": "Какой элемент обозначается символом O?",
     "options": ["Золото","Азот","Кислород","Водород"], "correct": 2,
     "explanation": "O — кислород (Oxygenium). Необходим для дыхания всех аэробных организмов."},
    {"question": "Сколько нот в музыкальной гамме?",
     "options": ["5","6","7","8"], "correct": 2,
     "explanation": "До-ре-ми-фа-соль-ля-си — семь нот. Восьмая повторяет первую (октава)."},
    {"question": "Кто изобрёл телефон?",
     "options": ["Эдисон","Белл","Маркони","Тесла"], "correct": 1,
     "explanation": "Александр Белл запатентовал телефон в 1876 году."},
    {"question": "Самая высокая гора мира?",
     "options": ["К2","Лхоцзе","Канченджанга","Эверест"], "correct": 3,
     "explanation": "Эверест — 8848 м. Покорён Хиллари и Тенцингом в 1953 году."},
    {"question": "Сколько цветов у радуги?",
     "options": ["5","6","7","8"], "correct": 2,
     "explanation": "КОЖЗГСФ: красный, оранжевый, жёлтый, зелёный, голубой, синий, фиолетовый."},
    {"question": "В каком году основана компания Apple?",
     "options": ["1972","1974","1976","1980"], "correct": 2,
     "explanation": "Apple основана 1 апреля 1976 года Джобсом, Возняком и Уэйном."},
    {"question": "Автор теории относительности?",
     "options": ["Ньютон","Бор","Эйнштейн","Фейнман"], "correct": 2,
     "explanation": "Эйнштейн опубликовал специальную теорию относительности в 1905 году."},
    {"question": "Сколько граней у куба?",
     "options": ["4","5","6","8"], "correct": 2,
     "explanation": "У куба 6 граней, 12 рёбер и 8 вершин."},
    {"question": "Самое глубокое озеро в мире?",
     "options": ["Каспийское","Байкал","Танганьика","Гурон"], "correct": 1,
     "explanation": "Байкал — глубина 1642 м. Содержит 20% всей пресной воды планеты."},
    {"question": "Как называется наша галактика?",
     "options": ["Андромеда","Треугольник","Млечный Путь","Магеллановы Облака"], "correct": 2,
     "explanation": "Млечный Путь — спиральная галактика диаметром ~100 000 световых лет."},
    {"question": "Столица Франции?",
     "options": ["Лион","Марсель","Ницца","Париж"], "correct": 3,
     "explanation": "Париж — столица Франции, основан около 250 г. до н. э."},
    {"question": "Сколько букв в русском алфавите?",
     "options": ["30","32","33","35"], "correct": 2,
     "explanation": "33 буквы: 10 гласных, 21 согласная, ъ и ь."},
    {"question": "Кто написал «Преступление и наказание»?",
     "options": ["Толстой","Тургенев","Горький","Достоевский"], "correct": 3,
     "explanation": "Достоевский опубликовал роман в 1866 году в «Русском вестнике»."},
    {"question": "Сколько океанов на Земле?",
     "options": ["3","4","5","6"], "correct": 2,
     "explanation": "Пять океанов: Тихий, Атлантический, Индийский, Северный Ледовитый, Южный."},
    {"question": "Чему равно число π (приближённо)?",
     "options": ["2.71","3.14","3.17","3.41"], "correct": 1,
     "explanation": "π ≈ 3.14159... — иррациональное число, отношение длины окружности к диаметру."},
    {"question": "Самый твёрдый природный минерал?",
     "options": ["Рубин","Кварц","Корунд","Алмаз"], "correct": 3,
     "explanation": "Алмаз — 10 по шкале Мооса. Единственное вещество, царапающее само себя."},
    {"question": "Кто первым совершил кругосветное плавание?",
     "options": ["Колумб","Васко да Гама","Магеллан-Элькано","Дрейк"], "correct": 2,
     "explanation": "Магеллан начал, Элькано завершил в 1522 г. Магеллан погиб на Филиппинах."},
    {"question": "Что означает «www» в адресе сайта?",
     "options": ["Wide Web World","World Wide Web","Web World Wide","Wire Web World"], "correct": 1,
     "explanation": "World Wide Web — система гипертекстовых документов. Изобрёл Тим Бернерс-Ли в 1989 г."},
    {"question": "Основной орган кровообращения?",
     "options": ["Печень","Лёгкие","Сердце","Почки"], "correct": 2,
     "explanation": "Сердце перекачивает около 7000 литров крови в сутки."},
]
