# -*- coding: utf-8 -*-
"""
BrainStorm — user_db.py
Пользователи, UGC-вопросы, кампания, достижения.
Отдельный SQLite-файл user_data.db.
"""
import os, time, json, hashlib, sqlite3, logging, re

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "user_data.db"
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)


# ─────────────────────────────────────────────
#  Соединение с БД
# ─────────────────────────────────────────────
def _conn():
    c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


# ─────────────────────────────────────────────
#  Инициализация таблиц
# ─────────────────────────────────────────────
def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username    TEXT PRIMARY KEY,
            pwd_hash    TEXT NOT NULL,
            xp          INTEGER DEFAULT 0,
            coins       INTEGER DEFAULT 50,
            games_played INTEGER DEFAULT 0,
            wins        INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            created_at  INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ugc_questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            author      TEXT NOT NULL,
            question    TEXT NOT NULL,
            options     TEXT NOT NULL,   -- JSON array
            correct     INTEGER NOT NULL,
            topic       TEXT DEFAULT '',
            difficulty  INTEGER DEFAULT 2,  -- 1-5
            status      TEXT DEFAULT 'pending',  -- pending/approved/rejected
            rating      REAL DEFAULT 0.0,
            usage_count INTEGER DEFAULT 0,
            correct_pct REAL DEFAULT 0.0,
            created_at  INTEGER DEFAULT 0,
            reject_reason TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ugc_votes (
            question_id INTEGER NOT NULL,
            voter       TEXT NOT NULL,
            vote        INTEGER NOT NULL,  -- +1 или -1
            PRIMARY KEY (question_id, voter)
        );
        CREATE TABLE IF NOT EXISTS ugc_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            reporter    TEXT NOT NULL,
            reason      TEXT DEFAULT '',
            created_at  INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS campaign_progress (
            username    TEXT NOT NULL,
            level_id    INTEGER NOT NULL,
            stars       INTEGER DEFAULT 0,
            best_score  INTEGER DEFAULT 0,
            completed_at INTEGER DEFAULT 0,
            PRIMARY KEY (username, level_id)
        );
        CREATE TABLE IF NOT EXISTS achievements (
            username    TEXT NOT NULL,
            ach_id      TEXT NOT NULL,
            unlocked_at INTEGER DEFAULT 0,
            PRIMARY KEY (username, ach_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ugc_status ON ugc_questions(status, rating DESC);
        CREATE INDEX IF NOT EXISTS idx_ugc_topic  ON ugc_questions(topic, status);
        CREATE INDEX IF NOT EXISTS idx_camp       ON campaign_progress(username);
        """)

init_db()


# ─────────────────────────────────────────────
#  Хэширование пароля (без bcrypt)
# ─────────────────────────────────────────────
def _hash_pwd(pwd: str, salt: str = "") -> str:
    if not salt:
        salt = os.urandom(16).hex()
    h = hashlib.sha256(f"{salt}:{pwd}".encode()).hexdigest()
    return f"{salt}:{h}"

def _check_pwd(pwd: str, stored: str) -> bool:
    try:
        salt, _ = stored.split(":", 1)
        return _hash_pwd(pwd, salt) == stored
    except Exception:
        return False


# ─────────────────────────────────────────────
#  Пользователи
# ─────────────────────────────────────────────
def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()[:20]
    if len(username) < 2:
        return False, "Имя слишком короткое (мин. 2 символа)"
    if len(password) < 4:
        return False, "Пароль слишком короткий (мин. 4 символа)"
    if not re.match(r'^[\w\-а-яёА-ЯЁ ]+$', username, re.UNICODE):
        return False, "Недопустимые символы в имени"
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO users(username,pwd_hash,created_at) VALUES(?,?,?)",
                (username, _hash_pwd(password), int(time.time()))
            )
        return True, "OK"
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким именем уже существует"
    except Exception as e:
        return False, str(e)


def login_user(username: str, password: str) -> tuple[bool, str]:
    try:
        with _conn() as c:
            row = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not row:
            return False, "Пользователь не найден"
        if not _check_pwd(password, row["pwd_hash"]):
            return False, "Неверный пароль"
        return True, "OK"
    except Exception as e:
        return False, str(e)


def get_user(username: str) -> dict | None:
    try:
        with _conn() as c:
            row = c.execute("SELECT username,xp,coins,games_played,wins,total_score,created_at FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def update_user_stats(username: str, score: int, won: bool, xp_gain: int):
    try:
        with _conn() as c:
            c.execute("""UPDATE users SET
                games_played=games_played+1,
                total_score=total_score+?,
                wins=wins+?,
                xp=xp+?
            WHERE username=?""", (score, 1 if won else 0, xp_gain, username))
    except Exception as e:
        logger.error("update_user_stats: %s", e)


def add_coins(username: str, amount: int):
    try:
        with _conn() as c:
            c.execute("UPDATE users SET coins=MAX(0,coins+?) WHERE username=?", (amount, username))
    except Exception as e:
        logger.error("add_coins: %s", e)


def spend_coins(username: str, amount: int) -> bool:
    try:
        with _conn() as c:
            row = c.execute("SELECT coins FROM users WHERE username=?", (username,)).fetchone()
            if not row or row["coins"] < amount:
                return False
            c.execute("UPDATE users SET coins=coins-? WHERE username=?", (amount, username))
        return True
    except Exception:
        return False


def get_level_from_xp(xp: int) -> int:
    import math
    return max(1, int(math.sqrt(xp / 100)) + 1)


# ─────────────────────────────────────────────
#  UGC — создание и модерация вопросов
# ─────────────────────────────────────────────

# Простой список запрещённых слов (без AI)
_BAD_WORDS = re.compile(
    r'\b(хуй|пизд|ебл|блядь|сука|мудак|чмо|нигг|фашист|убий)\w*',
    re.IGNORECASE | re.UNICODE
)

def _auto_moderate(text: str, options: list, correct: int) -> tuple[bool, str]:
    """Быстрая проверка без AI. Возвращает (ok, reason)."""
    # Проверка длины
    if len(text.strip()) < 10:
        return False, "Вопрос слишком короткий"
    if len(options) < 2 or len(options) > 6:
        return False, "Неверное количество вариантов (2-6)"
    if correct < 0 or correct >= len(options):
        return False, "Неверный индекс правильного ответа"
    # Уникальность вариантов
    lower_opts = [o.strip().lower() for o in options]
    if len(set(lower_opts)) != len(lower_opts):
        return False, "Варианты ответов должны быть уникальными"
    # Цензура
    if _BAD_WORDS.search(text) or any(_BAD_WORDS.search(o) for o in options):
        return False, "Текст содержит недопустимые слова"
    # Пустые варианты
    if any(not o.strip() for o in options):
        return False, "Варианты ответов не могут быть пустыми"
    return True, "OK"


def create_ugc_question(author: str, question: str, options: list,
                         correct: int, topic: str, difficulty: int) -> tuple[bool, str | int]:
    """Создаёт UGC-вопрос. Возвращает (ok, id_or_error)."""
    ok, reason = _auto_moderate(question, options, correct)
    if not ok:
        return False, reason
    try:
        with _conn() as c:
            # Проверка на дубликат (простое совпадение после нормализации)
            existing = c.execute(
                "SELECT id FROM ugc_questions WHERE LOWER(question)=LOWER(?)", (question.strip(),)
            ).fetchone()
            if existing:
                return False, "Такой вопрос уже существует"
            cur = c.execute(
                """INSERT INTO ugc_questions
                   (author,question,options,correct,topic,difficulty,status,created_at)
                   VALUES(?,?,?,?,?,?,'pending',?)""",
                (author, question.strip(), json.dumps(options, ensure_ascii=False),
                 correct, topic.strip()[:50], max(1, min(5, difficulty)), int(time.time()))
            )
            return True, cur.lastrowid
    except Exception as e:
        return False, str(e)


def get_ugc_questions(topic: str = "", status: str = "approved",
                      limit: int = 50, offset: int = 0) -> list[dict]:
    try:
        with _conn() as c:
            if topic:
                rows = c.execute(
                    "SELECT * FROM ugc_questions WHERE status=? AND topic LIKE ? ORDER BY rating DESC LIMIT ? OFFSET ?",
                    (status, f"%{topic}%", limit, offset)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM ugc_questions WHERE status=? ORDER BY rating DESC LIMIT ? OFFSET ?",
                    (status, limit, offset)
                ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"] or "[]")
            result.append(d)
        return result
    except Exception:
        return []


def get_user_ugc(username: str) -> list[dict]:
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM ugc_questions WHERE author=? ORDER BY created_at DESC LIMIT 100",
                (username,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"] or "[]")
            result.append(d)
        return result
    except Exception:
        return []


def vote_ugc(question_id: int, voter: str, vote: int) -> bool:
    """vote: +1 или -1."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO ugc_votes(question_id,voter,vote) VALUES(?,?,?)",
                (question_id, voter, vote)
            )
            # Пересчитать рейтинг
            row = c.execute(
                "SELECT COALESCE(SUM(vote),0) as r FROM ugc_votes WHERE question_id=?",
                (question_id,)
            ).fetchone()
            c.execute("UPDATE ugc_questions SET rating=? WHERE id=?", (row["r"], question_id))
        return True
    except Exception:
        return False


def report_ugc(question_id: int, reporter: str, reason: str) -> bool:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO ugc_reports(question_id,reporter,reason,created_at) VALUES(?,?,?,?)",
                (question_id, reporter, reason[:200], int(time.time()))
            )
            # После 5 жалоб — скрываем
            cnt = c.execute(
                "SELECT COUNT(*) as n FROM ugc_reports WHERE question_id=?", (question_id,)
            ).fetchone()["n"]
            if cnt >= 5:
                c.execute("UPDATE ugc_questions SET status='pending' WHERE id=?", (question_id,))
        return True
    except Exception:
        return False


