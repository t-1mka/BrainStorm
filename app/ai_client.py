# -*- coding: utf-8 -*-
"""
Клиент GigaChat для BrainStorm.
Использует system+user сообщения, гарантирует валидный JSON,
генерирует подсказки и объяснения.
"""

import os, re, json, random, logging

logger = logging.getLogger(__name__)

DIFFICULTY_LABELS = {
    "easy":   "ЛЁГКИЙ — простые факты, известные каждому школьнику",
    "medium": "СРЕДНИЙ — требует кругозора эрудированного взрослого",
    "hard":   "СЛОЖНЫЙ — экспертный уровень, узкоспециализированные знания",
}

SYSTEM_PROMPT = (
    "Ты — профессиональный помощник для создания вопросов викторины. "
    "Все вопросы строго на русском языке. "
    "Ты всегда отвечаешь ТОЛЬКО валидным JSON без markdown, без пояснений, "
    "без символов ``` или любых других обёрток. "
    "Поле 'correct' — это ЦЕЛОЕ ЧИСЛО, индекс правильного ответа НАЧИНАЯ С НУЛЯ. "
    "Никаких других форматов ответа."
)


def build_prompt(topic: str, count: int, difficulty: str, num_options: int) -> str:
    diff_label = DIFFICULTY_LABELS.get(difficulty, DIFFICULTY_LABELS["medium"])
    max_idx    = num_options - 1
    example_q  = {
        "question":           "Какой химический символ у золота?",
        "options":            (["Ag", "Au", "Fe", "Cu"] if num_options >= 4 else ["Au", "Fe"])[:num_options],
        "correct":            1,
        "explanation":        "Au — от латинского Aurum. Золото применяется с древнейших времён.",
        "hint":               "Этот металл известен людям более пяти тысяч лет и ценится во всём мире.",
    }
    example = json.dumps({"questions": [example_q]}, ensure_ascii=False, indent=2)

    return (
        f'Создай РОВНО {count} уникальных вопросов для викторины по теме "{topic}".\n'
        f'Сложность: {diff_label}.\n\n'
        f'СТРОГИЕ ПРАВИЛА:\n'
        f'1. Каждый вопрос имеет РОВНО {num_options} варианта ответа.\n'
        f'2. "correct" = ЦЕЛОЕ ЧИСЛО — номер правильного ответа СЧИТАЯ С НУЛЯ '
        f'(0=первый, 1=второй, 2=третий, 3=четвёртый). '
        f'ДОПУСТИМЫЕ ЗНАЧЕНИЯ: от 0 до {max_idx}.\n'
        f'3. Правильный ответ должен действительно быть верным.\n'
        f'4. "explanation" — интересный факт 1–2 предложения.\n'
        f'5. "hint" — одно предложение-подсказка, НЕ раскрывающая ответ.\n'
        f'6. Ответ — ТОЛЬКО JSON-объект с ключом "questions". Никакого markdown.\n\n'
        f'Пример формата:\n{example}\n\n'
        f'Создай {count} вопросов по теме "{topic}". Только JSON:'
    )


def build_hint_prompt(question_text: str) -> str:
    return (
        f"Дай одну краткую подсказку (1-2 предложения) к вопросу викторины. "
        f"НЕ называй правильный ответ, только наведи игрока на мысль.\n"
        f"Вопрос: {question_text}\nПодсказка:"
    )


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


def _parse_response(raw: str, num_options: int) -> list:
    text = raw.strip().lstrip('\ufeff')
    cb = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if cb:
        text = cb.group(1).strip()
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e != -1:
        text = text[s:e+1]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Попытка 1: полный JSON
    try:
        data = json.loads(text)
        qs = (data.get("questions") or data.get("вопросы")
              or next((v for v in data.values()
                       if isinstance(v, list) and v
                       and isinstance(v[0], dict) and "question" in v[0]), None))
        if qs:
            logger.info("JSON: %d вопросов", len(qs))
            return qs
        if "question" in data:
            return [data]
    except json.JSONDecodeError as exc:
        logger.warning("json.loads: %s", exc)

    # Попытка 2: найти JSON-объекты регулярками
    qs = []
    for m in re.finditer(r'\{[^{}]*"question"[^{}]*\}', raw, re.DOTALL):
        chunk = re.sub(r',\s*([}\]])', r'\1', m.group(0))
        try:
            obj = json.loads(chunk)
            if "question" in obj:
                qs.append(obj)
        except json.JSONDecodeError:
            pass
    if qs:
        logger.info("Regex-объекты: %d вопросов", len(qs))
        return qs

    # Попытка 3: поля по отдельности
    qs = []
    e_iter = iter(re.finditer(r'"explanation"\s*:\s*"((?:[^"\\]|\\.)*)"', raw))
    for qm, om, cm in zip(
        re.finditer(r'"question"\s*:\s*"((?:[^"\\]|\\.)*)"', raw),
        re.finditer(r'"options"\s*:\s*\[([\s\S]*?)\]', raw),
        re.finditer(r'"correct"\s*:\s*(\d+)', raw),
    ):
        opts = re.findall(r'"((?:[^"\\]|\\.)*)"', om.group(1))
        expl = ""
        try:
            expl = next(e_iter).group(1).replace('\\"', '"')
        except StopIteration:
            pass
        qs.append({"question": qm.group(1).replace('\\"', '"'),
                   "options":  [o.replace('\\"', '"') for o in opts],
                   "correct":  int(cm.group(1)),
                   "explanation": expl})
    if qs:
        logger.info("Поля regex: %d вопросов", len(qs))
        return qs

    raise ValueError(f"Не удалось разобрать ответ: {raw[:200]!r}")


