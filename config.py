import os

# Токен бота беремо тільки з ENV (Render / .env локально)
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Шлях до SQLite бази
DB_PATH = os.environ.get("DB_PATH", "bot.db")
