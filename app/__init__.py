from flask import Flask
from flask_socketio import SocketIO
import os, logging

logging.basicConfig(level=logging.INFO)

socketio = SocketIO()
CHEAT_NICK = "pasha1778"

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