def admin_moderate_ugc(question_id: int, approve: bool, reason: str = "") -> bool:
    status = "approved" if approve else "rejected"
    try:
        with _conn() as c:
            c.execute(
                "UPDATE ugc_questions SET status=?, reject_reason=? WHERE id=?",
                (status, reason, question_id)
            )
        return True
    except Exception:
        return False


def get_ugc_pending(limit: int = 50) -> list[dict]:
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM ugc_questions WHERE status='pending' ORDER BY created_at LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"] or "[]")
            result.append(d)
        return result
    except Exception:
        return []


def record_ugc_usage(question_id: int, correct: bool):
    """Обновляет статистику использования вопроса."""
    try:
        with _conn() as c:
            c.execute("UPDATE ugc_questions SET usage_count=usage_count+1 WHERE id=?", (question_id,))
            row = c.execute(
                "SELECT usage_count, correct_pct FROM ugc_questions WHERE id=?", (question_id,)
            ).fetchone()
            if row and row["usage_count"] > 0:
                old_pct = row["correct_pct"] or 0
                n = row["usage_count"]
                new_pct = (old_pct * (n - 1) + (100 if correct else 0)) / n
                c.execute("UPDATE ugc_questions SET correct_pct=? WHERE id=?", (new_pct, question_id))
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Кампания
# ─────────────────────────────────────────────

