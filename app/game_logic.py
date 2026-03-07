# -*- coding: utf-8 -*-
"""BrainStorm — game_logic.py v4"""
import random, string, time, sqlite3, os, logging, json
from dataclasses import dataclass, field
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

SCORE_MULT   = {"easy": 1.0, "medium": 1.5, "hard": 2.0}
BASE_SCORE   = 100; TIME_BONUS = 50; MAX_TIME = 30.0
JOKER_COST   = 100; HINT_COST = 75
BONUS_MULT   = 2.0; BONUS_CHANCE = 0.20
MAX_TEAMS    = 7

_CACHE: dict = {}; CACHE_TTL = 3600

def cache_get(key):
    if key in _CACHE:
        ts, qs = _CACHE[key]
        if time.time() - ts < CACHE_TTL: return qs
        del _CACHE[key]
    return None

def cache_set(key, qs): _CACHE[key] = (time.time(), qs)

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "leaderboard.db")
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

def _db_conn():
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row; return c

def _init_db():
    with _db_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                username TEXT PRIMARY KEY, total_score INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
                last_seen INTEGER DEFAULT 0, total_time INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bans (
                identifier TEXT PRIMARY KEY, reason TEXT, expires_at INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS room_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_code TEXT NOT NULL,
                played_at INTEGER NOT NULL, duration INTEGER DEFAULT 0,
                mode TEXT, topic TEXT, players_json TEXT, questions_json TEXT
            );
        """)
        for col in ["total_time"]:
            try: c.execute(f"ALTER TABLE leaderboard ADD COLUMN {col} INTEGER DEFAULT 0")
            except: pass
_init_db()

# ── Баны ──
def ban_user(identifier, reason="", mins=60):
    exp = int(time.time()) + mins * 60
    try:
        with _db_conn() as c: c.execute("INSERT OR REPLACE INTO bans VALUES(?,?,?)", (identifier.lower(), reason, exp))
        return True
    except: return False

def unban_user(identifier):
    try:
        with _db_conn() as c: c.execute("DELETE FROM bans WHERE identifier=?", (identifier.lower(),))
        return True
    except: return False

def is_banned(identifier):
    try:
        with _db_conn() as c:
            row = c.execute("SELECT expires_at FROM bans WHERE identifier=?", (identifier.lower(),)).fetchone()
            if not row: return False
            if row["expires_at"] > int(time.time()): return True
            c.execute("DELETE FROM bans WHERE identifier=?", (identifier.lower(),)); return False
    except: return False

def get_all_bans():
    try:
        with _db_conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM bans WHERE expires_at>?", (int(time.time()),)).fetchall()]
    except: return []

# ── История ──
def save_room_history(code, duration, mode, topic, players, questions):
    try:
        with _db_conn() as c:
            c.execute("INSERT INTO room_history(room_code,played_at,duration,mode,topic,players_json,questions_json) VALUES(?,?,?,?,?,?,?)",
                (code, int(time.time()), duration, mode, topic, json.dumps(players, ensure_ascii=False), json.dumps(questions, ensure_ascii=False)))
    except Exception as e: logger.error("history save: %s", e)

def get_room_history(code):
    try:
        with _db_conn() as c:
            rows = c.execute("SELECT * FROM room_history WHERE room_code=? ORDER BY played_at DESC LIMIT 10", (code.upper(),)).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                item["players"]   = json.loads(item.pop("players_json","[]") or "[]")
                item["questions"] = json.loads(item.pop("questions_json","[]") or "[]")
                out.append(item)
            return out
    except: return []

# ── Лидерборд ──
def update_leaderboard(players, duration=0):
    if not players: return
    best = max((p["score"] for p in players), default=0)
    now  = int(time.time())
    try:
        with _db_conn() as c:
            for p in players:
                name  = p["name"][:64]; score = int(p["score"])
                win   = 1 if score == best and score > 0 else 0
                c.execute("""INSERT INTO leaderboard(username,total_score,games_played,wins,last_seen,total_time) VALUES(?,?,1,?,?,?)
                    ON CONFLICT(username) DO UPDATE SET total_score=total_score+excluded.total_score,
                    games_played=games_played+1, wins=wins+excluded.wins,
                    last_seen=excluded.last_seen, total_time=total_time+excluded.total_time""",
                    (name, score, win, now, duration))
    except Exception as e: logger.error("lb update: %s", e)

def get_leaderboard_top(n=50):
    try:
        with _db_conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM leaderboard ORDER BY total_score DESC LIMIT ?", (n,)).fetchall()]
    except: return []

def get_all_users(nick="", limit=200):
    try:
        with _db_conn() as c:
            if nick:
                return [dict(r) for r in c.execute("SELECT * FROM leaderboard WHERE username LIKE ? ORDER BY total_score DESC LIMIT ?", (f"%{nick}%", limit)).fetchall()]
            return [dict(r) for r in c.execute("SELECT * FROM leaderboard ORDER BY total_score DESC LIMIT ?", (limit,)).fetchall()]
    except: return []

def reset_user_stats(username):
    try:
        with _db_conn() as c: c.execute("UPDATE leaderboard SET total_score=0,wins=0,games_played=0,total_time=0 WHERE username=?", (username,))
        return True
    except: return False

def get_player_rank(username):
    try:
        with _db_conn() as c:
            row = c.execute("SELECT *,(SELECT COUNT(*)+1 FROM leaderboard l2 WHERE l2.total_score>l.total_score) AS rank FROM leaderboard l WHERE username=?", (username,)).fetchone()
            return dict(row) if row else {}
    except: return {}

def reset_server_stats():
    try:
        cutoff = int(time.time()) - 30*86400
        with _db_conn() as c:
            c.execute("DELETE FROM room_history WHERE played_at<?", (cutoff,))
            c.execute("DELETE FROM bans WHERE expires_at<?", (int(time.time()),))
        return True
    except: return False


# ── Team ──
@dataclass
class Team:
    id: int
    name: str
    leader_sid: Optional[str] = None
    members: List[str] = field(default_factory=list)   # sids

    def to_dict(self):
        return {"id": self.id, "name": self.name, "leader_sid": self.leader_sid, "members": self.members}


# ── Player ──
@dataclass
class Player:
    sid: str
    name: str
    score: int = 0
    team: Optional[int] = None
    answered: bool = False
    answer_index: Optional[int] = None
    answer_time: float = 0.0
    streak: int = 0
    total_correct: int = 0
    lives: int = 3
    joker_used: bool = False
    is_spectator: bool = False
    is_invisible: bool = False
    infinite_lives: bool = False
    instant_answer: bool = False
    join_time: float = field(default_factory=time.time)

    def reset_answer(self):
        self.answered = False; self.answer_index = None; self.answer_time = 0.0

    def to_dict(self, is_host=False, reveal_invisible=False):
        if self.is_invisible and not reveal_invisible: return None
        return {
            "name": self.name, "score": self.score, "team": self.team,
            "is_host": is_host, "total_correct": self.total_correct,
            "lives": self.lives, "is_spectator": self.is_spectator,
            "is_invisible": self.is_invisible, "sid": self.sid,
        }


# ── Room ──
@dataclass
class Room:
    code: str
    host_sid: str
    settings:  dict  = field(default_factory=dict)
    players:   dict  = field(default_factory=dict)
    state:     str   = "waiting"
    questions: list  = field(default_factory=list)
    current_q: int   = 0
    q_start_time: float = 0.0
    ffa_first: Optional[str] = None
    # Teams
    teams:     Dict[int, Team] = field(default_factory=dict)
    team_draft_active: bool = False   # режим выбора команд капитанами
    draft_turn_team: int = 1          # чья очередь выбирать
    # Adaptive
    recent_correct: list = field(default_factory=list)
    current_difficulty: str = "medium"
    keep_scores: bool = False
    is_public: bool = False
    is_sandbox: bool = False
    game_start_time: float = 0.0
    answer_log: list = field(default_factory=list)

    @property
    def mode(self):          return self.settings.get("game_mode", "classic")
    @property
    def difficulty(self):    return self.current_difficulty
    @property
    def total_questions(self): return len(self.questions)
    @property
    def current_question(self):
        return self.questions[self.current_q] if 0 <= self.current_q < len(self.questions) else None
    @property
    def human_players(self):
        return [p for p in self.players.values() if not p.is_spectator]
    @property
    def active_players(self):
        if self.mode == "lives":
            return [p for p in self.players.values() if not p.is_spectator and p.lives > 0]
        return [p for p in self.players.values() if not p.is_spectator]

    def add_player(self, sid, name, spectator=False, invisible=False):
        p = Player(sid=sid, name=name, is_spectator=spectator, is_invisible=invisible)
        self.players[sid] = p; return p

    def remove_player(self, sid):
        self.players.pop(sid, None)
        for t in self.teams.values():
            if sid in t.members: t.members.remove(sid)
            if t.leader_sid == sid: t.leader_sid = None

    def name_taken(self, name, exclude_sid=None):
        """Проверяет, занято ли имя другим игроком в комнате."""
        for sid, p in self.players.items():
            if sid == exclude_sid: continue
            if p.name.lower() == name.lower(): return True
        return False

    def players_list(self, viewer_sid=None):
        """Список игроков. Только читер видит невидимок (хост — нет)."""
        from . import CHEAT_NICK
        reveal = False
        if viewer_sid and viewer_sid in self.players:
            vp = self.players[viewer_sid]
            reveal = vp.name.lower() == CHEAT_NICK   # только читер видит невидимок
        result = []
        for p in self.players.values():
            d = p.to_dict(is_host=(p.sid == self.host_sid), reveal_invisible=reveal)
            if d is not None: result.append(d)
        return result

    # ── Teams helpers ──
    def init_teams(self, count=2, names=None):
        """Инициализирует команды."""
        self.teams = {}
        default_names = [f"Команда {i+1}" for i in range(count)]
        for i in range(count):
            name = (names[i] if names and i < len(names) else default_names[i])
            self.teams[i+1] = Team(id=i+1, name=name)

    def assign_team_leaders(self):
        """Назначает первых вошедших игроков лидерами команд."""
        humans = sorted([p for p in self.players.values() if not p.is_spectator],
                        key=lambda p: p.join_time)
        for idx, team in enumerate(self.teams.values()):
            if idx < len(humans):
                team.leader_sid = humans[idx].sid
                team.members    = [humans[idx].sid]
                humans[idx].team = team.id

    def assign_teams_auto(self):
        """Автоматическое распределение по командам."""
        tc = len(self.teams) or 2
        if not self.teams: self.init_teams(tc)
        sids = [p.sid for p in self.players.values() if not p.is_spectator]
        random.shuffle(sids)
        for t in self.teams.values(): t.members = []
        for i, sid in enumerate(sids):
            team_id = list(self.teams.keys())[i % tc]
            self.teams[team_id].members.append(sid)
            self.players[sid].team = team_id

    def team_scores(self):
        s = {tid: 0 for tid in self.teams}
        for p in self.players.values():
            if p.team and p.team in s: s[p.team] += p.score
        return s

    def teams_list(self):
        return [t.to_dict() for t in self.teams.values()]

    def draft_pick(self, captain_sid, target_sid):
        """Капитан выбирает игрока в команду (draft mode)."""
        # Найти команду капитана
        cap_team = None
        for team in self.teams.values():
            if team.leader_sid == captain_sid:
                cap_team = team; break
        if not cap_team: return False, "Вы не капитан"
        if cap_team.id != self.draft_turn_team: return False, "Не ваша очередь"
        target = self.players.get(target_sid)
        if not target or target.team is not None: return False, "Игрок недоступен"
        cap_team.members.append(target_sid)
        target.team = cap_team.id
        # Следующий ход
        team_ids = sorted(self.teams.keys())
        cur_idx  = team_ids.index(self.draft_turn_team)
        self.draft_turn_team = team_ids[(cur_idx + 1) % len(team_ids)]
        # Проверить, все ли распределены
        undrafted = [p for p in self.players.values() if not p.is_spectator and p.team is None and
                     all(t.leader_sid != p.sid for t in self.teams.values())]
        if not undrafted:
            self.team_draft_active = False
        return True, "OK"

    # ── Answers ──
    def reset_answers(self):
        for p in self.players.values(): p.reset_answer(); p.joker_used = False
        self.ffa_first = None

    def all_answered(self):
        active = self.active_players
        if self.mode == "team":
            # В командном — отвечают только из текущей команды (turn_team)
            turn = self.settings.get("_turn_team", 1)
            active = [p for p in active if p.team == turn]
        return all(p.answered for p in active) if active else True

    def advance_question(self):
        if self.mode == "team":
            team_ids = sorted(self.teams.keys()) if self.teams else [1, 2]
            cur = self.settings.get("_turn_team", team_ids[0])
            idx = team_ids.index(cur) if cur in team_ids else 0
            self.settings["_turn_team"] = team_ids[(idx + 1) % len(team_ids)]
        self.current_q += 1
        if self.current_q >= self.total_questions: self.state = "finished"; return False
        if self.mode == "lives" and len(self.active_players) <= 1: self.state = "finished"; return False
        self.reset_answers(); self.q_start_time = time.time(); return True

    def award_point(self, sid):
        p = self.players.get(sid)
        if not p: return 0
        q = self.current_question
        is_bonus = q.get("bonus", False) if q else False
        mult = SCORE_MULT.get(self.difficulty, 1.0) * (BONUS_MULT if is_bonus else 1.0)
        pts  = int(BASE_SCORE * mult)
        elapsed = max(0.0, p.answer_time - self.q_start_time)
        pts += max(0, int(TIME_BONUS * (1 - elapsed / MAX_TIME)))
        p.streak += 1; p.total_correct += 1
        if p.streak >= 3: pts += min(50, (p.streak - 2) * 10)
        if self.mode == "coop":
            for pl in self.players.values():
                if not pl.is_spectator: pl.score += pts
        else: p.score += pts
        return pts

    def reset_streak(self, sid):
        if p := self.players.get(sid): p.streak = 0

    def lose_life(self, sid):
        p = self.players.get(sid)
        if not p or p.lives <= 0: return 0
        if p.infinite_lives: return p.lives
        p.lives -= 1
        if p.lives == 0: p.is_spectator = True
        return p.lives

    def use_joker(self, sid):
        p = self.players.get(sid); q = self.current_question
        if not p or not q or p.joker_used or p.answered or p.score < JOKER_COST: return None
        p.joker_used = True; p.score -= JOKER_COST
        correct = q["correct"]
        wrongs  = [i for i in range(len(q["options"])) if i != correct]
        return sorted([correct, random.choice(wrongs)])

    def record_answer_stat(self, ok):
        self.recent_correct.append(ok)
        if len(self.recent_correct) > 15: self.recent_correct.pop(0)

    def recalculate_difficulty(self):
        if len(self.recent_correct) < 6: return self.current_difficulty
        pct = sum(self.recent_correct) / len(self.recent_correct)
        self.current_difficulty = "hard" if pct > 0.80 else ("easy" if pct < 0.45 else "medium")
        return self.current_difficulty

    def final_results(self):
        sorted_p = sorted(self.players.values(), key=lambda p: -p.score)
        out = {
            "mode": self.mode,
            "players": [{"rank": i+1, "name": p.name, "score": p.score, "team": p.team,
                         "total_correct": p.total_correct, "is_spectator": p.is_spectator}
                        for i, p in enumerate(sorted_p)],
        }
        if self.mode == "team":
            ts = self.team_scores(); out["team_scores"] = ts
            out["winner_team"] = max(ts, key=ts.get) if ts else None
            out["team_names"]  = {tid: t.name for tid, t in self.teams.items()}
        if self.mode == "lives":
            out["survivors"] = [p.name for p in self.players.values() if p.lives > 0]
        return out

    def reset_for_restart(self, keep_scores=False):
        self.state = "waiting"; self.questions = []; self.current_q = 0
        self.ffa_first = None; self.recent_correct = []; self.answer_log = []
        self.current_difficulty = self.settings.get("difficulty", "medium")
        self.settings.pop("_turn_team", None)
        for t in self.teams.values(): t.members = []; t.leader_sid = None
        for p in self.players.values():
            p.answered = False; p.answer_index = None; p.answer_time = 0.0
            p.streak = 0; p.joker_used = False; p.is_spectator = False
            p.lives = 3; p.team = None
            if not keep_scores: p.score = 0; p.total_correct = 0


rooms: dict = {}

def gen_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=6))
        if code not in rooms: return code

def get_room_by_sid(sid):
    return next((r for r in rooms.values() if sid in r.players), None)
