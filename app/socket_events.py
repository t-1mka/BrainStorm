# -*- coding: utf-8 -*-
"""BrainStorm — socket_events.py v5"""
import time, logging, random, eventlet, json
from flask import request, session as flask_session
from flask_socketio import emit, join_room, leave_room
from . import socketio, CHEAT_TESTER_CODE
from .game_logic import (
    rooms, Room, gen_code, get_room_by_sid, index_add, index_remove,
    cache_get, cache_set,
    update_leaderboard, JOKER_COST, HINT_COST, BONUS_CHANCE,
    ban_user, is_banned, save_room_history, reset_user_stats, Team,
    cleanup_stale_rooms
)
from .ai_client import generate_questions, generate_hint

logger     = logging.getLogger(__name__)
TIME_PER_Q = 30

_CHAT_LOG: dict = {}
SI_ROWS       = 5
SI_COLS       = 3
SI_VALUES     = [100, 200, 300, 400, 500]

def _room_cleanup_loop():
    while True:
        eventlet.sleep(30)
        try:
            n = cleanup_stale_rooms()
            if n:
                logger.info("🧹 Удалено %d пустых/неактивных комнат", n)
        except Exception as e:
            logger.error("cleanup error: %s", e)

eventlet.spawn(_room_cleanup_loop)

def _is_cheater(sid) -> bool:
    room = get_room_by_sid(sid)
    if not room: return False
    p = room.players.get(sid)
    return bool(p and p.is_cheat)

def _is_host_or_cheater(sid, room) -> bool:
    if not room: return False
    return room.host_sid == sid or _is_cheater(sid)

def _is_admin() -> bool:
    return bool(flask_session.get("is_admin"))

def _mark_bonus(qs):
    return [{**q, "bonus": random.random() < BONUS_CHANCE} for q in qs]

def _broadcast_players(room: Room):
    public_list = []
    for p in room.players.values():
        d = p.to_dict(is_host=(p.sid == room.host_sid), reveal_invisible=False)
        if d is not None:
            public_list.append(d)
    teams_data = room.teams_list()
    for sid in list(room.players.keys()):
        p = room.players.get(sid)
        if p and p.is_cheat:
            personal = room.players_list(viewer_sid=sid)
            socketio.emit("players_update", {"players": personal, "teams": teams_data}, room=sid)
        else:
            socketio.emit("players_update", {"players": public_list, "teams": teams_data}, room=sid)

def _emit_question(room: Room):
    q = room.current_question
    if not q: return
    turn_team = room.settings.get("_turn_team", 1)
    base = {
        "question":        {"question": q["question"], "options": q["options"]},
        "question_number": room.current_q + 1,
        "total_questions": room.total_questions,
        "time_limit":      TIME_PER_Q,
        "mode":            room.mode,
        "is_bonus":        q.get("bonus", False),
        "difficulty":      room.difficulty,
        "turn_team":       turn_team,
        "team_scores":     room.team_scores(),
        "team_names":      {tid: t.name for tid, t in room.teams.items()},
        "presentation":    room.settings.get("presentation_mode", False),
    }
    for sid, player in room.players.items():
        p = {**base}
        if player.is_cheat:
            p["cheat_correct"] = q["correct"]
        if room.mode == "lives":
            p["my_lives"] = player.lives
        if player.instant_answer:
            p["instant_answer"] = True
        socketio.emit("new_question", p, room=sid)
    eventlet.spawn_after(TIME_PER_Q + 1, _timeout_question, room.code, room.current_q)

def _timeout_question(code, q_idx):
    room = rooms.get(code)
    if not room or room.state != "playing" or room.current_q != q_idx: return
    for p in room.active_players:
        if not p.answered and not p.instant_answer:
            p.answered = True; p.answer_index = -1; p.answer_time = time.time()
            room.reset_streak(p.sid); room.record_answer_stat(False)
    _resolve_question(room)

