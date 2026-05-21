# -*- coding: utf-8 -*-
import os, time, logging
from flask import Blueprint, render_template, jsonify, request, session
from .game_logic import (
    get_leaderboard_top, get_player_rank, rooms,
    ban_user, unban_user, get_all_bans,
    get_room_history, get_all_users, reset_user_stats, reset_server_stats,
    _sid_room
)
from .ai_client import active_backend
from .user_db import (
    register_user, login_user, get_user, update_user_stats, add_coins,
    spend_coins, get_level_from_xp,
    create_ugc_question, get_ugc_questions, get_user_ugc,
    vote_ugc, report_ugc, admin_moderate_ugc, get_ugc_pending,
    get_campaign_progress, save_campaign_result, CAMPAIGN_LEVELS,
    get_achievements, check_and_unlock_achievements, unlock_achievement,
    ACHIEVEMENTS
)
from .learn_mode import generate_learn_questions, extract_text_from_url

logger    = logging.getLogger(__name__)
bp        = Blueprint("main", __name__)

# Читаем коды из приложения (они уже загружены в __init__)
from . import ADMIN_SECRET_KEY, CHEAT_TESTER_CODE


def _admin():
    if not session.get("is_admin"):
        return jsonify({"error": "Нет доступа"}), 403
    return None

def _auth_user():
    """Возвращает username из сессии или None."""
    return session.get("username")


# ─── Основные маршруты ────────────────────────────────────────────────────────

@bp.route("/")
def index(): return render_template("index.html")

@bp.route("/health")
def health(): return jsonify({"status": "ok", "ts": time.time(), "ai": active_backend()})


# ─── Аутентификация ───────────────────────────────────────────────────────────

@bp.route("/api/auth/register", methods=["POST"])
def api_register():
    body = request.get_json(silent=True) or {}
    ok, msg = register_user(str(body.get("username","")).strip(), str(body.get("password","")))
    if ok:
        session["username"] = body["username"].strip()
        return jsonify({"ok": True, "user": get_user(body["username"].strip())})
    return jsonify({"ok": False, "error": msg}), 400

@bp.route("/api/auth/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username","")).strip()
    ok, msg  = login_user(username, str(body.get("password","")))
    if ok:
        session["username"] = username
        user = get_user(username)
        user["level"] = get_level_from_xp(user.get("xp",0))
        return jsonify({"ok": True, "user": user})
    return jsonify({"ok": False, "error": msg}), 401

@bp.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.pop("username", None)
    return jsonify({"ok": True})

@bp.route("/api/auth/me")
def api_me():
    u = _auth_user()
    if not u:
        return jsonify({"logged_in": False})
    user = get_user(u)
    if not user:
        session.pop("username", None)
        return jsonify({"logged_in": False})
    user["level"] = get_level_from_xp(user.get("xp", 0))
    user["achievements"] = get_achievements(u)
    return jsonify({"logged_in": True, "user": user})


# ─── Лидерборд ────────────────────────────────────────────────────────────────

@bp.route("/api/leaderboard")
def api_leaderboard():
    n = min(int(request.args.get("n", 50)), 200)
    return jsonify(get_leaderboard_top(n))

@bp.route("/api/rank/<username>")
def api_rank(username): return jsonify(get_player_rank(username))


# ─── Комнаты ─────────────────────────────────────────────────────────────────

@bp.route("/api/public_rooms")
def api_public_rooms():
    return jsonify([{
        "code": r.code, "state": r.state, "players": len(r.human_players),
        "mode": r.mode, "topic": r.settings.get("topic","")
    } for r in rooms.values()
        if getattr(r,"is_public",False) and r.state in ("waiting","playing")])

@bp.route("/api/rooms")
def api_rooms():
    return jsonify([{
        "code": r.code, "state": r.state,
        "players": len(r.players), "mode": r.mode
    } for r in rooms.values()])

@bp.route("/api/check_session", methods=["POST"])
def api_check_session():
    body = request.get_json(silent=True) or {}
    code = str(body.get("room_code","")).strip().upper()
    name = str(body.get("player_name","")).strip()
    if not code or not name:
        return jsonify({"ok": True})
    room = rooms.get(code)
    if not room:
        return jsonify({"ok": True})
    existing = next((s for s, p in room.players.items() if p.name.lower()==name.lower()), None)
    return jsonify({"ok": True, "already_in": existing is not None})
    

