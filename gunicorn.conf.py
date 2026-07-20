# Gunicorn configuration for Render
import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "eventlet"
worker_connections = 1000
timeout = 120
keepalive = 5