def _resolve_question(room: Room):
    q = room.current_question
    if not q: return
    ci = q["correct"]
    correct_text = q["options"][ci] if 0 <= ci < len(q["options"]) else "?"
    player_answers = {
        sid: {"answer": p.answer_index, "correct": p.answer_index == ci,
              "streak": p.streak, "name": p.name}
        for sid, p in room.players.items()
    }
    any_correct = any(v["correct"] for v in player_answers.values())
    room.record_answer_stat(any_correct)
    new_diff = room.recalculate_difficulty()
    room.answer_log.append({
        "question": q["question"], "correct_index": ci, "correct_text": correct_text,
        "answers": {p.name: p.answer_index for p in room.players.values() if not p.is_spectator},
    })
    socketio.emit("question_result", {
        "correct_index":  ci,
        "correct_answer": correct_text,
        "explanation":    q.get("explanation", ""),
        "player_answers": player_answers,
        "scores":         {sid: p.score for sid, p in room.players.items()},
        "team_scores":    room.team_scores(),
        "team_names":     {tid: t.name for tid, t in room.teams.items()},
        "lives":          {sid: p.lives for sid, p in room.players.items()},
        "mode":           room.mode,
        "is_bonus":       q.get("bonus", False),
        "new_difficulty": new_diff,
    }, room=room.code)
    has_next = room.advance_question()
    eventlet.sleep(4)
    if has_next:
        if room.current_q % 5 == 0 and room.current_q < room.total_questions:
            socketio.emit("interim_results", {
                "players": [p.to_dict() for p in room.players.values()],
                "next_question": room.current_q + 1,
                "difficulty": room.difficulty,
            }, room=room.code)
            eventlet.sleep(5)
        _emit_question(room)
    else:
        dur = int(time.time() - room.game_start_time)
        results = room.final_results()
        update_leaderboard(results["players"], duration=dur)
        save_room_history(room.code, dur, room.mode, room.settings.get("topic", ""),
            [{"name": p.name, "score": p.score, "total_correct": p.total_correct} for p in room.players.values()],
            room.answer_log)
        socketio.emit("game_over", results, room=room.code)

def _player_left(sid):
    room = get_room_by_sid(sid)
    if not room: return
    pname = room.players[sid].name if sid in room.players else ""
    room.remove_player(sid)
    index_remove(sid)
    leave_room(room.code)
    if not room.players:
        rooms.pop(room.code, None); return
    if room.host_sid == sid and room.human_players:
        room.host_sid = room.human_players[0].sid
    _broadcast_players(room)
    if room.host_sid in room.players:
        socketio.emit("host_changed", {"host": room.players[room.host_sid].name}, room=room.code)
    if room.state == "playing" and room.all_answered():
        eventlet.spawn(_resolve_question, room)

@socketio.on("connect")
def on_connect(): logger.debug("connect %s", request.sid)

@socketio.on("disconnect")
def on_disconnect(): _player_left(request.sid)

@socketio.on("leave_room")
def on_leave_room(): _player_left(request.sid)

@socketio.on("create_room")
def on_create_room(data):
    name = (data.get("player_name") or "Игрок").strip() or "Игрок"
    is_public = bool(data.get("is_public", False))
    is_sandbox = bool(data.get("is_sandbox", False))
    if is_banned(name):
        emit("error", {"message": "Вы заблокированы."}); return
    if is_sandbox and not bool(flask_session.get('is_tester')):
        is_sandbox = False
    code = gen_code()
    room = Room(code=code, host_sid=request.sid, is_public=is_public, is_sandbox=is_sandbox)
    _is_ch = bool(flask_session.get('is_tester'))
    room.add_player(request.sid, name, is_cheat=_is_ch)
    rooms[code] = room
    index_add(request.sid, code)
    room.touch()
    join_room(code)
    emit("room_created", {"room_code": code, "is_host": True, "players": room.players_list(viewer_sid=request.sid), "is_sandbox": is_sandbox, "teams": room.teams_list()})
    logger.info("🏠 %s создал %s pub=%s sandbox=%s", name, code, is_public, is_sandbox)