# ─── UGC ─────────────────────────────────────────────────────────────────────

@bp.route("/api/ugc/questions")
def api_ugc_list():
    topic  = request.args.get("topic","")
    limit  = min(int(request.args.get("limit",50)), 100)
    offset = int(request.args.get("offset",0))
    qs     = get_ugc_questions(topic=topic, status="approved", limit=limit, offset=offset)
    return jsonify({"questions": qs, "count": len(qs)})

@bp.route("/api/ugc/my")
def api_ugc_my():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    return jsonify({"questions": get_user_ugc(u)})

@bp.route("/api/ugc/create", methods=["POST"])
def api_ugc_create():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body    = request.get_json(silent=True) or {}
    ok, res = create_ugc_question(
        author     = u,
        question   = str(body.get("question","")),
        options    = body.get("options",[]),
        correct    = int(body.get("correct",0)),
        topic      = str(body.get("topic","")),
        difficulty = int(body.get("difficulty",2)),
    )
    if ok:
        # Начисляем монеты за создание
        add_coins(u, 5)
        new_achs = check_and_unlock_achievements(u)
        unlock_achievement(u, "ugc_creator")
        return jsonify({"ok": True, "id": res, "coins_earned": 5, "new_achievements": new_achs})
    return jsonify({"ok": False, "error": res}), 400

@bp.route("/api/ugc/vote", methods=["POST"])
def api_ugc_vote():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body = request.get_json(silent=True) or {}
    qid  = int(body.get("question_id",0))
    vote = int(body.get("vote",1))
    if vote not in (1,-1): return jsonify({"error":"vote должно быть 1 или -1"}), 400
    ok = vote_ugc(qid, u, vote)
    return jsonify({"ok": ok})

@bp.route("/api/ugc/report", methods=["POST"])
def api_ugc_report():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body = request.get_json(silent=True) or {}
    ok   = report_ugc(int(body.get("question_id",0)), u, str(body.get("reason","")))
    return jsonify({"ok": ok})


# ─── Кампания ─────────────────────────────────────────────────────────────────

@bp.route("/api/campaign/progress")
def api_campaign_progress():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    return jsonify(get_campaign_progress(u))

@bp.route("/api/campaign/levels")
def api_campaign_levels():
    u = _auth_user()
    if u:
        return jsonify(get_campaign_progress(u))
    # Гость видит уровни, все заблокированы
    return jsonify({
        "levels": [{**l,"stars":0,"best_score":0,"locked":True} for l in CAMPAIGN_LEVELS],
        "total_stars": 0
    })

@bp.route("/api/campaign/result", methods=["POST"])
def api_campaign_result():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body    = request.get_json(silent=True) or {}
    level_id    = int(body.get("level_id",0))
    score       = int(body.get("score",0))
    correct     = int(body.get("correct",0))
    total       = int(body.get("total_questions",1))
    result      = save_campaign_result(u, level_id, score, correct, total)
    # Достижения
    if result["stars"] == 3:
        unlock_achievement(u, "perfect_level")
    new_achs = check_and_unlock_achievements(u)
    result["new_achievements"] = new_achs
    return jsonify(result)

@bp.route("/api/campaign/start", methods=["POST"])
def api_campaign_start():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body     = request.get_json(silent=True) or {}
    level_id = int(body.get("level_id", 0))
    level    = next((l for l in CAMPAIGN_LEVELS if l["id"]==level_id), None)
    if not level:
        return jsonify({"error": "Уровень не найден"}), 404
    prog = get_campaign_progress(u)
    total_stars = prog["total_stars"]
    if total_stars < level["req_stars"]:
        return jsonify({"error": f"Нужно {level['req_stars']} звёзд"}), 403
    from .ai_client import generate_questions
    questions = generate_questions(
        topic       = level["topic"],
        count       = level["questions"],
        difficulty  = level["difficulty"],
        num_options = 4
    )
    return jsonify({"questions": questions, "level": level})

# ─── Режим обучения ───────────────────────────────────────────────────────────

