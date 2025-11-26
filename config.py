# config.py
import os

BOT_TOKEN = os.environ["BOT_TOKEN"]          # в Render додамо як змінну
DB_PATH = os.environ.get("DB_PATH", "bot.db")  # локально буде bot.db
