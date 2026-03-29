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
<<<<<<< HEAD

# Читаем коды из приложения (они уже загружены в __init__)
from . import ADMIN_SECRET_KEY, CHEAT_CODE
=======
ADMIN_KEY = os.getenv("ADMIN_SECRET_KEY", "1379")
>>>>>>> origin/main


def _admin():
    if not session.get("is_admin"):
        return jsonify({"error": "Нет доступа"}), 403
    return None

def _auth_user():
<<<<<<< HEAD
=======
    """Возвращает username из сессии или None."""
>>>>>>> origin/main
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


<<<<<<< HEAD
# ─── Лидерборд ────────────────────────────────────────────────────────────────
=======
# ─── Лидерборд и ранги ───────────────────────────────────────────────────────
>>>>>>> origin/main

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


<<<<<<< HEAD
# ─── UGC ─────────────────────────────────────────────────────────────────────
=======
# ─── UGC (пользовательские вопросы) ──────────────────────────────────────────
>>>>>>> origin/main

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
<<<<<<< HEAD
=======
        # Начисляем монеты за создание
>>>>>>> origin/main
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
<<<<<<< HEAD
=======
    # Гость видит уровни, все заблокированы
>>>>>>> origin/main
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
<<<<<<< HEAD
=======
    # Достижения
>>>>>>> origin/main
    if result["stars"] == 3:
        unlock_achievement(u, "perfect_level")
    new_achs = check_and_unlock_achievements(u)
    result["new_achievements"] = new_achs
    return jsonify(result)

<<<<<<< HEAD
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

=======
>>>>>>> origin/main

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
<<<<<<< HEAD
=======
    # Достижение за первый запуск режима обучения
>>>>>>> origin/main
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


<<<<<<< HEAD
# ─── Магазин ─────────────────────────────────────────────────────────────────
=======
# ─── Магазин (монеты) ─────────────────────────────────────────────────────────
>>>>>>> origin/main

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


<<<<<<< HEAD
# ─── Чит-меню (активация по коду) ────────────────────────────────────────────

@bp.route("/verify_cheat", methods=["POST"])
def verify_cheat():
    """Проверяет код чит-меню. Код хранится в .env как CHEAT_CODE."""
    body = request.get_json(silent=True) or {}
    key  = str(body.get("key","")).strip()
    if key == CHEAT_CODE:
        session["is_cheat"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403

@bp.route("/api/cheat/logout", methods=["POST"])
def api_cheat_logout():
    session.pop("is_cheat", None)
    return jsonify({"ok": True})


=======
>>>>>>> origin/main
# ─── Администрирование ────────────────────────────────────────────────────────

@bp.route("/verify_admin", methods=["POST"])
def verify_admin():
    body = request.get_json(silent=True) or {}
<<<<<<< HEAD
    if str(body.get("key","")).strip() == ADMIN_SECRET_KEY:
=======
    if str(body.get("key","")).strip() == ADMIN_KEY:
>>>>>>> origin/main
        session["is_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403

@bp.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})

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
<<<<<<< HEAD
=======


@bp.route("/api/campaign/start", methods=["POST"])
def api_campaign_start():
    """Генерирует вопросы для уровня кампании."""
    u = _auth_user()
    if not u: return jsonify({"error":"Не авторизован"}), 401
    body     = request.get_json(silent=True) or {}
    level_id = int(body.get("level_id", 0))
    level    = next((l for l in CAMPAIGN_LEVELS if l["id"]==level_id), None)
    if not level:
        return jsonify({"error": "Уровень не найден"}), 404
    # Проверяем доступность уровня
    prog = get_campaign_progress(u)
    total_stars = prog["total_stars"]
    if total_stars < level["req_stars"]:
        return jsonify({"error": f"Нужно {level['req_stars']} звёзд"}), 403
    from .ai_client import generate_questions
    questions = generate_questions(
        topic      = level["topic"],
        count      = level["questions"],
        difficulty = level["difficulty"],
        num_options = 4
    )
    return jsonify({"questions": questions, "level": level})
>>>>>>> origin/main