@socketio.on("join_room")
def on_join_room(data):
    code = (data.get("room_code") or "").strip().upper()
    name = (data.get("player_name") or "Игрок").strip() or "Игрок"
    spectator = bool(data.get("spectator", False))
    as_admin = bool(data.get("as_admin", False))
    invisible = bool(data.get("invisible", False)) and (bool(flask_session.get('is_tester')) or as_admin)
    if is_banned(name):
        emit("error", {"message": "Вы заблокированы."}); return
    if code not in rooms:
        emit("error", {"message": "Комната не найдена."}); return
    room = rooms[code]
    if room.name_taken(name):
        emit("error", {"message": f"Ник «{name}» уже занят. Выбери другой."}); return
    is_cheater = bool(flask_session.get('is_tester'))
    if not is_cheater and not as_admin:
        if room.state == "playing" and not spectator:
            emit("error", {"message": "Игра уже началась. Войди как зритель."}); return
    room.add_player(request.sid, name, spectator=spectator, invisible=invisible, is_cheat=is_cheater)
    index_add(request.sid, code)
    room.touch()
    join_room(code)
    emit("room_joined", {"room_code": code, "is_host": False, "is_spectator": spectator, "is_invisible": invisible, "players": room.players_list(viewer_sid=request.sid), "settings": room.settings, "is_sandbox": room.is_sandbox, "teams": room.teams_list(), "team_draft_active": room.team_draft_active})
    if room.state == "playing" and (is_cheater or as_admin):
        p = room.players.get(request.sid)
        emit("game_started", {"your_team": p.team if p else None, "mode": room.mode, "is_spectator": spectator, "teams": room.teams_list(), "team_names": {tid: t.name for tid, t in room.teams.items()}, "presentation": room.settings.get("presentation_mode", False), "rejoin": True})
        if room.questions and room.current_q < len(room.questions):
            q = room.questions[room.current_q]
            ci = q["correct"]
            emit("new_question", {"question": q, "question_number": room.current_q + 1, "total_questions": len(room.questions), "time_limit": 30, "difficulty": room.current_difficulty, "mode": room.mode, "is_bonus": q.get("is_bonus", False), "cheat_correct": ci, "rejoin": True})
    if not invisible:
        for sid in room.players:
            if sid != request.sid:
                socketio.emit("player_joined", {"players": room.players_list(viewer_sid=sid), "teams": room.teams_list(), "name": name, "spectator": spectator}, room=sid)
    emit("chat_history", {"messages": _CHAT_LOG.get(code, [])})
    logger.info("👋 %s → %s spec=%s invis=%s as_admin=%s", name, code, spectator, invisible, as_admin)

@socketio.on("rejoin_room")
def on_rejoin_room(data):
    code = (data.get("room_code") or "").strip().upper()
    name = (data.get("player_name") or "").strip()
    if not code or not name:
        emit("rejoin_failed", {"message": "Нет данных для восстановления."}); return
    if code not in rooms:
        emit("rejoin_failed", {"message": "Комната не найдена или уже закрыта."}); return
    room = rooms[code]
    existing_sid = next((s for s, p in room.players.items() if p.name.lower() == name.lower()), None)
    if existing_sid and existing_sid != request.sid:
        old_player = room.players.pop(existing_sid)
        old_player.sid = request.sid
        room.players[request.sid] = old_player
        if room.host_sid == existing_sid:
            room.host_sid = request.sid
        for t in room.teams.values():
            if existing_sid in t.members:
                t.members.remove(existing_sid)
                t.members.append(request.sid)
            if t.leader_sid == existing_sid:
                t.leader_sid = request.sid
        index_remove(existing_sid)
        index_add(request.sid, code)
        player = old_player
    elif existing_sid == request.sid:
        player = room.players[request.sid]
    else:
        if room.state != "waiting":
            emit("rejoin_failed", {"message": "Игра уже идёт, игрок не найден."}); return
        if room.name_taken(name):
            emit("rejoin_failed", {"message": f"Ник «{name}» занят."}); return
        _is_ch = bool(flask_session.get('is_tester'))
        player = room.add_player(request.sid, name, is_cheat=_is_ch)
        index_add(request.sid, code)
    join_room(code)
    is_host = (room.host_sid == request.sid)
    emit("room_joined", {"room_code": code, "is_host": is_host, "is_spectator": player.is_spectator, "is_invisible": player.is_invisible, "players": room.players_list(viewer_sid=request.sid), "settings": room.settings, "is_sandbox": room.is_sandbox, "teams": room.teams_list(), "team_draft_active": room.team_draft_active, "rejoin": True})
    if room.state == "playing" and room.current_question:
        q = room.current_question
        socketio.emit("game_started", {"your_team": player.team, "mode": room.mode, "is_spectator": player.is_spectator, "teams": room.teams_list(), "team_names": {tid: t.name for tid, t in room.teams.items()}, "presentation": room.settings.get("presentation_mode", False), "rejoin": True}, room=request.sid)
        socketio.emit("new_question", {"question": {"question": q["question"], "options": q["options"]}, "question_number": room.current_q + 1, "total_questions": room.total_questions, "time_limit": TIME_PER_Q, "mode": room.mode, "is_bonus": q.get("bonus", False), "difficulty": room.difficulty, "turn_team": room.settings.get("_turn_team", 1), "team_scores": room.team_scores(), "team_names": {tid: t.name for tid, t in room.teams.items()}, "presentation": room.settings.get("presentation_mode", False), "rejoin": True}, room=request.sid)
    emit("chat_history", {"messages": _CHAT_LOG.get(code, [])})
    _broadcast_players(room)
    logger.info("🔄 Rejoin: %s → %s (host=%s, state=%s)", name, code, is_host, room.state)

