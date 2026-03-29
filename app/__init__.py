from flask import Flask
from flask_socketio import SocketIO
import os, logging
<<<<<<< HEAD
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

socketio = SocketIO()

# Коды доступа берутся исключительно из .env / переменных окружения
CHEAT_CODE       = os.getenv("CHEAT_CODE", "1778")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "1379")

=======

logging.basicConfig(level=logging.INFO)

socketio = SocketIO()
CHEAT_NICK = "pasha1778"
>>>>>>> origin/main

def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )
    app.secret_key = os.getenv("SECRET_KEY", "brainstorm-secret-2024")

    from .routes import bp
    app.register_blueprint(bp)

    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="eventlet",
        logger=False,
        engineio_logger=False,
    )

    from . import socket_events  # noqa: F401

    return app