CAMPAIGN_LEVELS = [
    {"id":1,  "title":"Что? Где? Когда?",  "topic":"общие знания",        "world":1, "difficulty":"easy",   "questions":8,  "req_stars":0,  "boss":False, "reward_coins":30},
    {"id":2,  "title":"История мира",       "topic":"история",             "world":1, "difficulty":"easy",   "questions":8,  "req_stars":2,  "boss":False, "reward_coins":30},
    {"id":3,  "title":"Наука и природа",    "topic":"наука и природа",     "world":1, "difficulty":"easy",   "questions":8,  "req_stars":5,  "boss":False, "reward_coins":30},
    {"id":4,  "title":"Финал Мира 1 🏆",    "topic":"общие знания",        "world":1, "difficulty":"medium", "questions":10, "req_stars":9,  "boss":True,  "reward_coins":80},
    {"id":5,  "title":"Кино и музыка",      "topic":"кино и музыка",       "world":2, "difficulty":"medium", "questions":8,  "req_stars":12, "boss":False, "reward_coins":40},
    {"id":6,  "title":"Спорт",              "topic":"спорт",               "world":2, "difficulty":"medium", "questions":8,  "req_stars":14, "boss":False, "reward_coins":40},
    {"id":7,  "title":"География",          "topic":"география",           "world":2, "difficulty":"medium", "questions":8,  "req_stars":16, "boss":False, "reward_coins":40},
    {"id":8,  "title":"Технологии",         "topic":"технологии и IT",     "world":2, "difficulty":"medium", "questions":8,  "req_stars":18, "boss":False, "reward_coins":40},
    {"id":9,  "title":"Финал Мира 2 🏆",    "topic":"смешанная",           "world":2, "difficulty":"hard",   "questions":12, "req_stars":22, "boss":True,  "reward_coins":120},
    {"id":10, "title":"Мифология",          "topic":"мифология",           "world":3, "difficulty":"hard",   "questions":8,  "req_stars":25, "boss":False, "reward_coins":50},
    {"id":11, "title":"Литература",         "topic":"литература",          "world":3, "difficulty":"hard",   "questions":8,  "req_stars":27, "boss":False, "reward_coins":50},
    {"id":12, "title":"Эрудит Финал 🌟",    "topic":"эрудит высший уровень","world":3,"difficulty":"hard",   "questions":15, "req_stars":30, "boss":True,  "reward_coins":200},
]