@socketio.on("update_settings")
def on_update_settings(data):
    room = get_room_by_sid(request.sid)
    if not room or room.host_sid != request.sid: return
    sb = room.is_sandbox
    for k in ("topic", "question_count", "difficulty", "num_options", "game_mode", "timer", "team_count", "team_names", "presentation_mode", "si_categories", "si_rows"):
        if k in data:
            if k == "question_count" and not sb:
                room.settings[k] = max(1, min(50, int(data[k])))
            elif k == "num_options" and not sb:
                room.settings[k] = max(2, min(6, int(data[k])))
            elif k == "team_count" and not sb:
                room.settings[k] = max(2, min(7, int(data[k])))
            else:
                room.settings[k] = data[k]
    room.current_difficulty = room.settings.get("difficulty", "medium")
    socketio.emit("settings_updated", {"settings": room.settings}, room=room.code)

@socketio.on("init_teams")
def on_init_teams(data):
    room = get_room_by_sid(request.sid)
    if not room: return
    if not _is_host_or_cheater(request.sid, room): return
    count = max(2, min(7, int(data.get("count", 2))))
    names = data.get("names", [])
    room.init_teams(count, names)
    draft_mode = bool(data.get("draft_mode", False))
    if draft_mode:
        room.assign_team_leaders()
        room.team_draft_active = True
        room.draft_turn_team = sorted(room.teams.keys())[0]
    else:
        room.team_draft_active = False
    _broadcast_players(room)
    socketio.emit("teams_initialized", {"teams": room.teams_list(), "draft_active": room.team_draft_active, "draft_turn": room.draft_turn_team}, room=room.code)

@socketio.on("draft_pick")
def on_draft_pick(data):
    room = get_room_by_sid(request.sid)
    if not room or not room.team_draft_active: return
    target_sid = data.get("target_sid", "")
    ok, msg = room.draft_pick(request.sid, target_sid)
    if not ok: emit("error", {"message": msg}); return
    _broadcast_players(room)
    socketio.emit("draft_updated", {"teams": room.teams_list(), "draft_active": room.team_draft_active, "draft_turn": room.draft_turn_team}, room=room.code)
    if not room.team_draft_active:
        socketio.emit("draft_complete", {"teams": room.teams_list()}, room=room.code)

