# -*- coding: utf-8 -*-
"""
wsgi.py — точка входа для Gunicorn (Render, VPS).
Команда: gunicorn --worker-class eventlet -w 1 wsgi:application --bind 0.0.0.0:$PORT
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app, socketio

application = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    socketio.run(application, host="0.0.0.0", port=port)