def _smart_fix_correct(q: dict, num_options: int) -> int:
    c = q.get("correct", 0)
    try:
        c = int(c)
    except (ValueError, TypeError):
        return 0
    if 0 <= c <= num_options - 1:
        return c
    if 1 <= c <= num_options:          # 1-based
        logger.warning("correct=%d (1-based)→%d для '%s...'",
                       c, c - 1, q.get("question", "")[:40])
        return c - 1
    logger.warning("correct=%d вне [0..%d]→0 для '%s...'",
                   c, num_options - 1, q.get("question", "")[:40])
    return 0


def _fix_indexing(questions: list, num_options: int) -> list:
    corrects = [q.get("correct", 0) for q in questions
                if isinstance(q.get("correct"), int)]
    if not corrects:
        return questions
    all_1based = all(1 <= c <= num_options for c in corrects)
    any_0based = any(c == 0 for c in corrects)
    if all_1based and not any_0based:
        logger.info("Все 1-based → 0-based конвертация")
        for q in questions:
            if isinstance(q.get("correct"), int):
                q["correct"] -= 1
    else:
        for q in questions:
            q["correct"] = _smart_fix_correct(q, num_options)
    return questions


def _is_bad(q: dict) -> bool:
    text = q.get("question", "")
    if len(text.strip()) < 10:
        return True
    opts = q.get("options", [])
    texts = [str(o).strip().lower() for o in opts if str(o).strip()]
    return len(set(texts)) < len(texts)


def _fix_and_validate(q: dict, num_options: int) -> "dict | None":
    q = q.copy()
    if not isinstance(q.get("question"), str) or not q["question"].strip():
        return None
    opts = q.get("options", [])
    if not isinstance(opts, list):
        return None
    opts = [str(o).strip() for o in opts if str(o).strip()][:num_options]
    if len(opts) < 2:
        return None
    while len(opts) < num_options:
        opts.append(f"Вариант {chr(65 + len(opts))}")
    q["options"]           = opts
    q["correct"]           = _smart_fix_correct(q, num_options)
    q["explanation"]       = q.get("explanation") or ""
    if not isinstance(q["explanation"], str):
        q["explanation"] = ""
    q["hint"] = q.get("hint") or ""
    if not isinstance(q["hint"], str):
        q["hint"] = ""
    # rephrased_question генерируется на лету только по запросу (экономия токенов)
    if _is_bad(q):
        return None
    return q