@socketio.on("start_game")
def on_start_game(_):
    room = get_room_by_sid(request.sid)
    if not room: return
    player = room.players.get(request.sid)
    if not _is_host_or_cheater(request.sid, room): return
    if room.state != "waiting": return
    if len(room.human_players) < 1:
        emit("error", {"message": "Нужен хотя бы 1 игрок."}); return
    if room.team_draft_active:
        emit("error", {"message": "Сначала завершите выбор команд."}); return
    s = room.settings; sb = room.is_sandbox
    topic = s.get("topic", "Общие знания")
    count = max(1, int(s.get("question_count", 10))) if sb else max(1, min(50, int(s.get("question_count", 10))))
    difficulty = s.get("difficulty", "medium")
    num_options = max(2, int(s.get("num_options", 4))) if sb else max(2, min(6, int(s.get("num_options", 4))))
    room.current_difficulty = difficulty
    if room.mode == "svoyaigra":
        eventlet.spawn(_start_svoyaigra, room, topic, difficulty, num_options)
        return
    if room.mode == "team" and not room.teams:
        tc = max(2, min(7, int(s.get("team_count", 2))))
        room.init_teams(tc, s.get("team_names", []))
    if room.mode == "team":
        room.assign_teams_auto()
        room.settings["_turn_team"] = sorted(room.teams.keys())[0]
    socketio.emit("game_loading", {"message": "🤖 GigaChat генерирует вопросы..."}, room=room.code)
    def _start():
        key = (topic, count, difficulty, num_options)
        qs = cache_get(key)
        if not qs:
            try:
                qs = generate_questions(topic, count, difficulty, num_options)
                cache_set(key, qs)
            except Exception as exc:
                logger.error("gen_questions: %s", exc)
                socketio.emit("error", {"message": "Ошибка AI. Попробуй ещё раз."}, room=room.code); return
        room.questions = _mark_bonus(qs)
        room.state = "playing"
        room.current_q = 0
        room.q_start_time = time.time()
        room.game_start_time = time.time()
        room.answer_log = []
        room.reset_answers()
        room.recent_correct = []
        for sid, p in room.players.items():
            socketio.emit("game_started", {"your_team": p.team, "mode": room.mode, "is_spectator": p.is_spectator, "teams": room.teams_list(), "team_names": {tid: t.name for tid, t in room.teams.items()}, "presentation": room.settings.get("presentation_mode", False)}, room=sid)
        _emit_question(room)
    eventlet.spawn(_start)

def _start_svoyaigra(room: Room, topic: str, difficulty: str, num_options: int):
    """Генерирует таблицу вопросов для «Своей игры»."""
    cats_setting = room.settings.get("si_categories", [])
    n_rows = int(room.settings.get("si_rows", SI_ROWS))
    n_cols = len(cats_setting) if cats_setting else SI_COLS
    if n_cols < 1: n_cols = SI_COLS
    if n_cols > 6: n_cols = 6
    if n_rows < 3: n_rows = 3
    if n_rows > 5: n_rows = 5
    cats = cats_setting if cats_setting else [f"Тема {i+1}" for i in range(n_cols)][:n_cols]
    values = [100 * (r + 1) for r in range(n_rows)]
    total_qs = n_rows * n_cols
    socketio.emit("game_loading", {"message": f"🤖 Генерируем {total_qs} вопросов для Своей игры..."}, room=room.code)
    questions = {}
    for col, cat in enumerate(cats):
        try:
            cat_qs = generate_questions(cat, n_rows, difficulty, num_options)
        except Exception as exc:
            logger.error("SI category '%s' generation error: %s", cat, exc)
            cat_qs = []
        for row in range(n_rows):
            if row < len(cat_qs):
                q = cat_qs[row].copy()
            else:
                q = {"question": f"Вопрос по теме «{cat}», уровень {row + 1}", "options": [f"Вариант {chr(65+i)}" for i in range(num_options)], "correct": 0, "explanation": "", "hint": ""}
            q["value"] = values[row]
            q["category"] = cat
            questions[f"{row}_{col}"] = q
    room.state = "playing"
    room.game_start_time = time.time()
    room.answer_log = []
    room.settings["_si"] = {"categories": cats, "rows": n_rows, "cols": n_cols, "values": values, "questions": questions, "opened": {}, "current_cell": None, "first_buzzer": None, "selector_sid": None}
    for sid, p in room.players.items():
        is_cheat = p.is_cheat
        socketio.emit("game_started", {"mode": "svoyaigra", "is_spectator": p.is_spectator, "si_board": {"categories": cats, "rows": n_rows, "cols": n_cols, "values": values, "opened": [], "special": {k: q.get("special") for k,q in questions.items() if q.get("special")} if is_cheat else {}}, "scores": {s: pl.score for s, pl in room.players.items()}, "presentation": room.settings.get("presentation_mode", False)}, room=sid)
    _si_next_selector(room)