@bp.route("/api/learn/from_text", methods=["POST"])
def api_learn_text():
    body    = request.get_json(silent=True) or {}
    content = str(body.get("content","")).strip()
    num     = min(int(body.get("num_questions",6)), 8)
    if len(content) < 50:
        return jsonify({"error":"Текст слишком короткий (мин. 50 символов)"}), 400
    questions = generate_learn_questions(content, num)
    if not questions:
        return jsonify({"error":"Не удалось сгенерировать вопросы. Попробуй ещё раз."}), 500
    # Достижение за первый запуск режима обучения
    u = _auth_user()
    if u:
        unlock_achievement(u, "learn_mode")
    return jsonify({"questions": questions, "count": len(questions)})

@bp.route("/api/learn/from_url", methods=["POST"])
def api_learn_url():
    body = request.get_json(silent=True) or {}
    url  = str(body.get("url","")).strip()
    num  = min(int(body.get("num_questions",6)), 8)
    if not url.startswith(("http://","https://")):
        return jsonify({"error":"Некорректный URL"}), 400
    ok, text = extract_text_from_url(url)
    if not ok:
        return jsonify({"error": text}), 400
    if len(text) < 50:
        return jsonify({"error":"Страница содержит слишком мало текста"}), 400
    questions = generate_learn_questions(text, num)
    if not questions:
        return jsonify({"error":"Не удалось сгенерировать вопросы"}), 500
    u = _auth_user()
    if u: unlock_achievement(u, "learn_mode")
    return jsonify({"questions": questions, "count": len(questions)})


# ─── Достижения ───────────────────────────────────────────────────────────────

@bp.route("/api/achievements")
def api_achievements():
    u = _auth_user()
    if not u: return jsonify({"achievements":[]})
    return jsonify({"achievements": get_achievements(u)})


# ─── Магазин ─────────────────────────────────────────────────────────────────

SHOP_ITEMS = {
    "hint_free":     {"name":"Бесплатная подсказка",    "cost":30,  "desc":"Подсказка без списания очков"},
    "skip_question": {"name":"Пропуск вопроса",         "cost":50,  "desc":"Пропусти 1 вопрос в кампании"},
    "double_xp":     {"name":"Двойной XP (1 игра)",     "cost":100, "desc":"Удвоение XP в следующей игре"},
}

@bp.route("/api/shop/items")
def api_shop_items():
    u = _auth_user()
    coins = get_user(u)["coins"] if u else 0
    return jsonify({"items": SHOP_ITEMS, "coins": coins})

@bp.route("/api/shop/buy", methods=["POST"])
def api_shop_buy():
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body    = request.get_json(silent=True) or {}
    item_id = str(body.get("item_id",""))
    item    = SHOP_ITEMS.get(item_id)
    if not item:
        return jsonify({"error":"Товар не найден"}), 404
    if not spend_coins(u, item["cost"]):
        return jsonify({"error":"Недостаточно монет"}), 400
    user = get_user(u)
    return jsonify({"ok": True, "item": item_id, "coins_left": user["coins"] if user else 0})


# ─── Чит-меню (активация по коду) ────────────────────────────────────────────

@bp.route("/api/cheat/activate", methods=["POST"])
def api_cheat_activate():
    """Активация чит-режима через API. Код хранится в .env как CHEAT_TESTER_CODE."""
    body = request.get_json(silent=True) or {}
    code = str(body.get("code","")).strip()
    username = str(body.get("username","")).strip()
    
    if not username:
        return jsonify({"ok": False, "error": "Username required"}), 400
    
    if code == CHEAT_TESTER_CODE:
        session["is_tester"] = True
        session["tester_username"] = username
        logger.info(f"✅ Cheat activated for user: {username} from {request.remote_addr}")
        return jsonify({"ok": True})
    
    logger.warning(f"❌ Invalid cheat code attempt for user: {username} from {request.remote_addr}")
    return jsonify({"ok": False, "error": "Invalid code"}), 403

@bp.route("/api/cheat/check", methods=["GET"])
def api_cheat_check():
    """Проверка статуса читера для текущего пользователя."""
    return jsonify({
        "is_tester": session.get("is_tester", False),
        "is_admin": session.get("is_admin", False)
    })

@bp.route("/api/cheat/logout", methods=["POST"])
def api_cheat_logout():
    """Деактивация чит-режима."""
    session.pop("is_tester", None)
    session.pop("tester_username", None)
    session.pop("is_admin", None)
    return jsonify({"ok": True})