_FALLBACK = [
    {"question": "Сколько планет в Солнечной системе?",
     "options": ["6","7","8","9"], "correct": 2,
     "explanation": "Плутон исключён из числа планет в 2006 году решением МАС."},
    {"question": "Химический символ золота?",
     "options": ["Ag","Fe","Au","Cu"], "correct": 2,
     "explanation": "Au — от латинского Aurum. Золото применяется с древнейших времён."},
    {"question": "Год Октябрьской революции в России?",
     "options": ["1905","1914","1917","1922"], "correct": 2,
     "explanation": "7 ноября 1917 г. большевики взяли Зимний дворец."},
    {"question": "Столица Австралии?",
     "options": ["Сидней","Мельбурн","Канберра","Брисбен"], "correct": 2,
     "explanation": "Канберра построена специально как компромисс между Сиднеем и Мельбурном."},
    {"question": "Кто написал «Войну и мир»?",
     "options": ["Достоевский","Толстой","Тургенев","Чехов"], "correct": 1,
     "explanation": "Лев Толстой писал роман с 1863 по 1869 год."},
    {"question": "Основной газ атмосферы Земли?",
     "options": ["Кислород","Углекислый газ","Аргон","Азот"], "correct": 3,
     "explanation": "Азот составляет ~78% атмосферы. Кислород — около 21%."},
    {"question": "Самый лёгкий металл?",
     "options": ["Алюминий","Литий","Магний","Натрий"], "correct": 1,
     "explanation": "Литий — легчайший металл: плотность всего 0,53 г/см³."},
    {"question": "Год первого полёта человека в космос?",
     "options": ["1957","1959","1961","1965"], "correct": 2,
     "explanation": "Гагарин летел 12 апреля 1961 г. Полёт длился 108 минут."},
    {"question": "Самая длинная река в мире?",
     "options": ["Амазонка","Нил","Янцзы","Миссисипи"], "correct": 1,
     "explanation": "Нил (~6670 км) традиционно считается длиннейшей рекой."},
    {"question": "Сколько костей у взрослого человека?",
     "options": ["186","206","226","246"], "correct": 1,
     "explanation": "У новорождённых ~270 костей, у взрослого — 206."},
    {"question": "Столица Японии?",
     "options": ["Осака","Токио","Киото","Хиросима"], "correct": 1,
     "explanation": "Токио стал столицей в 1869 году."},
    {"question": "Кто написал «Мастер и Маргарита»?",
     "options": ["Достоевский","Булгаков","Пастернак","Есенин"], "correct": 1,
     "explanation": "Булгаков писал роман с 1928 по 1940 г., опубликован посмертно."},
    {"question": "Скорость света в вакууме (тыс. км/с)?",
     "options": ["100","200","300","400"], "correct": 2,
     "explanation": "Скорость света — 299 792 км/с. Фундаментальная константа."},
    {"question": "Сколько сторон у правильного шестиугольника?",
     "options": ["4","5","6","7"], "correct": 2,
     "explanation": "Соты пчёл — правильные шестиугольники: самая эффективная упаковка."},
    {"question": "Какой орган вырабатывает инсулин?",
     "options": ["Печень","Почки","Поджелудочная","Селезёнка"], "correct": 2,
     "explanation": "β-клетки поджелудочной железы синтезируют инсулин."},
    {"question": "Какая планета ближайшая к Солнцу?",
     "options": ["Венера","Земля","Меркурий","Марс"], "correct": 2,
     "explanation": "Меркурий ближайший, но не самый горячий — Венера горячее."},
    {"question": "Кто написал «Оду к радости» (9-я симфония)?",
     "options": ["Моцарт","Бах","Бетховен","Шуберт"], "correct": 2,
     "explanation": "Бетховен написал 9-ю симфонию в 1824 г., будучи полностью глухим."},
    {"question": "Чему равна сумма углов треугольника?",
     "options": ["90°","180°","270°","360°"], "correct": 1,
     "explanation": "В евклидовой геометрии сумма углов треугольника строго 180°."},
    {"question": "Сколько хромосом у здорового человека?",
     "options": ["23","44","46","48"], "correct": 2,
     "explanation": "46 хромосом (23 пары). Лишняя 21-я хромосома вызывает синдром Дауна."},
    {"question": "Какое животное символизирует WWF?",
     "options": ["Белый медведь","Панда","Тигр","Лев"], "correct": 1,
     "explanation": "Большая панда — символ WWF с 1961 года."},
]


def generate_questions(topic: str, count: int, difficulty: str, num_options: int) -> list:
    if os.getenv("GIGACHAT_CREDENTIALS"):
        try:
            prompt   = build_prompt(topic, count, difficulty, num_options)
            logger.info("📤 GigaChat | тема=%s | кол=%d | diff=%s", topic, count, difficulty)
            raw_text = _call_gigachat(prompt)
            logger.info("📥 Ответ: %d символов", len(raw_text))
            raw_qs   = _parse_response(raw_text, num_options)
            raw_qs   = _fix_indexing(raw_qs, num_options)
            qs       = [_fix_and_validate(q, num_options) for q in raw_qs]
            qs       = [q for q in qs if q is not None]
            if qs:
                logger.info("✅ Итого: %d вопросов", len(qs))
                return qs
            logger.warning("⚠️ Все вопросы отфильтрованы — fallback")
        except Exception as exc:
            logger.warning("⚠️ GigaChat ошибка: %s — fallback", exc)

    logger.warning("⚠️ Fallback-банк вопросов")
    pool = _FALLBACK * (count // len(_FALLBACK) + 1)
    return [_fix_and_validate(q.copy(), num_options) or q
            for q in random.sample(pool, min(count, len(pool)))]


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
        return f"GigaChat \u2705 ({os.getenv('GIGACHAT_SCOPE','GIGACHAT_API_PERS')})"
    return "Fallback (встроенный банк вопросов)"


def parse_questions_json(raw: str) -> list:
    """Публичный алиас _parse_response для learn_mode."""
    qs = _parse_response(raw, 4)
    qs = _fix_indexing(qs, 4)
    return [_fix_and_validate(q, 4) for q in qs if _fix_and_validate(q, 4)]
