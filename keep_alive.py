from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: rgba(255,255,255,0.1);
                padding: 30px;
                border-radius: 10px;
                backdrop-filter: blur(10px);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Discord Bot Online</h1>
            <p>Бот работает 24/7 на Replit</p>
            <p>Пинг бота: <span id="ping">...</span>ms</p>
        </div>
        <script>
            // Опционально: можно добавить динамическое обновление
        </script>
    </body>
    </html>
    """

@app.route('/ping')
def ping():
    return "pong"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()
