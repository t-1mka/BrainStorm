# -*- coding: utf-8 -*-
import os, time, logging
from flask import Blueprint, render_template, jsonify, request, session
from .game_logic import (
    get_leaderboard_top, get_player_rank, rooms,
    ban_user, unban_user, get_all_bans,
    get_room_history, get_all_users, reset_user_stats, reset_server_stats
)
from .ai_client import active_backend

logger = logging.getLogger(__name__)
bp     = Blueprint("main", __name__)
ADMIN_KEY = os.getenv("ADMIN_SECRET_KEY", "1379")

def _admin():
    if not session.get("is_admin"): return jsonify({"error": "Нет доступа"}), 403

@bp.route("/")
def index(): return render_template("index.html")

@bp.route("/health")
def health(): return jsonify({"status": "ok", "ts": time.time(), "ai": active_backend()})

@bp.route("/api/leaderboard")
def api_leaderboard():
    n = min(int(request.args.get("n", 50)), 200)
    return jsonify(get_leaderboard_top(n))

@bp.route("/api/rank/<username>")
def api_rank(username): return jsonify(get_player_rank(username))

@bp.route("/api/public_rooms")
def api_public_rooms():
    return jsonify([{"code": r.code, "state": r.state, "players": len(r.human_players),
                     "mode": r.mode, "topic": r.settings.get("topic", "")}
                    for r in rooms.values() if getattr(r, "is_public", False) and r.state in ("waiting", "playing")])

@bp.route("/api/rooms")
def api_rooms():
    return jsonify([{"code": r.code, "state": r.state, "players": len(r.players), "mode": r.mode} for r in rooms.values()])

@bp.route("/verify_admin", methods=["POST"])
def verify_admin():
    body = request.get_json(silent=True) or {}
    if str(body.get("key","")).strip() == ADMIN_KEY:
        session["is_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403

@bp.route("/api/admin/logout", methods=["POST"])
def api_admin_logout(): session.pop("is_admin", None); return jsonify({"ok": True})

@bp.route("/api/admin/rooms")
def api_admin_rooms():
    err = _admin()
    if err: return err
    return jsonify([{"code": r.code, "state": r.state, "players": len(r.players), "mode": r.mode,
                     "host": (r.players[r.host_sid].name if r.host_sid in r.players else ""),
                     "is_public": getattr(r,"is_public",False), "topic": r.settings.get("topic",""),
                     "is_sandbox": getattr(r,"is_sandbox",False)}
                    for r in rooms.values()])

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
    removed = sum(1 for c in list(rooms.keys()) if rooms[c].state == "finished" and not rooms.pop(c, None) is None)
    return jsonify({"ok": ok, "removed_rooms": removed})

@bp.route("/api/cheat/room_stats/<code>")
def api_cheat_stats(code):
    r = rooms.get(code.upper())
    if not r: return jsonify({"error": "not found"}), 404
    q = r.current_question
    if not q: return jsonify({"answers": {}})
    counts = {}; players = {}
    for p in r.players.values():
        if p.answered and p.answer_index is not None:
            i = p.answer_index
            counts[i] = counts.get(i,0)+1
            players.setdefault(i,[]).append(p.name)
    return jsonify({"answer_counts": counts, "answer_players": players,
                    "total_answered": sum(1 for p in r.players.values() if p.answered),
                    "total_active": len(r.active_players)})
