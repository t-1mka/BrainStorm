# gunicorn.conf.py — конфигурация Gunicorn для Render
import os

# Eventlet обязателен для Flask-SocketIO
worker_class   = "eventlet"
workers        = 1          # eventlet должен быть 1 worker
threads        = 1
bind           = f"0.0.0.0:{os.getenv('PORT', '5000')}"

# Таймауты (важно для Render — долгие SocketIO-соединения)
timeout        = 120
keepalive      = 5
graceful_timeout = 30

# Логи — выводим в stdout (Render читает stdout)
accesslog      = "-"
errorlog       = "-"
loglevel       = os.getenv("LOG_LEVEL", "info").lower()

# Prefork memory (eventlet green threads не требуют RAM как OS-threads)
worker_connections = 1000

# Сжатие ответов через proxy (Render сам сжимает)
forwarded_allow_ips = "*"
proxy_protocol = False
