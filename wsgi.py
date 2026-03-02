# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app, socketio

application = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    socketio.run(application, host="0.0.0.0", port=port)