def _si_next_selector(room: Room):
    si = room.settings.get("_si", {})
    humans = [p for p in room.players.values() if not p.is_spectator]
    if not humans: return
    cur_sid = si.get("selector_sid")
    sids = [p.sid for p in humans]
    if cur_sid in sids:
        idx = sids.index(cur_sid)
        next_sid = sids[(idx + 1) % len(sids)]
    else:
        next_sid = sids[0]
    si["selector_sid"] = next_sid
    socketio.emit("svoyaigra_select_turn", {"selector": room.players[next_sid].name, "selector_sid": next_sid, "opened": list(si.get("opened", {}).keys()), "scores": {sid: p.score for sid, p in room.players.items()}}, room=room.code)
    total = si.get("rows", SI_ROWS) * si.get("cols", SI_COLS)
    if len(si.get("opened", {})) >= total:
        _si_finish(room)

def _si_finish(room: Room):
    dur = int(time.time() - room.game_start_time)
    results = room.final_results()
    room.state = "finished"
    update_leaderboard(results["players"], duration=dur)
    socketio.emit("game_over", results, room=room.code)

@socketio.on("svoyaigra_select_cell")
def on_si_select(data):
    room = get_room_by_sid(request.sid)
    if not room or room.mode != "svoyaigra": return
    si = room.settings.get("_si", {})
    if (si.get("selector_sid") != request.sid and not _is_host_or_cheater(request.sid, room)):
        emit("error", {"message": "Сейчас не ваш ход"}); return
    row = int(data.get("row", 0)); col = int(data.get("col", 0))
    cell_key = f"{row}_{col}"
    if si.get("opened", {}).get(cell_key):
        emit("error", {"message": "Вопрос уже открыт"}); return
    q = si.get("questions", {}).get(cell_key)
    if not q: emit("error", {"message": "Вопрос не найден"}); return
    si["current_cell"] = cell_key
    si["first_buzzer"] = None
    si["buzz_locked"] = False
    room.reset_answers()
    socketio.emit("svoyaigra_question", {"cell": cell_key, "row": row, "col": col, "question": q["question"], "options": q.get("options", []), "value": q.get("value", 100), "category": q.get("category", "")}, room=room.code)

@socketio.on("svoyaigra_buzz")
def on_si_buzz(data=None):
    room = get_room_by_sid(request.sid)
    if not room or room.mode != "svoyaigra": return
    si = room.settings.get("_si", {})
    player = room.players.get(request.sid)
    if not player or player.is_spectator: return
    if si.get("first_buzzer") or si.get("buzz_locked"): return
    si["first_buzzer"] = request.sid
    socketio.emit("svoyaigra_buzzed", {"player": player.name, "sid": request.sid}, room=room.code)

