import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")  # напр. https://gpt5pro-bot.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "hook-" + os.urandom(8).hex())
PORT = int(os.environ.get("PORT", "10000"))  # Render прокидывает PORT сам
