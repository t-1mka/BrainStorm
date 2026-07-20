#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSGI entry point for Render deployment
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app import create_app, socketio

app = create_app()