@bp.route("/verify_cheat", methods=["POST"])
def verify_cheat():
    """Устаревший endpoint, использует api_cheat_activate."""
    body = request.get_json(silent=True) or {}
    key  = str(body.get("key","")).strip()
    if key == CHEAT_TESTER_CODE:
        session["is_tester"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403


# ─── Администрирование ────────────────────────────────────────────────────────

@bp.route("/api/admin/activate", methods=["POST"])
def api_admin_activate():
    """Активация админ-режима через API. Ключ хранится в .env как ADMIN_SECRET_KEY."""
    body = request.get_json(silent=True) or {}
    key = str(body.get("key","")).strip()
    logger.info(f"🔑 Admin activation attempt: key={key!r}, expected={ADMIN_SECRET_KEY!r}")
    
    if key == ADMIN_SECRET_KEY:
        session["is_admin"] = True
        logger.info(f"✅ Admin activated from {request.remote_addr}")
        return jsonify({"ok": True, "role": "admin"})
    
    logger.warning(f"❌ Invalid admin key attempt from {request.remote_addr}: got {key!r}")
    return jsonify({"ok": False, "error": "Invalid key"}), 403

@bp.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})

@bp.route("/verify_admin", methods=["POST"])
def verify_admin_compat():
    """Устаревший endpoint для совместимости."""
    body = request.get_json(silent=True) or {}
    if str(body.get("key","")).strip() == ADMIN_SECRET_KEY:
        session["is_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403

@bp.route("/api/admin/rooms")
def api_admin_rooms():
    err = _admin()
    if err: return err
    now = int(time.time())
    return jsonify([{
        "code": r.code, "state": r.state, "players": len(r.players), "mode": r.mode,
        "host": (r.players[r.host_sid].name if r.host_sid in r.players else ""),
        "is_public": getattr(r,"is_public",False), "topic": r.settings.get("topic",""),
        "is_sandbox": getattr(r,"is_sandbox",False),
        "idle_secs": now - int(r.last_activity),
    } for r in rooms.values()])

@bp.route("/api/admin/users")
def api_admin_users():
    err = _admin()
    if err: return err
    return jsonify(get_all_users(nick=request.args.get("nick",""), limit=200))

@bp.route("/api/admin/room_history/<code>")
def api_admin_history(code):
    err = _admin()
    if err: return err
    return jsonify(get_room_history(code))

@bp.route("/api/admin/bans")
def api_admin_bans():
    err = _admin()
    if err: return err
    return jsonify(get_all_bans())

@bp.route("/api/admin/ban", methods=["POST"])
def api_admin_ban():
    err = _admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    ok   = ban_user(str(body.get("identifier","")).strip(), str(body.get("reason","")).strip(), int(body.get("duration_minutes",60)))
    return jsonify({"ok": ok})

@bp.route("/api/admin/unban", methods=["POST"])
def api_admin_unban():
    err = _admin()
    if err: return err
    ok = unban_user(str((request.get_json(silent=True) or {}).get("identifier","")).strip())
    return jsonify({"ok": ok})

@bp.route("/api/admin/reset_user", methods=["POST"])
def api_admin_reset_user():
    err = _admin()
    if err: return err
    ok = reset_user_stats(str((request.get_json(silent=True) or {}).get("username","")).strip())
    return jsonify({"ok": ok})

@bp.route("/api/admin/reset_server", methods=["POST"])
def api_admin_reset_server():
    err = _admin()
    if err: return err
    ok      = reset_server_stats()
    removed = sum(1 for c in list(rooms.keys())
                  if rooms[c].state=="finished" and not rooms.pop(c,None) is None)
    return jsonify({"ok": ok, "removed_rooms": removed})

# ─── IP-Бан (новый функционал) ────────────────────────────────────────────────

@bp.route("/api/admin/ip_ban", methods=["POST"])
def api_admin_ip_ban():
    """Блокировка IP-адреса."""
    err = _admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    ip = str(body.get("ip","")).strip()
    reason = str(body.get("reason","")).strip()
    duration = int(body.get("duration_minutes", 1440))  # по умолчанию 24 часа
    
    if not ip:
        return jsonify({"ok": False, "error": "IP required"}), 400
    
    # TODO: Реализовать ip_ban в game_logic.py
    # Пока заглушка
    logger.info(f"🌐 IP banned: {ip} by admin, reason: {reason}, duration: {duration}min")
    return jsonify({"ok": True})

@bp.route("/api/admin/ip_unban", methods=["POST"])
def api_admin_ip_unban():
    """Разблокировка IP-адреса."""
    err = _admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    ip = str(body.get("ip","")).strip()
    
    if not ip:
        return jsonify({"ok": False, "error": "IP required"}), 400
    
    # TODO: Реализовать ip_unban в game_logic.py
    logger.info(f"✅ IP unbanned: {ip} by admin")
    return jsonify({"ok": True})

@bp.route("/api/admin/ip_bans")
def api_admin_ip_bans():
    """Список заблокированных IP."""
    err = _admin()
    if err: return err
    
    # TODO: Реализовать get_all_ip_bans в game_logic.py
    return jsonify([])  # Пока пустой список

@bp.route("/api/admin/ugc_pending")
def api_admin_ugc_pending():
    err = _admin()
    if err: return err
    return jsonify({"questions": get_ugc_pending(50)})

@bp.route("/api/admin/ugc_moderate", methods=["POST"])
def api_admin_ugc_moderate():
    err = _admin()
    if err: return err
    body    = request.get_json(silent=True) or {}
    qid     = int(body.get("question_id",0))
    approve = bool(body.get("approve",False))
    reason  = str(body.get("reason",""))
    ok      = admin_moderate_ugc(qid, approve, reason)
    return jsonify({"ok": ok})

@bp.route("/api/cheat/room_stats/<code>")
def api_cheat_stats(code):
    r = rooms.get(code.upper())
    if not r: return jsonify({"error":"not found"}), 404
    q = r.current_question
    if not q: return jsonify({"answers": {}})
    counts={}; players={}
    for p in r.players.values():
        if p.answered and p.answer_index is not None:
            i = p.answer_index
            counts[i] = counts.get(i,0)+1
            players.setdefault(i,[]).append(p.name)
    return jsonify({
        "answer_counts": counts, "answer_players": players,
        "total_answered": sum(1 for p in r.players.values() if p.answered),
        "total_active": len(r.active_players)
    })

# ─── Админские функции управления аккаунтами ─────────────────────────────────

@bp.route("/api/admin/impersonate", methods=["POST"])
def api_admin_impersonate():
    """Админ может войти в аккаунт игрока (без выкидывания самого игрока)."""
    err = _admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    target_username = str(body.get("username","")).strip()
    
    if not target_username:
        return jsonify({"error": "Username required"}), 400
    
    user = get_user(target_username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Сохраняем оригинальную сессию админа
    original_admin = session.get("is_admin")
    
    # Добавляем метку имперсонации
    session["impersonating"] = True
    session["impersonating_user"] = target_username
    session["username"] = target_username
    
    logger.info(f"🎭 Admin impersonating: {target_username}")
    
    return jsonify({
        "ok": True,
        "user": user,
        "message": f"Вы вошли как {target_username}"
    })

@bp.route("/api/admin/impersonate/stop", methods=["POST"])
def api_admin_stop_impersonate():
    """Админ выходит из имперсонации."""
    err = _admin()
    if err: return err
    
    target = session.pop("impersonating_user", None)
    session.pop("impersonating", None)
    
    logger.info(f"🎭 Stop impersonating: {target}")
    
    return jsonify({"ok": True, "message": "Вышли из аккаунта"})

@bp.route("/api/admin/user/<username>/edit", methods=["POST"])
def api_admin_edit_user(username):
    """Админ редактирует профиль игрока."""
    err = _admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    
    user = get_user(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Что можно редактировать
    if "display_name" in body:
        new_name = str(body["display_name"]).strip()
        if len(new_name) > 50:
            return jsonify({"error": "Слишком длинное имя"}), 400
        # Обновляем в БД (нужно добавить метод в user_db)
        # db_execute("UPDATE users SET display_name=? WHERE username=?", (new_name, username))
    
    if "coins" in body:
        new_coins = int(body["coins"])
        if new_coins < 0:
            return jsonify({"error": "Монеты не могут быть отрицательными"}), 400
        # db_execute("UPDATE users SET coins=? WHERE username=?", (new_coins, username))
    
    if "xp" in body:
        new_xp = int(body["xp"])
        if new_xp < 0:
            return jsonify({"error": "XP не может быть отрицательным"}), 400
        # db_execute("UPDATE users SET xp=? WHERE username=?", (new_xp, username))
    
    if "avatar" in body:
        # Проверка что аватар из списка допустимых
        avatar = str(body["avatar"]).strip()
        # db_execute("UPDATE users SET avatar=? WHERE username=?", (avatar, username))
    
    logger.info(f"✏️ Admin edited user: {username}")
    
    updated_user = get_user(username)
    return jsonify({"ok": True, "user": updated_user})

@bp.route("/api/admin/user/<username>/delete", methods=["POST"])
def api_admin_delete_user(username):
    """Админ удаляет аккаунт игрока."""
    err = _admin()
    if err: return err
    
    if not confirm(f"Вы уверены что хотите удалить аккаунт {username}?", body):
        return jsonify({"error": "Confirmation required"}), 400
    
    # Удаление из БД
    # db_execute("DELETE FROM users WHERE username=?", (username,))
    # db_execute("DELETE FROM user_stats WHERE username=?", (username,))
    
    logger.warning(f"🗑️ Admin deleted user: {username}")
    
    return jsonify({"ok": True, "message": f"Аккаунт {username} удалён"})

# ─── Профили пользователей ────────────────────────────────────────────────────

@bp.route("/api/profile", methods=["GET"])
def api_profile():
    """Получить свой профиль."""
    u = _auth_user()
    if not u:
        return jsonify({"error": "Не авторизован"}), 401
    
    user = get_user(u)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    
    user["level"] = get_level_from_xp(user.get("xp", 0))
    user["achievements"] = get_achievements(u)
    user["campaign_progress"] = get_campaign_progress(u)
    
    return jsonify({"profile": user})

@bp.route("/api/profile/<username>", methods=["GET"])
def api_public_profile(username):
    """Публичный профиль (других пользователей)."""
    user = get_user(username)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    
    user["level"] = get_level_from_xp(user.get("xp", 0))
    user["achievements"] = get_achievements(username)
    user["campaign_progress"] = get_campaign_progress(username)
    
    # Не показываем чувствительные данные
    public_profile = {
        "username": user["username"],
        "display_name": user.get("display_name", user["username"]),
        "avatar": user.get("avatar", "default"),
        "total_score": user["total_score"],
        "games_played": user["games_played"],
        "wins": user["wins"],
        "coins": user["coins"],
        "xp": user["xp"],
        "level": user["level"],
        "achievements_count": len(user["achievements"]),
        "rank": get_player_rank(username)["rank"]
    }
    
    return jsonify({"profile": public_profile})

@bp.route("/api/profile/update", methods=["POST"])
def api_update_profile():
    """Обновить свой профиль."""
    u = _auth_user()
    if not u:
        return jsonify({"error": "Не авторизован"}), 401
    
    body = request.get_json(silent=True) or {}
    
    # Что может менять сам пользователь
    if "display_name" in body:
        new_name = str(body["display_name"]).strip()
        if len(new_name) > 50 or len(new_name) < 2:
            return jsonify({"error": "Имя должно быть 2-50 символов"}), 400
        # db_execute("UPDATE users SET display_name=? WHERE username=?", (new_name, u))
    
    if "avatar" in body:
        avatar = str(body["avatar"]).strip()
        # Валидация аватара
        # db_execute("UPDATE users SET avatar=? WHERE username=?", (avatar, u))
    
    logger.info(f"✏️ User updated profile: {u}")
    
    updated_user = get_user(u)
    return jsonify({"ok": True, "profile": updated_user})

@bp.route("/api/profile/delete", methods=["POST"])
def api_delete_profile():
    """Удалить свой аккаунт."""
    u = _auth_user()
    if not u:
        return jsonify({"error": "Не авторизован"}), 401
    
    body = request.get_json(silent=True) or {}
    confirm = str(body.get("confirm","")).strip()
    
    if confirm != "DELETE_MY_ACCOUNT":
        return jsonify({"error": "Подтвердите удаление: DELETE_MY_ACCOUNT"}), 400
    
    # Удаление аккаунта
    # db_execute("DELETE FROM users WHERE username=?", (u,))
    # db_execute("DELETE FROM user_stats WHERE username=?", (u,))
    session.pop("username", None)
    
    logger.warning(f"🗑️ User deleted account: {u}")
    
    return jsonify({"ok": True, "message": "Аккаунт удалён"})