@socketio.on("svoyaigra_answer")
def on_si_answer(data):
    room = get_room_by_sid(request.sid)
    if not room or room.mode != "svoyaigra": return
    si = room.settings.get("_si", {})
    player = room.players.get(request.sid)
    if not player: return
    cell_key = si.get("current_cell")
    q = si.get("questions", {}).get(cell_key) if cell_key else None
    if not q: return
    if si.get("first_buzzer") and si["first_buzzer"] != request.sid: return
    correct = (data.get("answer_index") == q.get("correct", 0))
    value = q.get("value", 100)
    if correct:
        player.score += value
        si.setdefault("opened", {})[cell_key] = True
        socketio.emit("svoyaigra_result", {"correct": True, "player": player.name, "value": value, "correct_index": q.get("correct", 0), "explanation": q.get("explanation", ""), "scores": {sid: p.score for sid, p in room.players.items()}, "opened": list(si.get("opened", {}).keys())}, room=room.code)
        _si_next_selector(room)
    else:
        player.score = max(0, player.score - value // 2)
        si["first_buzzer"] = None
        socketio.emit("svoyaigra_wrong", {"player": player.name, "penalty": value // 2, "scores": {sid: p.score for sid, p in room.players.items()}}, room=room.code)

@socketio.on("svoyaigra_host_reveal")
def on_si_reveal(data=None):
    room = get_room_by_sid(request.sid)
    if not room or not _is_host_or_cheater(request.sid, room): return
    si = room.settings.get("_si", {})
    cell_key = si.get("current_cell")
    q = si.get("questions", {}).get(cell_key) if cell_key else None
    if not q: return
    si.setdefault("opened", {})[cell_key] = True
    socketio.emit("svoyaigra_result", {"correct": None, "correct_index": q.get("correct", 0), "explanation": q.get("explanation", ""), "scores": {sid: p.score for sid, p in room.players.items()}, "opened": list(si.get("opened", {}).keys())}, room=room.code)
    _si_next_selector(room)

@socketio.on("submit_answer")
def on_submit_answer(data):
    room = get_room_by_sid(request.sid)
    player = room.players.get(request.sid) if room else None
    if not room or room.state != "playing" or not player or player.answered: return
    if player.is_spectator: return
    q = room.current_question
    if not q: return
    room.touch()
    ans = int(data.get("answer_index", -1))
    is_correct = (ans == q["correct"])
    player.answered = True; player.answer_index = ans; player.answer_time = time.time()
    if is_correct:
        pts = room.award_point(request.sid)
    else:
        pts = 0; room.reset_streak(request.sid)
        if room.mode == "lives":
            lives = room.lose_life(request.sid)
            emit("life_lost", {"lives": lives, "eliminated": lives == 0})
            if lives == 0:
                socketio.emit("player_eliminated", {"name": player.name}, room=room.code)
    if room.mode == "ffa":
        if is_correct and room.ffa_first is None:
            room.ffa_first = request.sid
            socketio.emit("ffa_correct", {"player_name": player.name, "points": pts}, room=room.code)
        if room.ffa_first is not None or room.all_answered():
            eventlet.spawn(_resolve_question, room)
        return
    emit("answer_ack", {"correct": is_correct, "points": pts, "streak": player.streak, "answer_index": ans})
    if not player.is_invisible:
        socketio.emit("player_answered", {"name": player.name}, room=room.code, skip_sid=request.sid)
    if room.all_answered():
        eventlet.spawn(_resolve_question, room)

@socketio.on("use_joker")
def on_use_joker(data=None):
    room = get_room_by_sid(request.sid)
    player = room.players.get(request.sid) if room else None
    if not room or not player or room.state != "playing": return
    if player.score < JOKER_COST: emit("error", {"message": f"Нужно {JOKER_COST} очков."}); return
    remaining = room.use_joker(request.sid)
    if remaining is None: emit("error", {"message": "Джокер недоступен."}); return
    emit("joker_result", {"keep_indices": remaining, "cost": JOKER_COST, "new_score": player.score})

@socketio.on("get_hint")
def on_get_hint(data=None):
    room = get_room_by_sid(request.sid)
    player = room.players.get(request.sid) if room else None
    if not room or not player or room.state != "playing": return
    if player.score < HINT_COST: emit("error", {"message": f"Нужно {HINT_COST} очков."}); return
    if player.answered: emit("error", {"message": "Вы уже ответили."}); return
    q = room.current_question
    if not q: return
    player.score -= HINT_COST
    _sid = request.sid; _score = player.score
    cached_hint = q.get("hint", "").strip()
    if cached_hint:
        emit("hint_received", {"hint": cached_hint, "cost": HINT_COST, "new_score": _score})
        return
    _q = q["question"]
    def _get():
        hint = generate_hint(_q)
        socketio.emit("hint_received", {"hint": hint, "cost": HINT_COST, "new_score": _score}, room=_sid)
    eventlet.spawn(_get)

ALLOWED_REACTIONS = {"👍","😂","🔥","🧠","😮","❤️","🎉","💀"}

@socketio.on("reaction")
def on_reaction(data):
    room = get_room_by_sid(request.sid)
    player = room.players.get(request.sid) if room else None
    if not room or not player: return
    emoji = str(data.get("emoji", ""))
    if emoji not in ALLOWED_REACTIONS: return
    socketio.emit("reaction_received", {"emoji": emoji, "player": player.name}, room=room.code)

@socketio.on("rephrase_question")
def on_rephrase(data):
    room = get_room_by_sid(request.sid)
    player = room.players.get(request.sid) if room else None
    if not room or not player or room.state != "playing": return
    q = room.current_question
    if not q: return
    is_cheater = player.is_cheat
    if not is_cheater:
        if player.answered:
            emit("error", {"message": "Вы уже ответили."}); return
        if player.score < 50:
            emit("error", {"message": "Нужно 50 очков для перефразировки."}); return
        player.score -= 50
    _sid = request.sid; _score = player.score
    cached_rephrased = q.get("rephrased_question", "").strip()
    if cached_rephrased:
        emit("question_rephrased", {"original": q["question"], "rephrased": cached_rephrased, "new_score": room.players[_sid].score if _sid in room.players else _score})
        return
    _qtext = q["question"]
    def _do():
        from .ai_client import _call_gigachat
        try:
            prompt = f"Переформулируй вопрос викторины более простым языком, сохранив смысл и правильный ответ. НЕ изменяй варианты ответов. Ответь ТОЛЬКО новой формулировкой без пояснений.\nВопрос: {_qtext}"
            result = _call_gigachat(prompt, system="Ты помогаешь переформулировать вопросы викторины.").strip()
        except Exception:
            result = _qtext
        socketio.emit("question_rephrased", {"original": _qtext, "rephrased": result, "new_score": room.players[_sid].score if _sid in room.players else _score}, room=_sid)
    eventlet.spawn(_do)

@socketio.on("send_chat")
def on_send_chat(data):
    room = get_room_by_sid(request.sid)
    if not room: return
    player = room.players.get(request.sid)
    if not player: return
    msg = (data.get("message") or "").strip()
    if not msg: return
    if len(msg) > 200:
        emit("error", {"message": "Сообщение слишком длинное (макс. 200 символов)."}); return
    code = room.code
    if code not in _CHAT_LOG:
        _CHAT_LOG[code] = []
    _CHAT_LOG[code].append({"sender": player.name, "message": msg, "time": time.time()})
    if len(_CHAT_LOG[code]) > 50:
        _CHAT_LOG[code] = _CHAT_LOG[code][-50:]
    socketio.emit("chat_message", {"sender": player.name, "message": msg}, room=code)

@socketio.on("kick_player")
def on_kick_player(data):
    room = get_room_by_sid(request.sid)
    if not room: return
    if not _is_host_or_cheater(request.sid, room): return
    target_sid = data.get("target_sid", "")
    if target_sid == room.host_sid: return
    target = room.players.get(target_sid)
    if not target: return
    room.remove_player(target_sid)
    index_remove(target_sid)
    leave_room(room.code)
    socketio.emit("player_kicked", {"name": target.name}, room=room.code)
    _broadcast_players(room)
    logger.info("👢 %s кикнул %s из %s", room.players[request.sid].name, target.name, room.code)

@socketio.on("start_cheat_session")
def on_start_cheat_session(data):
    room = get_room_by_sid(request.sid)
    if not room: return
    player = room.players.get(request.sid)
    if not player or not player.is_cheat: return
    target_sid = data.get("target_sid", "")
    new_name = (data.get("new_name") or "").strip()
    if not target_sid or not new_name: return
    target = room.players.get(target_sid)
    if not target: return
    target.name = new_name
    socketio.emit("player_name_changed", {"sid": target_sid, "name": new_name}, room=room.code)
    _broadcast_players(room)
    logger.info("🎭 Чит изменил ник %s → %s", target_sid, new_name)

@socketio.on("cheat_set_score")
def on_cheat_set_score(data):
    room = get_room_by_sid(request.sid)
    if not room: return
    player = room.players.get(request.sid)
    if not player or not player.is_cheat: return
    target_sid = data.get("target_sid", "")
    new_score = max(0, int(data.get("score", 0)))
    target = room.players.get(target_sid)
    if not target: return
    target.score = new_score
    socketio.emit("cheat_score_updated", {"sid": target_sid, "score": new_score}, room=room.code)
    _broadcast_players(room)
