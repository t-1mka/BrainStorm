#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BrainStorm — точка запуска для локальной разработки.
Запуск: python run.py
"""

import os, sys, logging

# ── Кодировка ─────────────────────────────────────────────
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except: pass

if sys.version_info < (3, 10):
    print("Нужен Python 3.10+"); sys.exit(1)

# ── Загружаем .env ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
example  = os.path.join(BASE_DIR, ".env.example")

if not os.path.exists(env_path):
    if os.path.exists(example):
        import shutil; shutil.copy(example, env_path)
        print("Создан .env из шаблона.")

try:
    from dotenv import load_dotenv
    load_dotenv(env_path, override=False)
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv", "-q"])
    from dotenv import load_dotenv
    load_dotenv(env_path, override=False)

# ── Устанавливаем зависимости ──────────────────────────────
req_file = os.path.join(BASE_DIR, "requirements.txt")
if os.path.exists(req_file):
    import subprocess
    print("Проверяю зависимости...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file, "-q", "--disable-pip-version-check"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("Ошибка:", r.stderr[:300]); sys.exit(1)
    print("Зависимости OK")

# ── Логирование ────────────────────────────────────────────
log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for q in ("engineio", "socketio", "urllib3", "werkzeug"):
    logging.getLogger(q).setLevel(logging.WARNING)

# ── Запуск ─────────────────────────────────────────────────
import socket as _socket

def get_local_ip():
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

from app import create_app, socketio
from app.ai_client import active_backend

app     = create_app()
host    = os.getenv("HOST", "0.0.0.0")
port    = int(os.getenv("PORT", 5000))
debug   = os.getenv("DEBUG", "false").lower() == "true"
ip      = get_local_ip()
ai_info = active_backend()
creds   = os.getenv("GIGACHAT_CREDENTIALS", "")

print()
print("+--------------------------------------------------+")
print("|  MOZGOVOY SHTURM  -  server started!            |")
print("+--------------------------------------------------+")
print("|  Local:   http://localhost:" + str(port) + "                  |")
print("|  Network: http://" + ip + ":" + str(port) + "              |")
print("+--------------------------------------------------+")
print("|  AI: " + ai_info[:44] + (" " * max(0, 44 - len(ai_info))) + "  |")
if not creds:
    print("|  WARNING: GIGACHAT_CREDENTIALS not set!          |")
    print("|  Using fallback question bank                    |")
print("+--------------------------------------------------+")
print("|  Ctrl+C to stop                                  |")
print("+--------------------------------------------------+")
print()

socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
