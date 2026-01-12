import sys
import os

# アプリのルートディレクトリを Python パスに追加
sys.path.insert(0, '/home/yvofxbku/apathy-screen-app')

# FastAPI 本体
from app.main import app

# ASGI → WSGI 変換ラッパー
from asgiref.wsgi import WsgiToAsgi

wsgi_app = WsgiToAsgi(app)

