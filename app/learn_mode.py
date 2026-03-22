# -*- coding: utf-8 -*-
"""
BrainStorm — learn_mode.py
Режим обучения: загрузка текста/URL → генерация вопросов через AI.
Ограничение: макс. 2500 символов контента, 5-8 вопросов — экономим токены.
"""
import re, logging
from .ai_client import _call_gigachat, parse_questions_json

logger = logging.getLogger(__name__)

MAX_CONTENT_LEN = 2500   # символов
MAX_QUESTIONS   = 8


def extract_text_from_url(url: str) -> tuple[bool, str]:
    """Извлекает текст из URL. Без внешних API ключей."""
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (compatible; BrainStorm/1.0)"}
        resp = requests.get(url, timeout=8, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Убираем скрипты, стили, nav
        for tag in soup(["script","style","nav","header","footer","aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Чистим пустые строки
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return True, "\n".join(lines)
    except Exception as e:
        logger.error("extract_url: %s", e)
        return False, f"Ошибка загрузки: {e}"


def prepare_content(raw_text: str) -> str:
    """Обрезает и нормализует текст для промпта."""
    # Убираем лишние пробелы/переносы
    text = re.sub(r'\n{3,}', '\n\n', raw_text.strip())
    text = re.sub(r' {2,}', ' ', text)
    if len(text) > MAX_CONTENT_LEN:
        text = text[:MAX_CONTENT_LEN] + "..."
    return text


def generate_learn_questions(content: str, num: int = 6) -> list[dict]:
    """
    Генерирует вопросы по тексту. Возвращает список вопросов.
    Ограничиваем num до MAX_QUESTIONS чтобы экономить токены.
    """
    num = min(num, MAX_QUESTIONS)
    content = prepare_content(content)

    prompt = (
        f"На основе следующего текста создай РОВНО {num} вопросов для викторины.\n"
        f"Каждый вопрос должен иметь РОВНО 4 варианта ответа.\n"
        f"Ответ только в формате JSON без markdown:\n"
        f'{{\"questions\":[{{\"question\":\"...\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correct\":0,\"explanation\":\"...\"}}]}}\n\n'
        f"Текст:\n{content}\n\n"
        f"Создай {num} вопросов. Только JSON:"
    )
    system = (
        "Ты — эксперт по созданию учебных тестов. "
        "Отвечай ТОЛЬКО валидным JSON без markdown, без пояснений. "
        "Поле 'correct' — целое число (индекс с 0). "
        "Поле 'explanation' — 1 предложение."
    )
    try:
        raw = _call_gigachat(prompt, system=system)
        questions = parse_questions_json(raw)
        return questions[:num]
    except Exception as e:
        logger.error("generate_learn_questions: %s", e)
        return []