WORLD_NAMES = {1: "🌍 Мир знаний", 2: "🎭 Мир культуры", 3: "🔮 Мир мастеров"}


def get_campaign_progress(username: str) -> dict:
    """Возвращает прогресс + доступные уровни."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT level_id,stars,best_score FROM campaign_progress WHERE username=?",
                (username,)
            ).fetchall()
        progress = {r["level_id"]: {"stars": r["stars"], "best_score": r["best_score"]} for r in rows}
        total_stars = sum(v["stars"] for v in progress.values())
        levels = []
        for lvl in CAMPAIGN_LEVELS:
            p = progress.get(lvl["id"], {"stars": 0, "best_score": 0})
            levels.append({
                **lvl,
                "stars": p["stars"],
                "best_score": p["best_score"],
                "locked": total_stars < lvl["req_stars"],
            })
        return {"levels": levels, "total_stars": total_stars}
    except Exception as e:
        logger.error("get_campaign_progress: %s", e)
        return {"levels": [], "total_stars": 0}


def save_campaign_result(username: str, level_id: int, score: int,
                          correct: int, total_questions: int) -> dict:
    """Сохраняет результат уровня кампании, начисляет награды."""
    pct = correct / total_questions if total_questions > 0 else 0
    stars = 3 if pct >= 0.9 else (2 if pct >= 0.65 else (1 if pct >= 0.4 else 0))
    lvl_meta = next((l for l in CAMPAIGN_LEVELS if l["id"] == level_id), None)
    coins_earned = 0
    xp_earned = correct * 15 + stars * 25

    try:
        with _conn() as c:
            existing = c.execute(
                "SELECT stars,best_score FROM campaign_progress WHERE username=? AND level_id=?",
                (username, level_id)
            ).fetchone()
            old_stars = existing["stars"] if existing else 0
            new_stars  = max(old_stars, stars)
            # Монеты только за новые звёзды
            if lvl_meta and stars > old_stars:
                coins_earned = lvl_meta["reward_coins"] * (stars - old_stars) // 3
            c.execute("""
                INSERT INTO campaign_progress(username,level_id,stars,best_score,completed_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(username,level_id) DO UPDATE SET
                    stars=MAX(excluded.stars,stars),
                    best_score=MAX(excluded.best_score,best_score),
                    completed_at=excluded.completed_at
            """, (username, level_id, new_stars, score, int(time.time())))
        if coins_earned > 0:
            add_coins(username, coins_earned)
        if xp_earned > 0:
            with _conn() as c:
                c.execute("UPDATE users SET xp=xp+? WHERE username=?", (xp_earned, username))
    except Exception as e:
        logger.error("save_campaign_result: %s", e)

    return {"stars": stars, "xp": xp_earned, "coins": coins_earned, "pct": round(pct * 100)}


# ─────────────────────────────────────────────
#  Достижения
# ─────────────────────────────────────────────

ACHIEVEMENTS = {
    "first_win":       {"title": "Первая победа",      "icon": "🏆", "desc": "Выиграй первую игру"},
    "streak5":         {"title": "В потоке",           "icon": "🔥", "desc": "Серия 5 правильных подряд"},
    "campaign_world1": {"title": "Покоритель мира 1",  "icon": "🌍", "desc": "Пройди все уровни мира 1"},
    "campaign_boss":   {"title": "Боссубийца",         "icon": "⚔️",  "desc": "Победи босс-уровень"},
    "ugc_creator":     {"title": "Автор",              "icon": "✏️",  "desc": "Создай первый вопрос"},
    "ugc_10":          {"title": "Контрибьютор",       "icon": "📝",  "desc": "Создай 10 вопросов"},
    "games10":         {"title": "Завсегдатай",        "icon": "🎮",  "desc": "Сыграй 10 игр"},
    "games50":         {"title": "Ветеран",            "icon": "🎖️",  "desc": "Сыграй 50 игр"},
    "perfect_level":   {"title": "Перфекционист",      "icon": "⭐",  "desc": "Пройди уровень на 3 звезды"},
    "learn_mode":      {"title": "Студент",            "icon": "📚",  "desc": "Используй режим обучения"},
}


def unlock_achievement(username: str, ach_id: str) -> bool:
    """Разблокирует достижение. Возвращает True если разблокировано впервые."""
    if ach_id not in ACHIEVEMENTS:
        return False
    try:
        with _conn() as c:
            existing = c.execute(
                "SELECT 1 FROM achievements WHERE username=? AND ach_id=?", (username, ach_id)
            ).fetchone()
            if existing:
                return False
            c.execute(
                "INSERT INTO achievements(username,ach_id,unlocked_at) VALUES(?,?,?)",
                (username, ach_id, int(time.time()))
            )
        return True
    except Exception:
        return False


def get_achievements(username: str) -> list[dict]:
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT ach_id,unlocked_at FROM achievements WHERE username=?", (username,)
            ).fetchall()
        unlocked = {r["ach_id"]: r["unlocked_at"] for r in rows}
        result = []
        for ach_id, meta in ACHIEVEMENTS.items():
            result.append({
                "id": ach_id,
                **meta,
                "unlocked": ach_id in unlocked,
                "unlocked_at": unlocked.get(ach_id),
            })
        return result
    except Exception:
        return []


def check_and_unlock_achievements(username: str) -> list[str]:
    """Проверяет все условия и разблокирует достижения. Возвращает список новых."""
    new_achs = []
    user = get_user(username)
    if not user:
        return []
    if user["wins"] >= 1  and unlock_achievement(username, "first_win"):   new_achs.append("first_win")
    if user["games_played"] >= 10 and unlock_achievement(username, "games10"): new_achs.append("games10")
    if user["games_played"] >= 50 and unlock_achievement(username, "games50"): new_achs.append("games50")
    try:
        with _conn() as c:
            ugc_cnt = c.execute(
                "SELECT COUNT(*) as n FROM ugc_questions WHERE author=?", (username,)
            ).fetchone()["n"]
        if ugc_cnt >= 1  and unlock_achievement(username, "ugc_creator"): new_achs.append("ugc_creator")
        if ugc_cnt >= 10 and unlock_achievement(username, "ugc_10"):      new_achs.append("ugc_10")
    except Exception:
        pass
    return new_achs
